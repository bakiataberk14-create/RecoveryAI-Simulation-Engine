"""Conservative simulator rules. Not a provider authorization engine."""
from dataclasses import dataclass

RULE_VERSION = "stripe-card-subset-2026-10-18"
HARD = frozenset({"incorrect_number", "lost_card", "pickup_card", "stolen_card",
    "revocation_of_authorization", "revocation_of_all_authorizations",
    "authentication_required", "highest_risk_level", "transaction_not_allowed"})
SOFT = frozenset({"insufficient_funds", "issuer_not_available", "processing_error"})
CATEGORY = {"insufficient_funds": "insufficient_funds", "expired_card": "expired_method",
    "lost_card": "lost_stolen", "authentication_required": "authentication_required",
    "issuer_not_available": "issuer_unavailable", "generic_decline": "unknown"}


@dataclass(frozen=True)
class Context:
    provider: str = "stripe"
    decline: str = "insufficient_funds"
    consent: bool = True
    method_active: bool = True
    issuing_country: str = "US"
    connected: bool = True
    retries: int = 0
    max_retries: int = 1
    advice: str | None = None


def eligible_actions(ctx: Context) -> tuple[str, ...]:
    actions = ["observe", "review"]
    # Unknown providers/advice are fail-closed for payment mutation.
    if ctx.provider != "stripe" or ctx.advice is not None or not ctx.connected:
        return tuple(actions)
    if ctx.consent:
        actions.append("email")
        if ctx.decline == "authentication_required":
            actions.append("request_authentication")
        elif ctx.decline in HARD or ctx.decline == "expired_card" or not ctx.method_active:
            actions.append("request_update")
    if (ctx.decline in SOFT and ctx.method_active and ctx.issuing_country != "IN"
            and ctx.retries < ctx.max_retries):
        actions.append("retry_day3")
    return tuple(actions)


def select_action(policy, eligible, uniform):
    if policy == "randomized":
        return eligible[min(int(uniform * len(eligible)), len(eligible) - 1)], 1 / len(eligible)
    if policy == "observe":
        return "observe", 1.0
    if policy == "fixed_retry":
        return ("retry_day3" if "retry_day3" in eligible else "observe"), 1.0
    if policy == "rule_based":
        for action in ("request_update", "request_authentication", "retry_day3", "email", "observe"):
            if action in eligible:
                return action, 1.0
    raise ValueError("Unknown policy")
