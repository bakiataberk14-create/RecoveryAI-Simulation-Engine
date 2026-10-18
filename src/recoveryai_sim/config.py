"""Validated, versioned assumptions, not empirical estimates."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
from .parameters import Parameters


# Values are deliberately hypothetical. Separate parameters permit sensitivity tests.
SCENARIOS = {
    "baseline": (0.0, 0.0, 0.0),
    "funds_shock": (0.16, 0.0, 0.02),
    "expired_wave": (0.08, 0.0, 0.01),
    "issuer_outage": (0.0, 0.0, 0.0),
    "high_churn": (0.03, 0.0, 0.20),
    "enterprise": (-0.02, 0.04, -0.02),
    "consumer": (0.05, -0.02, 0.08),
    "economic_stress": (0.20, -0.05, 0.12),
    "saturation": (0.04, -0.20, 0.06),
    "unseen_market": (0.12, -0.08, 0.10),
}
POLICIES = ("randomized", "observe", "fixed_retry", "rule_based")


@dataclass(frozen=True)
class Config:
    invoices: int = 100_000
    merchants: int = 100
    months: int = 24
    seed: int = 42
    scenario: str = "baseline"
    policy: str = "randomized"
    failure_base: float = 0.10
    refund_probability: float = 0.025
    delivery_probability: float = 0.95
    duplicate_probability: float = 0.10
    max_retries: int = 1
    max_steps: int = 4
    step_interval_days: int = 3
    recovery_window_days: int = 30
    start: str = "2024-01-01T00:00:00+00:00"
    schema_version: str = "1"
    parameters: Parameters = field(default_factory=Parameters)

    def __post_init__(self):
        if isinstance(self.parameters, dict):
            object.__setattr__(self, "parameters", Parameters(**self.parameters))
        if not isinstance(self.parameters, Parameters):
            raise ValueError("parameters must follow the versioned Parameters schema")
        for name in ("invoices", "merchants", "months", "seed", "max_retries", "max_steps", "step_interval_days", "recovery_window_days"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if not 0 < self.merchants <= self.invoices or not 1 <= self.months <= 120:
            raise ValueError("Require 0 < merchants <= invoices and 1 <= months <= 120")
        if self.seed < 0 or not 0 <= self.max_retries <= (3 if self.schema_version == "2" else 1):
            raise ValueError("Retry bound exceeded or seed < 0")
        if not 1 <= self.max_steps <= 10 or not 1 <= self.step_interval_days <= 14 or not 1 <= self.recovery_window_days <= 30:
            raise ValueError("Invalid sequential horizon/step bounds")
        if self.scenario not in SCENARIOS or self.policy not in POLICIES:
            raise ValueError("Unknown scenario or policy")
        for name in ("failure_base", "refund_probability", "delivery_probability", "duplicate_probability"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Invalid probability: {name}")
        from datetime import datetime
        if datetime.fromisoformat(self.start).utcoffset() is None:
            raise ValueError("start requires a timezone")
        if self.schema_version not in ("1", "2"):
            raise ValueError("Unsupported schema version")

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    @classmethod
    def load(cls, path: Path):
        return cls(**json.loads(path.read_text(encoding="utf-8")))
