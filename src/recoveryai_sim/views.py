"""Positive allowlist boundary for decision-time features. Labels live separately."""
import json
from .storage import encode

FEATURES = {"amount_minor", "currency", "decline_reason", "decline_category", "attempt_count",
            "subscription_age_days", "past_successes", "past_failures", "engagement", "consent", "available_at"}
MODEL_FEATURES = FEATURES - {"available_at"}


def observable_features(raw, decision_at):
    if set(raw) != FEATURES or raw["available_at"] > decision_at:
        raise ValueError("Feature contract violation: unknown, missing or future feature")
    return {key: raw[key] for key in sorted(MODEL_FEATURES)}


def export_training(db, root):
    folder = root / "training"
    folder.mkdir()
    query = """SELECT a.*, c.merchant_id, o.recovered_7d, o.recovered_14d, o.recovered_30d,
        o.retention_90d, o.net_revenue, o.window_complete, o.observed_until
        FROM actions a JOIN outcomes o ON o.action_id=a.id AND o.tenant_id=a.tenant_id
        JOIN customers c ON c.id=a.customer_id AND c.tenant_id=a.tenant_id ORDER BY a.id"""
    with (folder / "decisions.jsonl").open("w", encoding="utf-8", newline="\n") as target:
        for row in db.execute(query):
            raw = json.loads(row["features_json"])
            record = {"synthetic": True, "x": observable_features(raw, row["decision_at"]),
                      "metadata": {key: row[key] for key in ("id", "tenant_id", "merchant_id", "customer_id", "decision_at", "observed_until")},
                      "policy": {"selected": row["selected"], "eligible": json.loads(row["eligible_json"]),
                                 "propensity": row["propensity"], "logging_policy": row["policy"]},
                      "y": {key: row[key] for key in ("recovered_7d", "recovered_14d", "recovered_30d", "retention_90d")},
                      "reward_30d_minor": row["net_revenue"] if row["window_complete"] else None}
            target.write(encode(record)+"\n")


def load_training(root):
    # Never take caller-specified oracle files as a training input.
    with (root / "training" / "decisions.jsonl").open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            if record.get("synthetic") is not True or set(record["x"]) != MODEL_FEATURES:
                raise ValueError("Not an approved synthetic training view")
            yield record
