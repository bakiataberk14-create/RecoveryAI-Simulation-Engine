"""Currency-local summaries with bootstrap stratified by fixed synthetic seed.

Each sample unit carries a merchant cluster and an invoice denominator. Bootstrap
resamples whole merchants within each world. Intervals are conditional on those
worlds, not a real-world bank/customer population guarantee.
"""
from collections import defaultdict
import random


def contrast_summary(units,seed=42,bootstrap=200):
    if type(bootstrap) is not int or bootstrap<20:
        raise ValueError("At least20 bootstrap replicates required")
    strata=defaultdict(lambda:defaultdict(list))
    for unit in units:
        if unit["n"]<=0:
            raise ValueError("Positive invoice denominator required")
        strata[unit["world"]][unit["merchant"]].append(unit)
    if not units:
        return {"status":"no_mature_cohort","n":0,"delta_minor_per_failed_invoice":None,"ci95":None}
    n=sum(u["n"] for u in units)
    totals={key:sum(u[key] for u in units) for key in ("baseline","target")}
    delta=(totals["target"]-totals["baseline"])/n
    enough=all(len(clusters)>=2 for clusters in strata.values())
    draws=[]
    rng=random.Random(seed)
    if enough:
        # Aggregate once to avoid repeating large customer/invoice lists.
        grouped={world:{merchant:(sum(u["target"]-u["baseline"] for u in group),sum(u["n"] for u in group))
                        for merchant,group in clusters.items()} for world,clusters in strata.items()}
        for _ in range(bootstrap):
            num,den=0,0
            for world in sorted(grouped):
                keys=sorted(grouped[world])
                for _ in keys:
                    d,k=grouped[world][rng.choice(keys)]
                    num+=d
                    den+=k
            draws.append(num/den)
        draws.sort()
    clusters=sum(len(c) for c in strata.values())
    return {"status":"limited_clusters" if any(len(c)<5 for c in strata.values()) else "conditional_simulation_estimate",
        "n":n,"worlds":len(strata),"merchant_clusters":clusters,
        "baseline_minor_per_failed_invoice":totals["baseline"]/n,"target_minor_per_failed_invoice":totals["target"]/n,
        "delta_minor_per_failed_invoice":delta,
        "ci95":[draws[int(.025*len(draws))],draws[min(len(draws)-1,int(.975*len(draws)))]] if draws else None,
        "negative_point_estimate":delta<0,"ci_entirely_negative":bool(draws and draws[min(len(draws)-1,int(.975*len(draws)))]<0),
        "inference_scope":"conditional on fixed generated worlds; merchant bootstrap within seed"}
