"""Full customer-history importance sampling with one financial return per invoice.

Weights cover all customer decisions through the latest enrolled reward deadline,
including earlier invoices and overlapping censored invoices. This avoids treating
successive invoices sharing history/methods as independent treatment episodes.
"""
from collections import Counter,defaultdict
import json
import math
import sqlite3
import sys

from .config import Config
from .trajectory import causal_episodes,CONTRACT
from .sequence_policy import choose,POLICY_VERSION
from .policy_statistics import contrast_summary
from .validation import validate
from .sequential_views import SEQUENCE_FEATURES


def trajectory_weight(policy,actions):
    log_weight=0.0
    matches=True
    for action in actions:
        legal=tuple(action["eligible"])
        p=action["propensity"]
        if not legal or isinstance(p,bool) or not isinstance(p,(int,float)) or not math.isfinite(p) or p<=0 or p>1:
            raise ValueError("Invalid trajectory propensity")
        if action["logging_policy"]!="randomized" or abs(p-1/len(legal))>1e-12:
            raise ValueError("Known full-support randomized behavior required")
        chosen,_=choose(policy,legal,action["prior_contacts"])
        matches=matches and action["selected"]==chosen
        log_weight-=math.log(p)
    if not matches:
        return 0.0
    if log_weight>math.log(sys.float_info.max):
        raise ValueError("Trajectory weight exceeds numeric range; no silent clipping")
    return math.exp(log_weight)


def support(weights,has_decisions):
    total=sum(weights)
    squares=sum(w*w for w in weights)
    if not math.isfinite(total) or not math.isfinite(squares):
        raise ValueError("Trajectory moments exceed numeric range")
    decision_weights=[w for w,d in zip(weights,has_decisions) if d]
    ds=sum(decision_weights)
    dq=sum(w*w for w in decision_weights)
    return {"customers":len(weights),"decision_customers":sum(has_decisions),
        "matched_customers":sum(w>0 for w in weights),"matched_decision_customers":sum(w>0 for w in decision_weights),
        "decisionless_customers":len(weights)-sum(has_decisions),"mean_weight":total/len(weights) if weights else None,
        "max_weight":max(weights,default=0),"effective_sample_size":total*total/squares if squares else 0,
        "decision_customer_ess":ds*ds/dq if dq else 0}


def evaluate_trajectories(root,target_policy="rule_based",bootstrap=200,min_ess=30,min_clusters=5):
    if target_policy not in {"observe","fixed_retry","rule_based"}:
        raise ValueError("Deterministic supported target policy required")
    if type(min_ess) is not int or min_ess<1 or type(min_clusters) is not int or min_clusters<1:
        raise ValueError("Positive support thresholds required")
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    config=Config(**manifest["config"])
    if config.schema_version!="2" or config.policy!="randomized":
        return {"status":"blocked","reason":"Schema2 randomized logging required for trajectory OPE","synthetic_only":True}
    validation=validate(root.resolve())
    if not validation["passed"]:
        return {"status":"blocked","reason":"Input artifact failed validation","checks":validation["failures"]}
    db=sqlite3.connect(f"{(root.resolve()/'simulation.sqlite').as_uri()}?mode=ro",uri=True)
    db.row_factory=sqlite3.Row
    try:
        episodes=list(causal_episodes(db,config))
        customers=defaultdict(list)
        maturity=defaultdict(Counter)
        for row in episodes:
            maturity[row["currency"]][row["status"]]+=1
            if row["status"]=="mature":
                customers[(row["tenant_id"],row["customer_id"])].append(row)
        groups=defaultdict(list)
        for (tenant,customer),rows in customers.items():
            deadline=max(r["financial_deadline"] for r in rows)
            actions=[]
            for a in db.execute("SELECT * FROM actions WHERE tenant_id=? AND customer_id=? AND decision_at<=? ORDER BY decision_at,id",(tenant,customer,deadline)):
                features=json.loads(a["features_json"])
                if a["policy_version"]!=POLICY_VERSION or set(features)!=SEQUENCE_FEATURES or features["available_at"]>a["decision_at"]:
                    raise ValueError("Unknown policy version or unsafe feature contract")
                actions.append({"eligible":json.loads(a["eligible_json"]),"selected":a["selected"],
                    "propensity":a["propensity"],"logging_policy":a["policy"],"prior_contacts":features["prior_contact_count"]})
            w=trajectory_weight(target_policy,actions)
            b=trajectory_weight("observe",actions)
            reward=sum(r["reward_minor"] for r in rows)
            groups[rows[0]["currency"]].append({"world":str(config.seed),"merchant":rows[0]["merchant_id"],
                "n":len(rows),"baseline":b*reward,"target":w*reward,"weight":w,"baseline_weight":b,"has_decisions":bool(actions)})
    finally:
        db.close()
    result={"status":"complete","method":"unclipped full customer-history importance sampling",
        "synthetic_only":True,"contract":CONTRACT,"baseline":"observe","target_policy":target_policy,
        "thresholds":{"min_decision_customer_ess":min_ess,"min_merchant_clusters":min_clusters},
        "config_sha256":manifest["config_sha256"],"currencies":{},
        "assumptions":["Known randomized conditional behavior propensities and unchanged target policy version.",
                       "No interference between customers; shared exogenous merchant/world conditions are held fixed.",
                       "Fixed initial-failure enrollment and administrative maturity, independent of policy choice.",
                       "Configured lifecycle events are exogenous; policy-induced churn and long-term LTV are outside this estimand.",
                       "No unresolved outcomes are dropped. Large weights are not clipped or normalized to hide variance."]}
    for currency,counts in sorted(maturity.items()):
        if counts["unresolved"] or counts["unobserved_provider"]:
            result["currencies"][currency]={"status":"blocked","reason":"Unresolved provider evidence","maturity":dict(counts)}
            continue
        units=groups[currency]
        target_support=support([u["weight"] for u in units],[u["has_decisions"] for u in units])
        base_support=support([u["baseline_weight"] for u in units],[u["has_decisions"] for u in units])
        clusters=len({u["merchant"] for u in units})
        enough=clusters>=min_clusters and all(d["effective_sample_size"]>=min_ess and
            (d["decision_customers"]==0 or d["decision_customer_ess"]>=min_ess) for d in (target_support,base_support))
        if not enough:
            summary={"status":"insufficient_support","n":sum(u["n"] for u in units),
                "delta_minor_per_failed_invoice":None,"ci95":None}
        else:
            summary=contrast_summary(units,bootstrap=bootstrap)
        summary.update(target_support=target_support,baseline_support=base_support,maturity=dict(counts))
        result["currencies"][currency]=summary
    if not any(r["status"] in {"conditional_simulation_estimate","limited_clusters"} for r in result["currencies"].values()):
        result["status"]="blocked"
        result["reason"]="No currency has adequate complete trajectory support"
    return result
