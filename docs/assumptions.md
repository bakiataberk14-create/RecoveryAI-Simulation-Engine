# Assumption register v1

All numerical behavior in this release is **SYNTHETIC_ASSUMPTION**, except scenario
shifts, which are **EXPERIMENTAL_HYPOTHESIS**. No estimated bank behavior or provider
price is represented. Parameter defaults are machine-readable in `Config` and
`Parameters`; every run embeds the complete effective parameter set and hash.
Override any Parameters field through a config's `parameters` object. The model
supports sensitivity sweeps; no automatic calibration is claimed.

## Generative mechanism

- Merchant acquisition weights follow a truncated Pareto: shape
  `merchant_size_shape=1.4`, cap `merchant_size_cap=200`. One initial cohort per
  merchant is reserved; subsequent customers follow those weights.
- Merchant failure offset is normal with `merchant_effect_sd=.05`.
- Customers arrive uniformly during the first `acquisition_days=60` (bounded to
  half the horizon). This is a closed cohort, not continuous market acquisition.
- Reliability is a normal draw (`reliability_mean=.75`, `reliability_sd=.16`)
  clipped to [.05,.98]. Engagement and willingness are uniform [0,1]. They are
  persistent customer attributes; reliability/willingness remain oracle-only.
- Consent is Bernoulli(`consent_probability=.85`). It does not change within a
  run. Countries and industries are uniformly assigned from the code enums.
- Monthly/quarterly/annual interval weights are 4:1:1. Calendar arithmetic clips
  renewal days to month-end. Cohorts are truncated to hit the requested invoice
  target exactly; this may shorten the final cohort's schedule.
- Amount = max(100, floor(base * exp(`amount_log_sd=.7` * normal noise))). Base is
  `amount_base_minor=5000`, `enterprise_amount_minor=150000`, or
  `consumer_amount_minor=1500`. All are currency-local minor units, NOT comparable
  purchasing power; no FX is assumed.
- Initial failure probability is clipped to [.01,.95]: `failure_base=.10` +
  scenario shift + merchant offset + (`reliability_mean` - reliability) *
  `failure_reliability_weight=.35` + shared weekly normal shock with
  `weekly_shock_sd=.04`. Issuer-outage world adds `outage_failure_shift=.7` on
  days 180..194 of each 365-day block. This is a fictional shared outage, not a
  real issuer or local-hour claim.
- Conditional decline mix weights are funds:2 and expiry/auth/generic/lost:1 each.
  Expiry-wave overrides with probability `expired_wave_probability=.7`.

## One-decision causal model

Natural recovery probability = `natural_recovery_base=.05` + reliability *
`natural_recovery_reliability_weight=.35`. Legal intervention additions:
`retry_effect=.13`, `email_effect=.08`, `update_effect=.20`,
`authentication_effect=.14`; observe/review have zero effect. Contact effects are
scaled by willingness and become zero on delivery failure. Scenario effect shifts
can make interventions harmful. Probabilities are clipped [0,1]. Shared uniform
noise determines all potential outcomes for the same invoice.

Delivery probability is `.95`; opening is `.2 + .6*engagement` (`open_base`,
`open_engagement_weight`); clicking requires opening and willingness. These are
immediate synthetic engagement signals, not real provider tracking fidelity.

Resolution day is 1 + uniform integer in [0, `payment_spread_days=24`), or 3 +
that integer for retry. There is one day-3 recovery retry at most. Its status can
remain pending until settlement; this is not an exact synchronous Stripe charge.
The common payment/refund/retention noise is keyed independently of policy choice.

Full refund probability `.025`, delay `refund_delay_days=7`. 90-day retention is
a per-invoice endpoint proxy: `.55 + .35*engagement - scenario churn shift`, and
saturation contact subtracts `.15` (`retention_base`,
`retention_engagement_weight`, `saturation_retention_penalty`). It does **not**
cancel subscriptions or affect later invoices. No claim of longitudinal churn
simulation is made in v0.1.

Communication cost `communication_cost_minor=2`, processing cost
`processing_cost_minor=5` are invented fixed costs in the invoice currency.
Baseline also incurs the customer-initiated payment cost if it succeeds.
Net outcome excludes initial failed-attempt cost (a pre-decision sunk cost).
Refunds after day30 stay in the ledger but are excluded from the 30-day reward.

Webhook delay is uniform [0,`webhook_max_delay_days=5`], duplicate probability
`.10`. Invoices and decisions see synchronous attempt results; webhook delays
stress the separate replay consumer, not the policy's information arrival time.

## Sensitivity and uncertainty

Recommended experiments: halve/double effect and cost coefficients, vary failure
base .05..30, delivery .70..99, reliability spread .05..25. These are experimental
ranges, not confidence intervals. Preserve seeds and compare currency-separated
results. Do not tune on `unseen_market`. No parameter is calibrated merely because
a run produces an attractive recovery rate.

Limits: no discounts, partial collections, chargebacks, SMS, dynamic consent,
sequential bandits, drift fitting or real merchant imports in this slice.
