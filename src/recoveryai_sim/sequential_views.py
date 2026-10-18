"""Sequence features are observed evidence; episode cash appears exactly once."""
from datetime import datetime, timedelta
import json
from .views import FEATURES
from .storage import encode

SEQUENCE_FEATURES = FEATURES | {"step","prior_contact_count","prior_retry_count","known_invoice_state",
    "known_method_state","observed_delivery_count","observation_lag_days"}


def export_training_v2(db,root):
    folder=root/"training"
    folder.mkdir()
    query="""SELECT a.*,c.merchant_id,o.recovered_at,o.retention_90d,o.observed_until,o.measurement_status
        FROM actions a JOIN customers c ON c.id=a.customer_id AND c.tenant_id=a.tenant_id
        JOIN outcomes o ON o.invoice_id=a.invoice_id AND o.tenant_id=a.tenant_id ORDER BY a.id"""
    with (folder/"decisions.jsonl").open("w",encoding="utf-8",newline="\n") as target:
        for row in db.execute(query):
            features=json.loads(row["features_json"])
            if set(features)!=SEQUENCE_FEATURES or features["available_at"]>row["decision_at"]:
                raise ValueError("Sequential feature availability violation")
            decision=datetime.fromisoformat(row["decision_at"])
            until=datetime.fromisoformat(row["observed_until"])
            paid=datetime.fromisoformat(row["recovered_at"]) if row["recovered_at"] else None
            measurable=row["measurement_status"]=="observed" and (paid is None or paid>=decision)
            labels={f"recovered_{days}d":int(paid is not None and paid<=decision+timedelta(days=days))
                    if until>=decision+timedelta(days=days) and measurable else None for days in (7,14,30)}
            # Retention is still an episode endpoint, never relabeled as 90 days from every action.
            labels["retention_90d"]=row["retention_90d"] if row["step"]==1 else None
            target.write(encode({"schema_version":"2","synthetic":True,
                "x":{key:features[key] for key in sorted(SEQUENCE_FEATURES-{"available_at"})},
                "metadata":{key:row[key] for key in ("id","tenant_id","merchant_id","customer_id","invoice_id","decision_at","observed_until","step")},
                "policy":{"selected":row["selected"],"eligible":json.loads(row["eligible_json"]),
                          "propensity":row["propensity"],"logging_policy":row["policy"]},
                "y":labels,"reward_30d_minor":None})+"\n")
    with (folder/"episodes.jsonl").open("w",encoding="utf-8",newline="\n") as target:
        for row in db.execute("SELECT * FROM outcomes ORDER BY id"):
            target.write(encode({"schema_version":"2","synthetic":True,"invoice_id":row["invoice_id"],
                "tenant_id":row["tenant_id"],"currency":row["currency"],"measurement_status":row["measurement_status"],
                "window_complete":bool(row["window_complete"]),"reward_30d_minor":row["net_revenue"] if row["window_complete"] else None})+"\n")
