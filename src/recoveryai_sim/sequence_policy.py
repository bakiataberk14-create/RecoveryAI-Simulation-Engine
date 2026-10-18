"""Versioned target policy shared by execution and trajectory evaluation."""
from .safety import select_action

POLICY_VERSION = "sequential-1"


def choose(policy, eligible, prior_contacts, uniform=0):
    if (policy == "rule_based" and "email" in eligible and prior_contacts == 0
            and "request_update" not in eligible and "request_authentication" not in eligible):
        return "email", 1.0
    return select_action(policy, eligible, uniform)
