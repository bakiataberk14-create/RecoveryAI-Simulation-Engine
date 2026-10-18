"""Allowlisted offline research contract, NOT a production ingestion endpoint.

Pseudonymous references are still sensitive. No raw payload, identity, message
content or credentials belong here. Unknown/missing values stay unknown.
"""
from datetime import datetime, timedelta, timezone
import re

CONTRACT = "first-decision-learning-1"
OBJECTIVE = "observed-net-recovery-cash-30d-1"
SOURCES = {"provider", "product", "subscription", "support", "communications", "finance"}
CURRENCIES = {"TRY", "USD", "EUR", "GBP", "CAD", "AUD"}
ENUMS = {
    "decline_reason": {"insufficient_funds", "expired_card", "authentication_required", "generic_decline",
                       "lost_card", "issuer_not_available", "processing_error", "unknown"},
    "gross_margin_bucket": {"negative", "low", "medium", "high", "unknown"},
    "support_risk": {"low", "medium", "high", "unknown"},
}
FEATURE_SOURCES = {
    "subscription_age_days": "subscription", "previous_failure_count": "provider",
    "customer_active_days_7d": "product", "customer_active_days_30d": "product",
    "usage_intensity_bucket": "product", "team_size": "product", "feature_count_30d": "product",
    "estimated_ltv_minor": "finance", "gross_margin_bucket": "finance", "cost_to_serve_minor_30d": "finance",
    "support_ticket_count_30d": "support", "support_risk": "support",
    "messages_delivered_30d": "communications", "messages_clicked_30d": "communications",
    "consent": "communications",
}
FEATURE_ENUMS = {**ENUMS, "usage_intensity_bucket": {"none", "low", "medium", "high", "unknown"}}
ACTIONS = {"observe", "review", "email", "hosted_payment_link", "request_update", "request_authentication", "retry_day3"}
TOP = {"contract", "tenant_ref", "customer_ref", "recovery_ref", "decision_ref", "environment", "provider",
       "first_failure_at", "decision_at", "amount_minor", "currency", "decline_reason", "attempt_count",
       "policy_version", "model_version", "selected_action", "eligible_actions", "propensity", "features",
       "execution", "outcome"}
EXECUTION = {"status", "executed_at", "execution_ref", "delivery_status", "message_ref"}
OUTCOME = {"status", "window_end", "available_at", "provider_event_ref", "paid_at", "gross_recovered_minor",
           "refund_minor", "processing_cost_minor", "communication_cost_minor", "service_fee_minor"}


class ContractError(ValueError):
    """Error codes intentionally never interpolate source values or raw exceptions."""


def require(condition, code):
    if not condition:
        raise ContractError(code)


def fields(value, expected, code):
    require(type(value) is dict and set(value) == set(expected), code)


def timestamp(value):
    require(type(value) is str and len(value) <= 40, "invalid_timestamp")
    try:
        result = datetime.fromisoformat(value)
        require(result.utcoffset() is not None, "timezone_required")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ContractError("invalid_timestamp") from None


def reference(value, prefix):
    require(type(value) is str and re.fullmatch(prefix + r"_[0-9a-f]{64}", value) is not None,
            "pseudonymous_reference_required")


def integer(value, minimum=0, maximum=10**15):
    require(type(value) is int and minimum <= value <= maximum, "invalid_integer")


def version(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is not None,
            "invalid_version_code")


def validate_permission(record, now):
    fields(record, {"contract", "permission_granted", "purpose", "tenant_refs", "environment", "data_origin",
                    "source_version", "exported_at", "expires_at", "retention_until"}, "permission_fields")
    require(record["contract"] == CONTRACT and record["permission_granted"] is True
            and record["purpose"] == "offline_decision_research", "permission_required")
    require(type(record["tenant_refs"]) is list and 0 < len(record["tenant_refs"]) <= 10000, "tenant_scope_required")
    for tenant in record["tenant_refs"]:
        reference(tenant, "t")
    require(len(set(record["tenant_refs"])) == len(record["tenant_refs"]), "duplicate_tenant_scope")
    require(record["environment"] in {"live", "sandbox", "synthetic"}, "invalid_environment")
    expected = "synthetic" if record["environment"] == "synthetic" else "merchant_export"
    require(record["data_origin"] == expected, "environment_origin_mismatch")
    version(record["source_version"])
    exported, expires, retention = (timestamp(record[k]) for k in ("exported_at", "expires_at", "retention_until"))
    require(exported <= now < expires and exported <= now < retention, "permission_expired_or_future")
    return record


def validate_episode(record, permission):
    fields(record, TOP, "episode_fields")
    require(record["contract"] == CONTRACT, "contract_version")
    for field, prefix in (("tenant_ref", "t"), ("customer_ref", "c"), ("recovery_ref", "r"), ("decision_ref", "d")):
        reference(record[field], prefix)
    require(record["tenant_ref"] in permission["tenant_refs"], "tenant_not_permitted")
    require(record["environment"] == permission["environment"], "mixed_environment")
    require(record["provider"] in {"stripe", "iyzico", "paytr"}, "unknown_provider")
    failure, decision = timestamp(record["first_failure_at"]), timestamp(record["decision_at"])
    require(failure <= decision <= failure + timedelta(days=30), "decision_outside_episode")
    require(decision <= timestamp(permission["exported_at"]), "decision_after_export")
    integer(record["amount_minor"], 1)
    integer(record["attempt_count"], 1, 1000)
    require(record["currency"] in CURRENCIES, "unsupported_currency")
    require(record["decline_reason"] in ENUMS["decline_reason"], "unknown_decline_code")
    version(record["policy_version"])
    if record["model_version"] is not None:
        version(record["model_version"])
    legal = record["eligible_actions"]
    require(type(legal) is list and legal and all(type(a) is str and a in ACTIONS for a in legal), "invalid_action_set")
    require(len(set(legal)) == len(legal) and record["selected_action"] in legal, "action_outside_support")
    p = record["propensity"]
    require(type(p) in (int, float) and 0 < p <= 1, "invalid_propensity")
    fields(record["features"], FEATURE_SOURCES, "feature_fields")
    values, missing = {}, []
    for name, source in FEATURE_SOURCES.items():
        feature = record["features"][name]
        if feature is None:
            values[name] = None
            missing.append(name)
            continue
        fields(feature, {"value", "occurred_at", "available_at", "source"}, "feature_provenance_fields")
        require(feature["source"] == source, "feature_source_mismatch")
        occurred, available = timestamp(feature["occurred_at"]), timestamp(feature["available_at"])
        require(occurred <= available <= decision, "future_feature_leakage")
        require(decision - occurred <= timedelta(days=30), "stale_feature")
        value = feature["value"]
        if name == "consent":
            require(type(value) is bool, "invalid_consent")
        elif name in FEATURE_ENUMS:
            require(type(value) is str and value in FEATURE_ENUMS[name], "invalid_feature_category")
        else:
            maximum = 7 if name == "customer_active_days_7d" else 30 if name == "customer_active_days_30d" else 10**15
            integer(value, maximum=maximum)
        values[name] = value
    if values["customer_active_days_7d"] is not None and values["customer_active_days_30d"] is not None:
        require(values["customer_active_days_7d"] <= values["customer_active_days_30d"], "activity_window_mismatch")
    if values["messages_clicked_30d"] is not None and values["messages_delivered_30d"] is not None:
        require(values["messages_clicked_30d"] <= values["messages_delivered_30d"], "communication_funnel_mismatch")
    fields(record["execution"], EXECUTION, "execution_fields")
    execution = record["execution"]
    require(execution["status"] in {"not_executed", "executed", "unknown"}, "invalid_execution_state")
    require(execution["delivery_status"] in {"not_applicable", "unknown", "delivered", "bounced"}, "invalid_delivery_state")
    if execution["executed_at"] is not None:
        executed = timestamp(execution["executed_at"])
        require(decision <= executed <= timestamp(permission["exported_at"]), "invalid_execution_time")
        reference(execution["execution_ref"], "x")
    else:
        require(execution["execution_ref"] is None, "execution_reference_without_time")
    if execution["status"] == "executed":
        require(execution["executed_at"] is not None, "execution_evidence_required")
    if execution["status"] == "not_executed":
        require(execution["executed_at"] is None and execution["delivery_status"] == "not_applicable"
                and execution["message_ref"] is None, "non_execution_has_delivery")
    if execution["message_ref"] is not None:
        reference(execution["message_ref"], "m")
    if execution["delivery_status"] in {"delivered", "bounced"}:
        require(execution["message_ref"] is not None and execution["status"] == "executed", "delivery_evidence_required")
    if record["selected_action"] in {"observe", "review"}:
        require(execution["status"] == "not_executed", "holdout_action_leakage")
    if execution["status"] == "executed" and record["selected_action"] in {"email", "hosted_payment_link", "request_update", "request_authentication"}:
        require(values["consent"] is True, "executed_contact_without_consent")
    # No native retry authority can be inferred for Turkish providers.
    require(record["provider"] == "stripe" or "retry_day3" not in legal, "unsupported_provider_retry")
    fields(record["outcome"], OUTCOME, "outcome_fields")
    outcome = record["outcome"]
    require(outcome["status"] in {"provider_confirmed_paid", "provider_confirmed_unpaid", "unresolved"}, "invalid_outcome_state")
    end, available = timestamp(outcome["window_end"]), timestamp(outcome["available_at"])
    require(end == failure + timedelta(days=30), "outcome_window_mismatch")
    if execution["executed_at"] is not None:
        require(timestamp(execution["executed_at"]) <= end, "execution_outside_window")
    require(failure <= available <= timestamp(permission["exported_at"]), "outcome_availability_mismatch")
    for name in ("processing_cost_minor", "communication_cost_minor", "service_fee_minor"):
        integer(outcome[name])
    reward = None
    if outcome["status"] == "unresolved":
        require(all(outcome[k] is None for k in ("provider_event_ref", "paid_at", "gross_recovered_minor", "refund_minor")),
                "unresolved_has_fabricated_label")
    else:
        require(end <= available, "immature_outcome_label")
        reference(outcome["provider_event_ref"], "p")
        integer(outcome["gross_recovered_minor"], maximum=record["amount_minor"])
        integer(outcome["refund_minor"], maximum=outcome["gross_recovered_minor"])
        if outcome["status"] == "provider_confirmed_paid":
            require(outcome["gross_recovered_minor"] > 0 and outcome["paid_at"] is not None, "payment_evidence_required")
            require(failure <= timestamp(outcome["paid_at"]) <= end, "payment_outside_window")
        else:
            require(outcome["gross_recovered_minor"] == outcome["refund_minor"] == 0 and outcome["paid_at"] is None,
                    "unpaid_has_payment")
        reward = outcome["gross_recovered_minor"] - outcome["refund_minor"] - sum(
            outcome[k] for k in ("processing_cost_minor", "communication_cost_minor", "service_fee_minor"))
    return {"x": {"amount_minor": record["amount_minor"], "currency": record["currency"],
                  "decline_reason": record["decline_reason"], "attempt_count": record["attempt_count"], **values},
            "missing_features": missing, "observed_net_cash_30d_minor": reward,
            "causal_effect": None, "billable": False}
