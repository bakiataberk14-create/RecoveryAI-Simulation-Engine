"""Complete policy reruns on identical initial worlds and fixed failure cohorts."""
from collections import Counter,defaultdict
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

from .config import POLICIES,SCENARIOS
from .engine import generate
from .trajectory import causal_episodes,CONTRACT
from .policy_statistics import contrast_summary
from .validation import validate


def paired_currency_report(pairs,seed=42,bootstrap=200):
    groups=defaultdict(list)
    seen=set()
    for world,baseline,target in pairs:
        key=(world,baseline["tenant_id"],baseline["invoice_id"])
        if key in seen:
            raise ValueError("Duplicate episode in comparison cohort")
        seen.add(key)
        identity=("invoice_id","tenant_id","customer_id","merchant_id","currency","failure_at","amount_due_minor","financial_deadline","mature_after")
        if any(baseline[key]!=target[key] for key in identity):
            raise ValueError("Policy comparison changed the enrolled cohort")
        groups[baseline["currency"]].append((world,baseline,target))
    results={}
    for currency,group in sorted(groups.items()):
        maturity=Counter()
        mature=[]
        for world,baseline,target in group:
            if baseline["status"]==target["status"]=="censored":
                maturity["administratively_censored"]+=1
            elif baseline["status"]==target["status"]=="mature":
                maturity["mature_pairs"]+=1
                mature.append((world,baseline,target))
            else:
                maturity["unresolved_or_incompatible"]+=1
        if maturity["unresolved_or_incompatible"]:
            results[currency]={"status":"blocked","reason":"Incomplete provider evidence; no outcome-dependent case dropping",
                               "cohort_size":len(group),"maturity":dict(maturity)}
            continue
        units=[{"world":world,"merchant":b["merchant_id"],"n":1,"baseline":b["reward_minor"],"target":t["reward_minor"]}
               for world,b,t in mature]
        summary=contrast_summary(units,seed,bootstrap)
        summary.update(cohort_size=len(group),maturity=dict(maturity))
        if mature:
            n=len(mature)
            base_success=sum(b["recovered_30d"] for _,b,_ in mature)
            target_success=sum(t["recovered_30d"] for _,_,t in mature)
            base_cost=sum(b["processing_cost_minor"]+b["communication_cost_minor"] for _,b,_ in mature)
            target_cost=sum(t["processing_cost_minor"]+t["communication_cost_minor"] for _,_,t in mature)
            summary.update(baseline_recovery_rate_30d=base_success/n,target_recovery_rate_30d=target_success/n,
                recovery_difference_pp=100*(target_success-base_success)/n,
                baseline_cost_minor_per_failed_invoice=base_cost/n,target_cost_minor_per_failed_invoice=target_cost/n,
                additional_cost_minor_per_incremental_recovered_invoice=(target_cost-base_cost)/(target_success-base_success) if target_success>base_success else None,
                reduction_in_restricted_unpaid_days=sum(b["restricted_unpaid_days"]-t["restricted_unpaid_days"] for _,b,t in mature)/n,
                baseline_no_decision_invoices=sum(b["decision_count"]==0 for _,b,_ in mature),
                target_no_decision_invoices=sum(t["decision_count"]==0 for _,_,t in mature))
        results[currency]=summary
    return results


def compare_policies(config,output:Path,seeds=(42,43),scenarios=None,policies=("observe","fixed_retry","rule_based"),bootstrap=200):
    seeds,policies=tuple(seeds),tuple(policies)
    scenarios=tuple(scenarios) if scenarios is not None else (config.scenario,)
    if config.schema_version!="2":
        raise ValueError("Full trajectory comparison requires schema2")
    if not seeds or len(set(seeds))!=len(seeds) or any(type(s) is not int or s<0 for s in seeds):
        raise ValueError("Unique nonnegative integer seeds required")
    if not scenarios or len(set(scenarios))!=len(scenarios) or not set(scenarios)<=set(SCENARIOS):
        raise ValueError("Unique known scenarios required")
    if not policies or len(set(policies))!=len(policies) or not set(policies)<=set(POLICIES):
        raise ValueError("Unique known policies required")
    if type(bootstrap) is not int or bootstrap<20:
        raise ValueError("At least20 bootstrap replicates required")
    policies=("observe",)+tuple(p for p in policies if p!="observe")
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    report={"status":"complete","synthetic_only":True,"contract":CONTRACT,
        "method":"paired complete policy rollout with common exogenous noise",
        "baseline":"observe","seeds":list(seeds),"policies":list(policies),"scenarios":{},"runs":[],
        "limitations":["Conditional simulator evidence, not real merchant lift.",
                       "Confidence intervals resample merchants within the fixed generated worlds.",
                       "Initial-payment failure mechanism and fixed enrollment are held constant across policies."]}
    reference_source=None
    for scenario in scenarios:
        contrasts={policy:[] for policy in policies}
        for seed in seeds:
            worlds={}
            initial_hash=None
            for policy in policies:
                folder=output/f"{scenario}-{seed}-{policy}"
                cfg=replace(config,scenario=scenario,seed=seed,policy=policy)
                manifest=generate(cfg,folder)
                if reference_source is not None and manifest["source_sha256"]!=reference_source:
                    raise ValueError("Source changed between policy runs")
                reference_source=manifest["source_sha256"]
                validation=validate(folder.resolve())
                if not validation["passed"]:
                    raise ValueError(f"Policy run failed invariant checks: {scenario}/{seed}/{policy}")
                if initial_hash is not None and manifest["initial_world_sha256"]!=initial_hash:
                    raise ValueError("Policies did not start from the same initial world")
                initial_hash=manifest["initial_world_sha256"]
                db=sqlite3.connect(f"{(folder.resolve()/'simulation.sqlite').as_uri()}?mode=ro",uri=True)
                db.row_factory=sqlite3.Row
                try:
                    worlds[policy]={(r["tenant_id"],r["invoice_id"]):r for r in causal_episodes(db,cfg)}
                finally:
                    db.close()
                report["runs"].append({"scenario":scenario,"seed":seed,"policy":policy,"path":folder.name,
                    "initial_world_sha256":initial_hash,"source_sha256":manifest["source_sha256"],
                    "config_sha256":manifest["config_sha256"],"validation_groups":len(validation["checks"]),
                    "failed_invoice_cohort":len(worlds[policy])})
            baseline=worlds["observe"]
            for policy in policies:
                if set(worlds[policy])!=set(baseline):
                    raise ValueError("Initial failed-invoice enrollment changed across policies")
                for key in sorted(baseline):
                    contrasts[policy].append((str(seed),baseline[key],worlds[policy][key]))
        report["scenarios"][scenario]={policy:paired_currency_report(pairs,bootstrap=bootstrap) for policy,pairs in contrasts.items()}
    (output/"policy_comparison_report.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    return report
