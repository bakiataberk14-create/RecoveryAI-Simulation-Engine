"""A deliberately small structural causal model, NOT learned payment behavior.

One decision per failed invoice in v0.1. All potential actions share exogenous
payment, delivery, refund and retention noise. Only the selected arm is observed.
"""
from dataclasses import dataclass
from .config import SCENARIOS


@dataclass(frozen=True)
class Potential:
    recovery_day: int | None
    retained: bool
    refund_day: int | None
    delivered: bool
    opened: bool
    clicked: bool
    processing_cost: int
    communication_cost: int
    net: int


def potential(noise, key, action, reliability, willingness, engagement, amount, config):
    _, effect_shift, churn_shift = SCENARIOS[config.scenario]
    p = config.parameters
    contact = action in {"email", "request_update", "request_authentication"}
    delivered = contact and noise.uniform(key, "delivery") < config.delivery_probability
    opened = delivered and noise.uniform(key, "open") < (p.open_base + engagement * p.open_engagement_weight)
    clicked = opened and noise.uniform(key, "click") < willingness
    base = p.natural_recovery_base + p.natural_recovery_reliability_weight * reliability
    effect = {"observe": 0.0, "review": 0.0, "retry_day3": p.retry_effect,
              "email": p.email_effect, "request_update": p.update_effect, "request_authentication": p.authentication_effect}[action]
    if action not in {"observe", "review"}:
        effect = (effect + effect_shift) * (willingness if contact else 1)
    if contact and not delivered:
        effect = 0.0
    probability = max(0.0, min(1.0, base + effect))
    success = noise.uniform(key, "payment") < probability
    # Time is shared across alternatives; retries cannot execute before day three.
    day = (3 if action == "retry_day3" else 1) + int(noise.uniform(key, "payment_time") * p.payment_spread_days)
    day = day if success else None
    refund_day = day + p.refund_delay_days if success and noise.uniform(key, "refund") < config.refund_probability else None
    retained = noise.uniform(key, "retention") < max(0, min(1,
        p.retention_base + p.retention_engagement_weight * engagement - churn_shift - (p.saturation_retention_penalty if config.scenario == "saturation" and contact else 0)))
    communication_cost = p.communication_cost_minor if contact else 0
    # Hypothetical fixed minor-unit costs, NOT Stripe prices, no FX conversion.
    processing_cost = p.processing_cost_minor if action == "retry_day3" or success else 0
    net = (amount if success else 0) - (amount if refund_day is not None and refund_day <= 30 else 0)
    net -= processing_cost + communication_cost
    return Potential(day, retained, refund_day, delivered, opened, clicked,
                     processing_cost, communication_cost, net)
