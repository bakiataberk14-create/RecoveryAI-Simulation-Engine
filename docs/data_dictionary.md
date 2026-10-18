# Schema 1: data dictionary and metric contracts

Executable column definitions (types, nullability, uniqueness, FK and CHECK
constraints) are in `recoveryai_sim.storage.SCHEMA`. Monetary types are integer
minor units; all supported currencies have two decimals. Timestamps are ISO8601
UTC strings. Booleans in SQLite/Parquet are integer 0/1. Every table has a unique
`id` TEXT and a `tenant_id` TEXT. IDs use `syn_` prefixes. Empty exports retain
their SQL-derived Parquet schema.

| Table | Other fields and meaning |
|---|---|
| merchants | country ISO2; currency ISO3; industry fictional category; provider `stripe` (simulation only). tenant_id is unique. |
| customers | merchant_id FK; signup_at timestamp; consent communication permission; engagement observable synthetic [0,1]. |
| subscriptions | customer_id FK; interval_months 1/3/12; amount_minor; currency; start_at; status (`active` in current closed-cohort slice). |
| payment_methods | customer_id FK; method_type `card`; issuing_country; status. Contains no PAN, CVV, name, email or issuer identifier. |
| invoices | subscription_id FK; currency; amount_due original obligation; amount_paid collected before refunds; amount_remaining outstanding; refund_amount cumulative returned amount; created_at; paid_at nullable; status open/paid/refunded. |
| attempts | invoice_id/method_id FKs; occurred_at initiation timestamp; number positive invoice-local ordinal; result failed/pending/succeeded; decline nullable raw synthetic code; action_id nullable (initial attempt has no recovery action); processing_cost minor units. |
| actions | invoice_id unique FK (one decision per invoice in v1); customer_id FK; decision_at; features_json immutable-at-export snapshot; eligible_json safe action list; selected; propensity exact behavior probability; policy; policy_version; rule_version; execution_at nullable if horizon censored; status scheduled/executed/observed/review_only. |
| communications | action_id unique FK; sent_at; delivered/opened/clicked booleans with monotone funnel; cost_minor. Email channel only; no customer message content. |
| outcomes | invoice_id/action_id unique FKs; currency; recovered_at nullable; gross_recovered; processing_cost post-decision only; communication_cost; refund_amount within 30d only; net_revenue 30d reward; recovered_7d/14d/30d nullable censored booleans; retention_90d nullable endpoint proxy; window_complete 30d; observed_until timestamp. |
| events | invoice_id FK; occurred_at business timestamp; event_type internal `sim.*`; provider_reference_type nullable semantic reference, **not a provider payload**; namespace=simulation; synthetic=1. |
| deliveries | event_id FK; delivered_at >= event time; multiple rows can reference one event (replay). Events beyond the observation horizon are not delivered. |
| oracle | action_id FK; action legal alternative; recovery_day nullable integer offset; retained_90d hidden endpoint; refund_day nullable offset; reward_minor complete 30d potential reward; latent_reliability hidden probability. Unique(action_id,action). Never a training source. |
| oracle_world | id references synthetic customer identity logically; merchant_effect, reliability, willingness hidden state. Never a training source. |

FK tenant equality is checked across every relation by the validator. SQLite FKs
alone check identity, not composite tenant identity; this offline artifact is not
a multi-tenant serving API or production database. The replay consumer rejects
cross-tenant events.

## Decision feature availability

All features in an action are available at the synchronous failed-attempt result:
amount_minor, currency, decline_reason, decline_category, attempt_count (1),
subscription_age_days, past_successes, past_failures (excluding current failure),
engagement, consent, available_at. Availability must not exceed decision_at.
Customer IDs and merchant IDs remain split metadata, never model features.

`training/decisions.jsonl` separates `x`, `y`, `metadata`, `policy`, and
`reward_30d_minor`. Only `x` is accepted by baseline predictors. `y` has nullable
7/14/30-day recovery labels and 90-day retention. Incomplete windows are null,
not failure. Policies see only observed features; counterfactuals are oracle-only.

## Accounting and estimands

- Obligation: amount_due = amount_paid + amount_remaining. Refund is a separate
  reversal, not a new unpaid obligation. Net cash = amount_paid - refund_amount.
- Recovery denominator: initially failed invoices, not attempts or merchants.
- Net 30d recovery = gross recovered - post-decision processing - communication
  cost - refunds occurring within day30. Initial attempt cost is excluded equally
  across actions. No taxes, FX or platform success fee is simulated.
- Potential incremental value = oracle action reward minus oracle observe reward
  for the **same failed-invoice context**. Not all recovered cash is incremental.
- OPE reports IPS value per failed invoice by currency and effective sample size,
  with merchant-cluster bootstrap intervals. Insufficient support is flagged.
- ML target is observed recovery under the logging policy, not individual causal
  uplift. Training merchants and future test merchants are disjoint; training
  observation windows must end before the split cutoff.
