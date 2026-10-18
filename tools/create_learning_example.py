"""Create a tiny SYNTHETIC contract example. Not merchant data or model evidence."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

from recoveryai_sim.learning_contract import CONTRACT, FEATURE_SOURCES


def ref(prefix, label):
    return prefix+"_"+hashlib.sha256(label.encode()).hexdigest()


def example():
    tenants = [ref("t",f"synthetic-tenant-{i}") for i in range(2)]
    permission = dict(contract=CONTRACT,permission_granted=True,purpose="offline_decision_research",
        tenant_refs=tenants,environment="synthetic",data_origin="synthetic",source_version="synthetic-example-1",
        exported_at="2026-06-01T00:00:00+00:00",expires_at="2099-01-01T00:00:00+00:00",
        retention_until="2099-01-01T00:00:00+00:00")
    split = dict(contract=CONTRACT,train_before="2026-03-01T00:00:00+00:00",
                 test_from="2026-04-01T00:00:00+00:00",heldout_tenants=[tenants[1]])
    records = []
    for i, month in enumerate((1,4)):
        failure = datetime(2026,month,1,tzinfo=timezone.utc)
        decision = failure+timedelta(hours=1)
        outcome = dict(status="provider_confirmed_paid",window_end=(failure+timedelta(days=30)).isoformat(),
            available_at=(failure+timedelta(days=31)).isoformat(),provider_event_ref=ref("p",f"synthetic-payment-{i}"),
            paid_at=(failure+timedelta(days=3)).isoformat(),gross_recovered_minor=10000,refund_minor=0,
            processing_cost_minor=5,communication_cost_minor=0,service_fee_minor=1500)
        records.append(dict(contract=CONTRACT,tenant_ref=tenants[i],customer_ref=ref("c",f"synthetic-customer-{i}"),
            recovery_ref=ref("r",f"synthetic-recovery-{i}"),decision_ref=ref("d",f"synthetic-decision-{i}"),
            environment="synthetic",provider="iyzico",first_failure_at=failure.isoformat(),decision_at=decision.isoformat(),
            amount_minor=10000,currency="TRY",decline_reason="insufficient_funds",attempt_count=1,
            policy_version="observe-1",model_version=None,selected_action="observe",eligible_actions=["observe","review"],
            propensity=.5,features={name:None for name in FEATURE_SOURCES},
            execution=dict(status="not_executed",executed_at=None,execution_ref=None,delivery_status="not_applicable",message_ref=None),
            outcome=outcome))
    return permission,split,records


def write_example(output):
    output = Path(output)
    output.mkdir(parents=True,exist_ok=False)
    permission,split,records = example()
    for name,record in (("permission.json",permission),("split.json",split)):
        (output/name).write_text(json.dumps(record,indent=2),encoding="utf-8")
    with (output/"episodes.jsonl").open("w",encoding="utf-8",newline="\n") as target:
        for record in records:
            target.write(json.dumps(record,sort_keys=True,allow_nan=False)+"\n")


if __name__ == "__main__":
    write_example(sys.argv[1])
