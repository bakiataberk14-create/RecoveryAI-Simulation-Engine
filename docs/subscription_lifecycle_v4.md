# Exogenous subscription lifecycle — v0.4

This is an offline synthetic subscription simulator, not Alroca production billing.
No cancellation, plan change or payment is sent to a real provider.

## Input contract

Schema2 `lifecycle_events` contains objects with `customer_index` (generated
customer ordinal), positive integer `day` since signup, and `kind`:

- `pause`: active subscription becomes paused.
- `resume`: paused/unpaid subscription becomes active; cancelled remains terminal.
- `cancel`: terminal cancellation, without refunding or voiding old invoices.
- `plan`: optional positive integer `amount_minor` and/or `interval_months` 1..12.
  Currency does not change. There is no implicit exchange rate or proration.

Unknown keys, invalid transitions, conflicting customer/day controls, missing
customers and events outside the horizon fail explicitly. A failed run does not
publish a complete manifest. Configuration is immutable and included in its hash.
Config ordinal is the stable idempotency key: replay of the same event is a no-op.

## Calendar semantics (explicit synthetic assumptions)

The next existing billing anchor is preserved after a plan change. Later unissued
dates are recalculated with the new interval using calendar-month clamping (not
30-day arithmetic). Paused renewal slots are skipped, not accumulated as debt.
Resume continues at the next calendar slot: no immediate charge or catch-up invoice.
Controls effective at a renewal timestamp run before that renewal, because all
configured controls are queued at seeding. Only one control per customer/day is allowed.

`invoices` remains the original **planned renewal-slot budget**. With no controls,
the historical exact invoice-count behavior is preserved. Pause/cancel or longer
intervals can reduce actual invoices; a shorter interval cannot exceed the original
number of slots per customer. Dates beyond the world horizon are right-censored,
not backfilled with invented customers. This is a bounded research population,
not a forecast of unrestricted subscription revenue.

## Evidence and invariants

- `subscription_events`: append-only before/after subscription state, effective
  timestamp, tenant and subscription. These are merchant controls, not provider
  webhook evidence. Future controls are never added to decision feature snapshots.
- `renewal_slots`: append-only calendar position, status, currency, price and
  interval snapshot, with an invoice reference only for issued slots.
- A unique subscription/cycle and unique invoice reference prevent repeated issuance.
- Obsolete queued dates are rescheduled without issuing stale invoices.
- Issued invoice tenant, subscription, currency, due amount and timestamp are immutable.
- Existing failed invoices keep their original amount during later plan changes.
- Dispatch still checks current subscription status, independently of delayed
  subscription notifications. Pausing/cancelling does not permit stale dispatch.
- Validation checks slot ownership, invoice/slot terms, coverage and slot budget,
  alongside existing accounting, tenant, evidence and causal-cohort checks.

The existing `on_control` invoice-scoped test helper remains compatible; configured
lifecycle scenarios use the new persistent subscription-level journal.

## Evaluation limits

Lifecycle controls are **exogenous**, identical across paired policy worlds, and
included in the initial-world fingerprint. They do not depend on payment outcomes
or recovery actions. Fixed failed-invoice cohort equality is still enforced.
Policy reports estimate 30-day failed-invoice recovery returns, **not subscription
LTV or policy-induced retention/churn**. Those require a different enrollment and
long-term estimand before adding endogenous cancellation behavior.

`retention_90d` is still a hypothetical Bernoulli label, not observed merchant
retention. Configured lifecycle state at the label's 90-day boundary forces it to
zero when inactive; later cancellation must not rewrite an earlier label.
Schema1 behavior is unchanged and rejects lifecycle configuration.

Schema2 adds tables in v0.4; regenerate old artifacts with the new engine to use
the current validator. This does not migrate or rewrite old datasets.
