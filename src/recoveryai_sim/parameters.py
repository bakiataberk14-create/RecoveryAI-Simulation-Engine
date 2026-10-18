"""Version 1: every numeric value below is a SYNTHETIC_ASSUMPTION.

No values are fitted to a merchant dataset or claimed as provider prices.
Definitions and experimental ranges: docs/assumptions.md.
"""
from dataclasses import dataclass, fields
import math


@dataclass(frozen=True)
class Parameters:
    merchant_size_shape: float = 1.4
    merchant_size_cap: float = 200.0
    merchant_effect_sd: float = .05
    acquisition_days: float = 60.0
    reliability_mean: float = .75
    reliability_sd: float = .16
    consent_probability: float = .85
    amount_base_minor: int = 5000
    enterprise_amount_minor: int = 150000
    consumer_amount_minor: int = 1500
    amount_log_sd: float = .7
    failure_reliability_weight: float = .35
    weekly_shock_sd: float = .04
    outage_failure_shift: float = .7
    expired_wave_probability: float = .7
    natural_recovery_base: float = .05
    natural_recovery_reliability_weight: float = .35
    retry_effect: float = .13
    email_effect: float = .08
    update_effect: float = .20
    authentication_effect: float = .14
    open_base: float = .2
    open_engagement_weight: float = .6
    retention_base: float = .55
    retention_engagement_weight: float = .35
    saturation_retention_penalty: float = .15
    payment_spread_days: int = 24
    refund_delay_days: int = 7
    webhook_max_delay_days: float = 5.0
    communication_cost_minor: int = 2
    processing_cost_minor: int = 5

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid synthetic parameter: {field.name}")
            if field.type is int and type(value) is not int:
                raise ValueError(f"Expected integer parameter: {field.name}")
        if not self.merchant_size_shape > 0 or self.merchant_size_cap < 1:
            raise ValueError("Invalid merchant-size distribution")
        if self.payment_spread_days > 27 or self.payment_spread_days < 1:
            raise ValueError("v1 payment resolution must fit within the 30-day horizon")
        if not 0 <= self.consent_probability <= 1 or not 0 <= self.expired_wave_probability <= 1:
            raise ValueError("Invalid probability")
