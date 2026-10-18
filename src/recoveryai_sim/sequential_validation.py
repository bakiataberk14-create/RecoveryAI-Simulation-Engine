"""Evidence-based validation of the schema-2 execution and observation boundaries."""
from datetime import datetime,timedelta
import hashlib
import json
import sqlite3
from .sequential_schema import SCHEMA_V2
from .sequential_views import SEQUENCE_FEATURES
from .safety import Context, eligible_actions
from .views import load_training


def validate_v2(root,manifest):
    db=sqlite3.connect(f"{(root.resolve()/'simulation.sqlite').as_uri()}?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    checks,failures={},[]
    def check(name,violations):
        checks[name]=violations==0
        if violations:
            failures.append({"check":name,"violations":violations})
    def count(query):
        return db.execute(query).fetchone()[0]
    try:
        check("sqlite_integrity",int(db.execute("PRAGMA integrity_check").fetchone()[0]!="ok"))
        check("foreign_keys",len(db.execute("PRAGMA foreign_key_check").fetchall()))
        check("synthetic_manifest",int(manifest.get("billable") is not False or manifest.get("status")!="complete"))
        check("manifest_counts",sum(count(f"SELECT count(*) FROM {table}")!=manifest["counts"].get(table) for table in SCHEMA_V2))
        check("financial_balances",count("""SELECT count(*) FROM invoices WHERE amount_paid+amount_remaining<>amount_due
            OR refund_amount<0 OR refund_amount>amount_paid OR (status IN ('paid','refunded') AND amount_remaining<>0)"""))
        check("episode_accounting",count("SELECT count(*) FROM outcomes WHERE net_revenue<>gross_recovered-processing_cost-communication_cost-refund_amount"))
        check("single_collection",count("SELECT count(*) FROM (SELECT invoice_id FROM attempts WHERE result='succeeded' GROUP BY invoice_id HAVING count(*)>1)"))
        check("renewal_invoice_snapshot",count("""SELECT count(*) FROM renewal_slots r JOIN invoices i ON i.id=r.invoice_id
            WHERE r.tenant_id<>i.tenant_id OR r.subscription_id<>i.subscription_id OR r.amount_minor<>i.amount_due
            OR r.currency<>i.currency OR r.scheduled_at<>i.created_at"""))
        check("renewal_coverage",count("SELECT count(*) FROM invoices i WHERE NOT EXISTS (SELECT 1 FROM renewal_slots r WHERE r.invoice_id=i.id)"))
        check("renewal_budget",int(count("SELECT count(*) FROM renewal_slots")>manifest["config"]["invoices"]))
        relations=[("subscription_events","subscription_id","subscriptions"),("renewal_slots","subscription_id","subscriptions"),
            ("customers","merchant_id","merchants"),("subscriptions","customer_id","customers"),
            ("payment_methods","customer_id","customers"),("invoices","subscription_id","subscriptions"),
            ("actions","invoice_id","invoices"),("actions","customer_id","customers"),
            ("actions","previous_action_id","actions"),("actions","source_observation_id","observations"),
            ("attempts","invoice_id","invoices"),("attempts","method_id","payment_methods"),
            ("attempts","action_id","actions"),("communications","action_id","actions"),
            ("observations","invoice_id","invoices"),("observations","event_id","events"),
            ("deliveries","event_id","events"),("events","invoice_id","invoices"),
            ("action_results","action_id","actions"),("step_oracle","action_id","actions"),
            ("outcomes","invoice_id","invoices"),("outcomes","action_id","actions")]
        check("tenant_relations",sum(count(f"SELECT count(*) FROM {child} c JOIN {parent} p ON p.id=c.{fk} WHERE c.tenant_id<>p.tenant_id") for child,fk,parent in relations))
        check("currency_consistency",count("SELECT count(*) FROM invoices i JOIN subscriptions s ON s.id=i.subscription_id WHERE i.currency<>s.currency")+count("SELECT count(*) FROM outcomes o JOIN invoices i ON i.id=o.invoice_id WHERE o.currency<>i.currency"))
        check("observations_not_future",count("SELECT count(*) FROM observations WHERE available_at<occurred_at"))
        check("delivery_matches_observation",count("""SELECT count(*) FROM observations o WHERE NOT EXISTS
            (SELECT 1 FROM deliveries d WHERE d.event_id=o.event_id AND d.tenant_id=o.tenant_id AND d.delivered_at=o.available_at)"""))
        check("terminal_observation_sticky",count("""SELECT count(*) FROM observations f WHERE f.event_type='sim.payment_failed' AND f.applied=1
            AND EXISTS (SELECT 1 FROM observations t WHERE t.invoice_id=f.invoice_id AND t.tenant_id=f.tenant_id
            AND t.event_type IN ('sim.payment_succeeded','sim.refund') AND t.available_at<f.available_at)"""))
        check("bounded_steps",count(f"SELECT count(*) FROM actions WHERE step>{manifest['config']['max_steps']}"))
        check("bounded_retries",count(f"""SELECT count(*) FROM (SELECT invoice_id FROM actions WHERE selected='retry_day3' AND status='executed'
            GROUP BY invoice_id HAVING count(*)>{manifest['config']['max_retries']})"""))
        check("action_chain",count("""SELECT count(*) FROM actions a LEFT JOIN actions p ON p.id=a.previous_action_id
            WHERE (a.step=1 AND a.previous_action_id IS NOT NULL) OR
            (a.step>1 AND (p.id IS NULL OR p.invoice_id<>a.invoice_id OR p.step<>a.step-1 OR p.decision_at>a.decision_at))"""))
        source_errors,safety_errors=0,0
        for row in db.execute("SELECT a.*,m.issuing_country FROM actions a JOIN attempts initial ON initial.invoice_id=a.invoice_id AND initial.number=1 JOIN payment_methods m ON m.id=initial.method_id"):
            features=json.loads(row["features_json"])
            sources=json.loads(row["sources_json"])
            source_errors+=set(features)!=SEQUENCE_FEATURES or features["available_at"]>row["decision_at"] or not sources
            for ref in sources:
                if ref.get("kind")=="execution":
                    obs=db.execute("SELECT r.tenant_id,r.recorded_at AS available_at,a.customer_id FROM action_results r JOIN actions a ON a.id=r.action_id WHERE r.id=?",(ref["id"],)).fetchone()
                else:
                    obs=db.execute("SELECT o.*,sub.customer_id FROM observations o JOIN invoices i ON i.id=o.invoice_id JOIN subscriptions sub ON sub.id=i.subscription_id WHERE o.id=?",(ref["id"],)).fetchone()
                source_errors+=int(obs is None or obs["tenant_id"]!=row["tenant_id"] or obs["customer_id"]!=row["customer_id"] or obs["available_at"]!=ref["available_at"] or obs["available_at"]>row["decision_at"])
            source_errors+=row["source_observation_id"] not in {ref["id"] for ref in sources}
            legal=eligible_actions(Context(decline=features["decline_reason"],consent=features["consent"],
                method_active=features["known_method_state"]=="active",issuing_country=row["issuing_country"],
                retries=features["prior_retry_count"],max_retries=manifest["config"]["max_retries"]))
            listed=json.loads(row["eligible_json"])
            safety_errors+=row["selected"] not in listed or not set(listed)<=set(legal)
            safety_errors+=abs(row["propensity"]-(1/len(listed) if row["policy"]=="randomized" else 1))>1e-12
        check("snapshot_evidence_availability",source_errors)
        check("safe_logged_actions",safety_errors)
        check("execution_has_result",count("SELECT count(*) FROM actions a LEFT JOIN action_results r ON r.action_id=a.id WHERE a.status<>'scheduled' AND (r.id IS NULL OR r.result<>a.status)"))
        check("blocked_actions_no_dispatch",count("SELECT count(*) FROM communications c JOIN actions a ON a.id=c.action_id WHERE a.status<>'executed'")+count("SELECT count(*) FROM attempts p JOIN actions a ON a.id=p.action_id WHERE a.status NOT IN ('executed','observed','review_only')"))
        check("observe_no_communication",count("SELECT count(*) FROM communications c JOIN actions a ON a.id=c.action_id WHERE a.selected IN ('observe','review')"))
        check("delivery_funnel",count("SELECT count(*) FROM communications WHERE clicked>opened OR opened>delivered"))
        check("unique_episode_rewards",count("SELECT count(*) FROM outcomes")-count("SELECT count(DISTINCT invoice_id) FROM outcomes"))
        records=list(load_training(root))
        check("training_rows",int(len(records)!=count("SELECT count(*) FROM actions a JOIN outcomes o ON o.invoice_id=a.invoice_id")))
        check("no_duplicated_step_reward",sum(r["reward_30d_minor"] is not None for r in records))
        if manifest.get("causal_episode_contract"):
            causal_path=root/"evaluation/causal_episodes.jsonl"
            causal_rows=[json.loads(line) for line in causal_path.read_text(encoding="utf-8").splitlines()] if causal_path.is_file() else []
            bad=0
            for row in causal_rows:
                source=db.execute("SELECT i.tenant_id,i.currency,a.occurred_at FROM invoices i JOIN attempts a ON a.invoice_id=i.id AND a.number=1 AND a.result='failed' WHERE i.id=?",(row["invoice_id"],)).fetchone()
                bad+=int(source is None or source["tenant_id"]!=row["tenant_id"] or source["currency"]!=row["currency"] or source["occurred_at"]!=row["failure_at"])
                bad+=row["contract"]!=manifest["causal_episode_contract"] or row["synthetic"] is not True or row["billable"] is not False
                bad+=datetime.fromisoformat(row["financial_deadline"])-datetime.fromisoformat(row["failure_at"])!=timedelta(days=30)
                if row["status"]=="mature":
                    bad+=row["mature_after"]>row["observed_until"]
                    bad+=row["reward_minor"]!=row["gross_recovered_minor"]-row["refund_minor"]-row["processing_cost_minor"]-row["communication_cost_minor"]
                else:
                    bad+=row["reward_minor"] is not None
            check("fixed_causal_cohort",bad+int(len(causal_rows)!=count("SELECT count(*) FROM attempts WHERE number=1 AND result='failed'")))
            check("unique_causal_episode",len(causal_rows)-len({(r["tenant_id"],r["invoice_id"]) for r in causal_rows}))
        check("censored_training_labels",sum(value is not None and (datetime.fromisoformat(r["metadata"]["observed_until"])-datetime.fromisoformat(r["metadata"]["decision_at"])).total_seconds()<int(name.split('_')[1][:-1])*86400 for r in records for name,value in r["y"].items() if name.startswith("recovered_")))
        checksum_errors=0
        for relative,expected in manifest.get("logical_checksums",{}).items():
            path=(root/relative).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                checksum_errors+=1
                continue
            with path.open("rb") as content:
                checksum_errors+=hashlib.file_digest(content,"sha256").hexdigest()!=expected
        check("export_checksums",checksum_errors)
    finally:
        db.close()
    return {"passed":not failures,"checks":checks,"failures":failures,
        "warnings":["Synthetic sequential model; window effects are uncalibrated.",
                    "One-step policy estimators are blocked for this schema.",
                    "Retention remains a synthetic episode endpoint, not subscription churn dynamics."]}
