"""Failing validation returns explicit evidence, never a generic success badge."""
import json
from pathlib import Path
import sqlite3
import hashlib
from .safety import Context, eligible_actions
from .storage import SCHEMA
from .views import observable_features, load_training
from .replay import ReplayLedger


def validate(root: Path):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    db = sqlite3.connect(f"{(root / 'simulation.sqlite').as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    failures, checks = [], {}

    def check(name, violations):
        checks[name] = violations == 0
        if violations:
            failures.append({"check": name, "violations": violations})

    def count(query):
        return db.execute(query).fetchone()[0]

    try:
        check("sqlite_integrity", int(db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"))
        check("foreign_keys", len(db.execute("PRAGMA foreign_key_check").fetchall()))
        check("synthetic_manifest", int(manifest.get("billable") is not False or manifest.get("status") != "complete"))
        check("invoice_count", int(count("SELECT count(*) FROM invoices") != manifest["config"]["invoices"]))
        check("balances", count("""SELECT count(*) FROM invoices WHERE amount_paid+amount_remaining<>amount_due
              OR amount_paid<0 OR amount_remaining<0 OR refund_amount<0 OR refund_amount>amount_paid"""))
        check("outcome_accounting", count("""SELECT count(*) FROM outcomes WHERE
              net_revenue<>gross_recovered-processing_cost-communication_cost-refund_amount"""))
        relations = [("customers", "merchant_id", "merchants"), ("subscriptions", "customer_id", "customers"),
                     ("payment_methods", "customer_id", "customers"), ("invoices", "subscription_id", "subscriptions"),
                     ("actions", "invoice_id", "invoices"), ("actions", "customer_id", "customers"),
                     ("attempts", "invoice_id", "invoices"), ("attempts", "method_id", "payment_methods"),
                     ("attempts", "action_id", "actions"), ("communications", "action_id", "actions"),
                     ("outcomes", "action_id", "actions"), ("outcomes", "invoice_id", "invoices"),
                     ("events", "invoice_id", "invoices"), ("deliveries", "event_id", "events"),
                     ("oracle", "action_id", "actions")]
        check("tenant_foreign_keys", sum(count(f"SELECT count(*) FROM {child} c JOIN {parent} p ON c.{fk}=p.id WHERE c.tenant_id<>p.tenant_id") for child, fk, parent in relations))
        check("currency_consistency", count("SELECT count(*) FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id WHERE i.currency<>s.currency") + count("SELECT count(*) FROM outcomes o JOIN invoices i ON i.id=o.invoice_id WHERE o.currency<>i.currency"))
        check("temporal_order", count("SELECT count(*) FROM attempts a JOIN invoices i ON i.id=a.invoice_id WHERE a.occurred_at<i.created_at") + count("SELECT count(*) FROM deliveries d JOIN events e ON e.id=d.event_id WHERE d.delivered_at<e.occurred_at"))
        check("no_double_collection", count("SELECT count(*) FROM (SELECT invoice_id FROM attempts WHERE result='succeeded' GROUP BY invoice_id HAVING count(*)>1)"))
        safety_errors, feature_errors = 0, 0
        for action in db.execute("SELECT a.*, m.issuing_country FROM actions a JOIN attempts p ON p.invoice_id=a.invoice_id AND p.number=1 JOIN payment_methods m ON m.id=p.method_id"):
            raw = json.loads(action["features_json"])
            legal = eligible_actions(Context(decline=raw["decline_reason"], consent=raw["consent"],
                                     issuing_country=action["issuing_country"], max_retries=manifest["config"]["max_retries"]))
            safety_errors += action["selected"] not in legal or tuple(json.loads(action["eligible_json"])) != legal
            try:
                observable_features(raw, action["decision_at"])
            except ValueError:
                feature_errors += 1
        check("safe_actions", safety_errors)
        check("feature_availability", feature_errors)
        check("observe_no_customer_action", count("SELECT count(*) FROM communications c JOIN actions a ON a.id=c.action_id WHERE a.selected IN ('observe','review')"))
        check("delivery_funnel", count("SELECT count(*) FROM communications WHERE clicked>opened OR opened>delivered"))
        check("censored_targets", count("""SELECT count(*) FROM outcomes o JOIN actions a ON a.id=o.action_id
              WHERE (julianday(o.observed_until)-julianday(a.decision_at)<30 AND o.recovered_30d IS NOT NULL)
                 OR (julianday(o.observed_until)-julianday(a.decision_at)<90 AND o.retention_90d IS NOT NULL)"""))
        check("manifest_counts", sum(count(f"SELECT count(*) FROM {t}") != manifest["counts"].get(t) for t in SCHEMA))
        checksum_errors = 0
        for relative, expected in manifest.get("logical_checksums", {}).items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                checksum_errors += 1
                continue
            with path.open("rb") as content:
                checksum_errors += hashlib.file_digest(content, "sha256").hexdigest() != expected
        check("export_checksums", checksum_errors)
        training_count = sum(1 for _ in load_training(root))
        check("training_row_count", int(training_count != count("SELECT count(*) FROM actions")))
        ledgers = {}
        replay_errors = 0
        for event in db.execute("SELECT e.* FROM deliveries d JOIN events e ON e.id=d.event_id ORDER BY d.delivered_at,d.id"):
            ledger = ledgers.setdefault(event["tenant_id"], ReplayLedger(event["tenant_id"]))
            ledger.apply(event)
            before = (ledger.paid.copy(), ledger.refunded.copy())
            replay_errors += ledger.apply(event) is not False
            replay_errors += before != (ledger.paid, ledger.refunded)
        expected = {}
        for row in db.execute("""SELECT DISTINCT e.tenant_id,e.invoice_id FROM events e JOIN deliveries d ON d.event_id=e.id
            WHERE e.event_type='sim.payment_succeeded' AND NOT EXISTS (
                SELECT 1 FROM events r JOIN deliveries rd ON rd.event_id=r.id
                WHERE r.invoice_id=e.invoice_id AND r.tenant_id=e.tenant_id AND r.event_type='sim.refund')"""):
            expected.setdefault(row[0], set()).add(row[1])
        replay_errors += sum(ledger.settled != expected.get(tenant, set()) for tenant, ledger in ledgers.items())
        check("replay_no_double_effect", replay_errors)
    finally:
        db.close()
    return {"passed": not failures, "checks": checks, "failures": failures,
            "warnings": ["Synthetic evidence only; not provider integration certification.",
                         "One recovery decision per invoice; no full sequential treatment model.",
                         "No real merchant calibration or empirical recovery-rate claim."]}
