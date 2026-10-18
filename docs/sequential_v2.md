# Schema 2 — delayed evidence and bounded recovery trajectories

Engine 0.2 supports schema1 and schema2. Existing schema1 artifacts are not
migrated or overwritten. Select schema2 explicitly:

```bash
python -m recoveryai_sim generate --config configs/sequential.json --output outputs/sequence --parquet
python -m recoveryai_sim validate --input outputs/sequence
python -m recoveryai_sim train --input outputs/sequence
```

## Time and knowledge

The world has physical events with `occurred_at`. Each delivery has
`delivered_at`; the first processed delivery produces an immutable observation
with `available_at`. These are separate from action `decision_at`, dispatch
`execution_at` and result `recorded_at`.

Physical payment failure schedules observation delivery and natural-recovery
windows; it never calls the policy immediately. Decisions require a received
failure observation. Duplicate deliveries produce one observation. A late
failure cannot reopen a paid/refunded/closed projection. Consent/subscription
notifications compare business timestamp and deterministic event ID, preventing
an older grant/pause from overriding a later revocation/reactivation.

History features query received observations, not the world's hidden customer
counters. `sources_json` records the exact observation IDs and their availability
times. References with `kind: execution` point to earlier immutable action-result
records. Static amount/currency/customer profile is known at signup/invoice
creation. No reference may belong to another tenant/customer or become available
after decision time. Same-time events use the queue's deterministic serial order.

Execution performs a physical provider-state preflight. Thus a policy can plan a
retry while a success callback is delayed, but dispatch still blocks if the
invoice is paid, subscription inactive, method replaced/revoked, consent revoked,
provider result pending/unknown, or recovery window closed. This preflight is
new information obtained at execution; it is not copied backward into a feature
snapshot. Reason and timestamp are recorded in `action_results`.

## States and idempotency

`state_machine.py` defines legal states and transitions. Schema2 installs SQLite
triggers so direct SQL cannot regress terminal invoice/attempt/action states,
reactivate a replaced method or resurrect a cancelled subscription. Scheduled
actions can execute, observe, request review, be cancelled, blocked or censored.
Dispatch status is terminal; payment and delivery outcomes are separate records.

An action is unique by `(invoice_id, step)`, each result/communication is unique
by action, and each observation is unique by event. Queue timers deduplicate an
invoice/timestamp; execution checks persisted action status before dispatch.
This is a deterministic single-process simulator, not a distributed worker lease
or production concurrency guarantee.

Synthetic `on_control` events can pause/cancel/reactivate a subscription, revoke
consent, or void/write off an open invoice. Cancellation/closed observations stop
future actions; preflight also protects the interval before those notifications
arrive. Future invoice generation requires an active subscription. Automatic
churn/cancellation dynamics are a separate future module.

## Multiple steps

Configuration bounds: `max_steps` 1..10 (default4), `max_retries` 0..3 for schema2,
`step_interval_days` 1..14 (default3), `recovery_window_days` 1..30 (default30).
The rule-based policy prefers an update/authentication request where appropriate;
otherwise it starts with email, then eligible retries/observation. Contacts of a
given type execute at most once per invoice. Review ends policy follow-up;
natural recovery can continue. Native observe policy never dispatches contact or
automated payment actions. Customer-initiated natural payments have no action ID.

Each step gets a fresh immutable snapshot, eligible actions, conditional behavior
propensity, previous-action link and evidence references. Retries are reevaluated
at execution. Unknown provider outcomes stay unresolved and cannot create another
payment. A fresh customer method is simulated for a hard/expired decline before
customer-initiated payment; a replaced method cannot be reused by a planned retry.

## Hypothetical window model

For a window of length `d`, the model transforms the existing hypothetical
30-day rate `q` to a window probability `1 - (1-q) ** (d/30)`.
`q` combines natural reliability and the current legal intervention effect,
clipped to [0,.99]. Contact effects require underlying delivery and are scaled
by willingness; saturation/economic scenario shifts can reduce value. A window
uses keyed exogenous noise shared across its legal alternatives.

An intervention affects its next settlement window only. Baseline windows keep
running until the configured horizon. No specific bank, actual provider retry
algorithm or empirical hazard is represented. Email opens/clicks have separate
internal events and can be observed late or out of order. The received funnel
is monotone even when click arrives before delivery.

`step_oracle` holds conditional **next-window** potential successes for legal
alternatives at an executed step. It is not a counterfactual full trajectory.
The existing one-step IPS and oracle evaluators return `status: blocked` on
schema2; the CLI exits nonzero. Sequential OPE is deliberately not approximated
by adding the same invoice reward to every decision.

## Schema additions and training

- `actions`: invoice FK is no longer unique; adds `step`, nullable
  `previous_action_id`, `source_observation_id`, `sources_json`, and unique
  `(invoice_id,step)`. Decision/ownership/evidence fields are immutable.
- `events`: adds a synthetic `payload_json` with attempt/action/method references
  and safe typed result metadata. These are internal sim events, not real PSP
  webhook payloads.
- `observations`: unique event FK, tenant/invoice FKs, business/availability
  timestamps, event type, applied flag, immutable payload. Late obsolete controls
  remain recorded with applied=0.
- `action_results`: unique action FK, dispatch result/reason, recorded timestamp,
  method FK and hypothetical processing/communication cost. Immutable.
- `outcomes`: one financial result per invoice, linked to its first action;
  adds `measurement_status` observed/unresolved.
- `step_oracle`: action FK, window end, legal alternative, probability and hidden
  potential-success boolean; unique(action,alternative). Oracle-only export.

Observed training adds step, prior contact/retry counts, known invoice/method
state, observed delivery count and observation lag. Decision targets are recovery
within 7/14/30 days from that decision **under subsequent logged behavior**.
They are censored until mature; already-settled but not-yet-observed contexts have
null targets rather than false failures. Retention remains a first-step episode
endpoint, never relabeled as 90 days after every action.

Every decision has `reward_30d_minor: null`. `training/episodes.jsonl` contains a
single reward per invoice/currency. Unknown/pending provider results or payment/
refund results not yet received make the episode unresolved and reward null.
Predictive baselines can consume schema2; this does not identify causal policy
value. Financial horizons start at the first decision, remain distinct from
decision-local prediction horizons, and retain integer minor-unit accounting.

Limits: no partial payments, chargebacks, automatic churn dynamics, sequential
causal estimator, real-data calibration or real provider calls were added.
