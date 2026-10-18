# Full recovery-policy evaluation — engine0.3

Two different estimators answer two explicitly different data questions.

## 1. Complete policy reruns inside the simulator

```bash
python -m recoveryai_sim compare-policies --config configs/sequential.json --invoices 2000 --merchants 20 --seeds 42 43 --scenarios baseline saturation --output outputs/comparison
```

For every selected scenario/seed, the command runs observe, fixed_retry and
rule_based from the beginning. It hashes seeded merchants, customers, planned
subscriptions/payment methods, hidden world state and renewal calendars before
any decisions. Every policy must have the same initial-world digest and exact
failed-invoice enrollment. Mismatches stop the experiment; there is no inner join
that silently discards different cases. Every child run passes artifact validation.

Window payment noise is keyed by invoice and calendar window, not the number of
previously executed windows. Callback delay/duplication noise uses semantic event
identity instead of an event ordinal changed by communication actions. Policies
therefore share explicit exogenous conditions while evolving their own complete
observed histories, methods, follow-up timings and execution outcomes.

Results stay separate by scenario and currency. They include sample/merchant/world
counts; baseline/target net value per failed invoice; paired incremental value;
recovery-rate difference; costs; restricted unpaid days; and negative-value flags.
Incremental cost per incremental recovered invoice is null unless the incremental
recovery count is positive. Refunds affect financial value independently of gross
payment success. No unconditional synthetic-population superiority is claimed.

Confidence intervals resample whole merchants **within each fixed seed/world**.
All invoices/customers of a sampled merchant stay together. One-merchant strata
have no interval; fewer than5 merchants are flagged. Intervals are conditional
on the generated worlds, not on real merchants or a general distribution of
future economic shocks. Multiple seeds/scenarios give separate sensitivity
evidence; the command never tunes parameters or selects a deployable winner.
Intervals are pointwise nominal95% intervals, without adjustment for the number
of policies/scenarios/currencies. Negative-interval flags are diagnostics, not
authority to stop or deploy a real merchant policy.

## 2. Logged-data full customer-history importance sampling

Generate randomized schema2 logs, then:

```bash
python -m recoveryai_sim trajectory-evaluate --input outputs/randomized --target-policy rule_based
```

The shared versioned policy function computes the target choice from the logged
safe action set and observed prior contact count. For a customer history,
`w = product(target_probability / logged_behavior_probability)`.
Targets in this release are deterministic, so any mismatched decision gives zero
weight; a fully matched history multiplies inverse logged probabilities. Native
decisionless customers have weight1.

Weights cover the customer's **entire action history through the latest enrolled
financial deadline**, including earlier invoices and overlapping invoices that
are administratively censored. Multiplying only within each invoice would omit
effects carried through a customer's method and history. The customer's enrolled
invoice returns are summed once, then weighted once. The final denominator is
the fixed number of enrolled mature failed invoices, not number of actions.

This estimator requires known full-support randomized logging, unchanged policy
semantics, no interference between customers, a fixed initial-failure mechanism
and complete outcomes. The current simulator holds shared merchant/world shocks
fixed; it does not model policies changing future invoice creation/churn.

The report gives trajectory matches, mean/max weights, customer ESS, and ESS among
customers who actually had decisions. Decisionless customers cannot hide absent
intervention support. Default thresholds require ESS>=30 and>=5 merchant clusters
for both target and observe. Insufficient support produces null value/interval
fields and a blocked command when no currency qualifies. Unknown outcomes are
not dropped. There is no clipping, self-normalization or fabricated propensity
to make a sparse dataset look reliable. Numeric overflow fails explicitly.

This is trajectory IS, not doubly robust estimation. The sequential framework and
variance caveat are supported by [Jiang and Li, ICML2016](https://proceedings.mlr.press/v48/jiang16.html).
Simulator-specific customer independence, cohort and threshold assumptions are
documented here; the paper does not validate these assumptions for real merchants.

## Common fixed cohort and return contract

`evaluation/causal_episodes.jsonl` uses contract `failure-anchored-30d-v1`:

- Enrollment: every invoice whose initial attempt failed, including invoices
  recovered naturally before an actionable notification or with no decisions.
- Anchor: actual initial failed-attempt timestamp. Financial deadline is exactly
  30 days later, independent of when the first decision occurred.
- Administrative maturity: the financial deadline plus the configured maximum
  callback delay must precede the world end, for successes and failures equally.
- Reward: confirmed gross payment in the window minus full refunds occurring in
  the window, post-failure processing and communication costs. Initial failed
  attempt cost is a common sunk cost and excluded. Monetary values are integers
  in the invoice currency. Payments/refunds after the deadline are excluded.
- Pending/unknown attempts or missing provider observations produce unresolved
  returns. A comparison with any unresolved mature case blocks that currency;
  it does not keep only favorable/complete cases.
- One row and one financial return per tenant/invoice. The export contains no
  unchosen outcomes or latent variables; the projection does not read oracle
  tables. Old decision-anchored `training/episodes.jsonl` remains for compatibility
  and is not the causal evaluation denominator.

The report's `complete` status means the requested experiment finished, not that
every currency has enough data or that treatment outperformed observe. Inspect
the currency status, maturity, sign, interval and support counts.

## Limits

Initial invoice cohorts are intentionally fixed across policy worlds. Automatic
churn, changing future revenue/invoice schedules, partial refunds/chargebacks,
real-data calibration and real provider experiments remain separate modules.
The existing one-step evaluate/oracle-evaluate commands continue to reject
schema2. Only this complete-rollout comparison or the properly supported logged
trajectory estimator should be used for multi-step policy value.
