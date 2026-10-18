"""Permissioned aggregate contract. No raw identities, events or PII ingestion."""
from datetime import datetime
import math
import re

FIELDS = {"permission_granted", "tenant_ref", "population", "period_start", "period_end",
          "initial_attempts", "initial_failures", "metric_definition", "source_version"}


def assess_aggregate(record):
    if set(record) != FIELDS or record["permission_granted"] is not True:
        raise ValueError("Explicit permission and exact aggregate contract required")
    if record["metric_definition"] != "failed_initial_attempts/initial_attempts":
        raise ValueError("Incompatible denominator")
    if not isinstance(record["tenant_ref"], str) or not re.fullmatch(r"agg_[A-Za-z0-9_-]{1,64}", record["tenant_ref"]):
        raise ValueError("Use a pseudonymous agg_ tenant reference")
    for key in ("population", "source_version"):
        if not isinstance(record[key], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", record[key]):
            raise ValueError("Use non-identifying population/source-version category codes")
    start, end = (datetime.fromisoformat(record[k]) for k in ("period_start", "period_end"))
    if start.utcoffset() is None or end.utcoffset() is None or start >= end:
        raise ValueError("Valid timezone-aware observation period required")
    n, k = record["initial_attempts"], record["initial_failures"]
    if type(n) is not int or type(k) is not int or n <= 0 or not 0 <= k <= n:
        raise ValueError("Invalid counts")
    p, z = k/n, 1.96
    center = (p+z*z/(2*n))/(1+z*z/n)
    half = z * math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return {"evidence_class": "EMPIRICAL_BENCHMARK", "rate": p, "n": n,
            "wilson_ci95": [center-half, center+half], "population": record["population"],
            "source_version": record["source_version"], "automatic_parameter_update": False,
            "warning": "Descriptive binomial interval; repeated-customer correlation may understate uncertainty. One aggregate cannot identify all latent parameters."}
