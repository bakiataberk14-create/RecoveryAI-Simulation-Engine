# RecoveryAI-Simulation-Engine
## Sequential engine: v0.2

Schema2 adds delayed observations, database-enforced state transitions and bounded
multi-step recovery. Read [the v2 contract and limitations](docs/sequential_v2.md).
Schema1 remains available for the existing one-decision experiments.

```bash
python -m recoveryai_sim generate --config configs/sequential.json --output outputs/sequence --parquet
python -m recoveryai_sim validate --input outputs/sequence
python -m recoveryai_sim train --input outputs/sequence
```

Decision evidence is timestamped and immutable. Dispatch rechecks payment,
subscription, method and consent state. Episode financial rewards appear once;
one-step policy estimators explicitly reject sequential datasets.

## Runnable implementation: v0.1

The repository now contains an offline vertical slice. The original blueprint
below is preserved as the roadmap, **not a claim that every planned module is
complete**. Start with [the implementation guide](docs/implementation.md),
[data dictionary](docs/data_dictionary.md), [assumptions](docs/assumptions.md) and
[data card](docs/simulation_data_card.md).

```bash
python -m venv .venv
# Activate .venv for your shell, then:
python -m pip install -e '.[dev,parquet,ml]'
python -m pytest -q
python -m recoveryai_sim generate --invoices 10000 --merchants 30 --seed 42 --output outputs/demo --parquet
python -m recoveryai_sim validate --input outputs/demo
python -m recoveryai_sim evaluate --input outputs/demo
python -m recoveryai_sim train --input outputs/demo
```

Implemented: event queue; persistent customer histories; safe action gate;
randomized/observe/fixed-retry/rule-based policies; exact minor-unit accounting;
refunds; censored labels; separate observable/oracle views; Parquet; grouped
temporal baseline models; currency-separated IPS; tenant/replay validation.

No live calls, production billing integration or empirical calibration. No claim
to reproduce Stripe Smart Retries. Synthetic outputs cannot establish real lift.
Full sequential recovery, real cancellation dynamics, Adyen execution rules,
SMS, DR estimators, real-data adapters and production retraining remain planned.

## Original design blueprint (preserved)

sentetik data
RecoveryAI Synthetic Payment Intelligence Engine
Project status: specification and development blueprint. This README defines the intended architecture, contracts, quality gates, and agent workflow. It does not claim that the described modules, CLI commands, datasets, benchmarks, or tests already exist. Implemented capabilities must be tracked explicitly as work progresses.
Data classification: All generated payment, merchant, customer, and financial records are SYNTHETIC — NOT REAL TRANSACTIONS. Results from this simulator do not establish real-world recovery lift or payment approval rates.

1. Mission
Build a reproducible, source-aware, event-driven subscription-payment simulator for RecoveryAI: a B2B platform that helps subscription businesses safely recover failed payments and, eventually, optimize retention and net customer revenue.
This repository should produce two distinct products:
1. Operational realism: synthetic Stripe-like subscription and payment events for testing ingestion, webhooks, idempotency, retries, reconciliation, tenant isolation, and failure handling.
2. Decision intelligence: a stochastic environment with sequential customer behavior, permitted interventions, observable outcomes, and separately held simulator-only counterfactual truth for model development and policy evaluation.
North star: Help RecoveryAI build and test safe systems today while creating an auditable path to learning from permissioned real merchant data later. Volume of synthetic records is not the primary quality metric.
Non-goals
- Recreating Stripe Smart Retries' proprietary model or claiming to know its internal performance.
- Claiming synthetic training/evaluation proves real-world uplift.
- Producing real card numbers, CVVs, real customer identity data, credentials, or realistic-looking secret tokens.
- Running unsupervised payment attempts against live PSPs.
- Implementing every future revenue optimization feature in the first release.
2. Operating principles (read this first, especially coding agents)
1. Make a runnable vertical slice first. A tested 10,000-invoice simulation beats an unfinished million-row generator.
2. Facts ≠ benchmarks ≠ assumptions. Every consequential rule/parameter must be tagged VERIFIED_RULE, EMPIRICAL_BENCHMARK, CALIBRATED_ESTIMATE, SYNTHETIC_ASSUMPTION, or EXPERIMENTAL_HYPOTHESIS.
3. Safety first. A payment action is eligible only if the versioned, provider-specific safety policy allows it. When evidence is ambiguous, default to no automatic retry or explicit review.
4. Time is causal. Features used at decision time must actually be available by that timestamp. Future outcomes and latent simulated states cannot appear in production-like ML data.
5. One underlying world, multiple views. Operational events, training features, action logs, outcomes, and oracle/counterfactual data must be derived consistently, but stored separately.
6. Use integer minor units for money. Do not reconcile financial amounts using binary floating-point arithmetic. Store currency and explicit fee/discount/refund components.
7. Maintain uncertainty. Calibrate only to benchmarks with defined population, metric, observation window, and denominator. Run sensitivity analysis instead of inventing precision.
8. Keep provenance attached. All simulation runs retain a config snapshot, source-registry version, code revision, scenario, seed, clock/calendar settings, and output checksums.
9. Never silently change semantics. Schema or metric changes require versioning, migration/compatibility notes, and updated tests.
10. Fail loudly. Tests or rules not executed must be reported as not verified, never described as passing.
3. Intended users and outputs
Consumer	Data product	What it tests	What it cannot establish
Backend engineers	Operational event stream	State transitions, API contracts, webhook ordering/retries, idempotency	Real issuer behavior
Data engineers	Relational Parquet/DB tables	Referential integrity, reconciliation, throughput	Market representativeness
ML engineers	Decision-time feature and label views	Pipeline correctness, calibration on simulated worlds	Real-world prediction accuracy
Causal/decision researchers	Logged policies, rewards, oracle truth	Off-policy estimators, controlled simulator comparisons	Causal lift on actual merchants
Reliability/security engineers	Fault and edge-case scenarios	Failure handling and access boundaries	Full production security certification


4. Research foundation and evidence registry
Do not scrape unrelated statistics into a single probability distribution. Research official documentation at the time of implementation and pin version/date where applicable.
Starting references (read and verify; URLs here are research starting points, not proof that any numeric claim has been checked):
- Stripe Billing — Smart Retries
- Stripe — Card declines
- Stripe — Webhooks
- Stripe — Testing
- Stripe Billing — Test Clocks
- Adyen — Raw acquirer responses
- Recurly — State of Subscriptions
- Baremetrics — Subscription payment recovery benchmarks
- PCI Security Standards Council
For each consequential claim or rule, maintain sources/source_registry.yaml (or an equivalent machine-readable file) with:
parameter_or_rule_id, evidence_class, source_url, accessed_at, published_at_if_known, provider_api_version_if_applicable, population, denominator, time_window, value_or_rule, units, uncertainty, notes, owner.
Mandatory discipline: Distinguish attempt success, failed-invoice recovery, merchant-level medians, recovered gross value, and incremental revenue. Never mix their denominators or assume reports from different merchant populations are comparable. Unknown base rates stay explicit synthetic assumptions with tunable ranges.
5. Architecture
Versioned evidence + documented assumptions
                    |
           Scenario configuration
                    |
   Merchant + customer + subscription generators
                    |
      World state and event-time scheduler
                    |
    Invoice -> payment attempt -> observed decline
                    |
       Versioned safety / eligibility gate
                    |
     Logged decision policy (incl. propensities)
                    |
     Action execution -> response -> new events
                    |
    Invoice settlement / churn / retention outcomes
                    |
       Validated canonical event and data store
          /              |               \
 Operational view   ML/decision view   Simulator-only oracle
 (safe events)      (point-in-time)    (latent + counterfactuals)
          \              |               /
          Calibration, stress tests, quality reports
Separate these boundaries
- Payment-provider adapter: provider-specific event shapes, decline mappings, advice codes, and permitted actions.
- Canonical domain: stable internal model for invoice, attempt, action, customer, and outcome. Raw provider payloads are not the canonical truth.
- World simulator: maintains hidden state and models how events unfold.
- Policy engine: determines admissible interventions. A prediction must never override a safety rule.
- Decision policy: selects from admissible actions and logs its selection probability.
- Projections/exports: derive observable features, labels, and private oracle data independently from the same simulated trajectory.
- Evaluation: tests financial and behavioral consistency plus policy comparisons with uncertainty estimates.
Design components with explicit interfaces so real merchant data can replace synthetic parameter estimates without rewriting the whole system.
6. Canonical domain and minimum schema
Use stable synthetic identifiers, documented nullability, timezone-aware timestamps (UTC internal storage), explicit schema versions, and foreign keys. Plan for these logical tables:
Table	Key fields / duties
merchants	merchant_id, tenant_id, industry, region, PSP, billing profile, policy version
customers	customer_id, merchant_id, signup, observed history, consent status
payment_methods	Synthetic non-sensitive metadata, status, expiry, update history
subscriptions	subscription_id, customer, plan, recurring amount, currency, schedule, status history
invoices	Invoice lifecycle, amount due/paid/remaining, currency, timestamps, status
payment_attempts	Attempt index/time, method, PSP, raw/canonical decline, advice, result, cost
recovery_decisions	Decision timestamp, known context, admissible action set, chosen policy, propensity
recovery_actions	Executed action, result, communication or payment-method update, costs
communications	Permitted channel, template variant, delivery/engagement events, opt-outs
outcomes	Settlement, refund, net value, time-to-recovery, 30/60/90-day outcomes and censor flags
event_log	Immutable synthetic event envelope, event/processing times, ordering and duplication metadata
simulator_oracle	Private hidden world state, potential outcomes, simulated causal effects
run_manifest	Seed, code commit, config hashes, source registry, software and data schema versions


Important modeling rules:
- An invoice can have multiple payment attempts and recovery actions; attempts and actions are not one-to-one.
- Distinguish event_time, observed_at, decision_time, and processed_at when modeling latency and delayed webhooks.
- Maintain an append-only event record; projections may be recalculated. Duplicate deliveries must never imply duplicate business effects.
- Invoice, subscription, and payment attempt states must have tested legal transitions. Paid, voided, disputed, refunded, and outstanding amounts cannot be casually interchanged.
- Model subscription cancellation separately from failure to collect a specific invoice.
- Save issuer/customer latent variables only in simulator_oracle or internal simulation state; never include them in regular production-like feature views.
- Do not invent real BIN/IIN, PAN, CVV, access tokens, or identifying customer information.
7. Statistical and causal simulation design
7.1 Generate dependence, not random independent rows
Model hierarchical merchant differences, customer payment reliability, behavioral heterogeneity, plan value, time-varying economic conditions, shared PSP/issuer outages, expiring payment methods, prior attempts, and retention. Prefer transparent probabilistic rules and documented parameters before complex generators.
Potential building blocks: hierarchical distributions, mixture models, survival/hazard processes, state machines, common shocks, and a discrete-event queue. Each addition must solve a concrete realism or evaluation need.
7.2 Two distinct probability concepts
- Observational prediction: P(invoice paid within horizon | information available at time t, existing policy).
- Action value: E(net outcome under do(action a) | information available at time t).
These are not interchangeable. A high predicted recovery probability does not prove a retry, email, discount, or update request caused the payment to recover.
7.3 Sequential decisions and counterfactuals
At each decision point:
1. Snapshot observable information available at that time.
2. Compute the safely eligible action set.
3. Select an action under a versioned behavior policy; log the action's probability.
4. Execute the action through the simulator; advance events and state.
5. Log observed outcome and costs.
6. If evaluating alternatives, calculate potential outcomes in isolated oracle experiments using compatible shared random shocks; never put those alternatives in training exports.
Require an explicit no-intervention baseline. Account for natural recovery: a recovered invoice is not automatically incremental revenue attributable to RecoveryAI.
7.4 Recovery metrics
Document all formulas and their denominator/time window. Minimum metrics:
- First-attempt failure rate.
- Invoice-level recovery within 7/14/30 days.
- Time to recovery (with censoring).
- Gross recovered invoice value.
- Incremental net value versus an explicit baseline.
- Communications, retries, discounts, fees, refunds, and downstream retention impacts.
- Merchant-level distributions; do not hide variance behind global averages.
8. Safe actions and policies
Supported candidate action types may include do_nothing, wait, retry, request_payment_update, send_email, send_sms, request_authentication, offer_pause, offer_downgrade, offer_discount, human_review.
They are not all automatically executable. Availability depends on customer consent, merchant policies, PSP support, provider/scheme restrictions, payment-method state, and the current event. Never infer retry permission solely from a simplified "soft" vs "hard" label.
Maintain reviewed, source-linked PSP rules in a versioned file such as configs/decline_rules.yaml. For every rule: list its evidence/version, scope, and what happens if provider advice is unavailable or conflicts with defaults. Record the rule fired in each recovery decision.
A supervised ML model must not authorize an action excluded by this policy. An unsafe recommendation must produce a conservative fallback or review task—not a real retry.
9. Scenarios: baseline, tail risks, and distribution shift
Implement each scenario as a configuration overlay, not duplicated generator code. Start with:
1. baseline_b2b_saas — ordinary recurring invoices and merchant heterogeneity.
2. consumer_subscriptions — lower average bills and larger customer populations.
3. enterprise_b2b — higher invoice values, fewer accounts, different retention mechanisms.
4. liquidity_shock — hypothetical temporary increase in insufficient funds.
5. card_expiry_wave — correlated payment-method update needs.
6. issuer_outage — correlated time-bounded failures.
7. high_churn — higher customer cancellation hazard.
8. communication_fatigue — negative effects from repeated outreach.
9. webhook_disorder — duplicates, retries, delayed/out-of-order deliveries.
10. unseen_holdout — deliberately shifted distributions hidden from model design/tuning.
Scenario severity and rates are configuration parameters, not measured market frequencies unless independently supported. Include a no-action counterfactual and alternative policies under each scenario.
10. Dataset exports and leakage prevention
Export separately:
- operational/: redacted/synthetic event payloads and normalized finance/CRM records.
- ml_observed/: features valid at a decision timestamp, policy-selected action, recorded propensity, observed reward and valid labels.
- oracle_private/: simulator latent states, unchosen potential outcomes and simulated optimal actions. Do not include in model training inputs.
- stress/: edge cases and shifted evaluation worlds.
- reports/: run manifests, audits, calibration, validation, and benchmark plots.
Strict leakage checks:
- Features have available_at <= decision_time.
- Label horizons begin after the relevant decision; incomplete 30/60/90-day labels are marked censored or missing, not false.
- Disjoint time/merchant evaluation slices where appropriate; don't randomly split event rows sharing invoices or customers.
- No oracle fields, future customer updates, eventual settlement flags, future interventions, or post-decision aggregates in features.
- Selection bias and outcome-dependent missingness are acknowledged explicitly.
For policy learning, preserve action propensities and verify overlap/positivity before inverse propensity or doubly robust estimators. Report when off-policy evaluation is not identified.
11. Development phases and definition of done
Status labels: [ ] not completed / [x] verified completed. Agents must not check boxes without evidence from code execution. Initial status is intentionally unchecked.
Phase 0 — Contracts and evidence
- [ ] Pin Python/tooling versions and establish reproducible environment.
- [ ] Create versioned schemas, event/state contracts, and run-manifest format.
- [ ] Verify provider safety documentation and create sourced rule registry.
- [ ] Create separate assumptions, scenario, and evidence registries.
Exit gate: spec files validate, rule references exist, basic test suite starts.
Phase 1 — First end-to-end vertical slice
- [ ] Generate merchants, customers, subscriptions, invoices, attempts and outcomes as one time-ordered simulation.
- [ ] Add eligible action enforcement, a simple logging policy, and append-only event logs.
- [ ] Export all three boundary views: operational, observed ML, private oracle.
- [ ] Successfully run a deterministic 10K-invoice test and invariant checks.
Exit gate: one CLI run creates verifiable consistent data, and an identical seed/config reproduces the same logical outputs.
Phase 2 — 100K invoices and calibration
- [ ] Add heterogeneity, correlated shocks and configurable scenario families.
- [ ] Build benchmark comparison reports with denominators and uncertainty.
- [ ] Produce at least 100K invoice records without compromising constraints.
- [ ] Verify memory/runtime characteristics and output lineage.
Exit gate: successful generator, calibration limitations documented, zero critical data-integrity or policy failures.
Phase 3 — Decision intelligence
- [ ] Train simple baselines (heuristics and logistic/gradient-boosted models).
- [ ] Evaluate calibration, time/merchant holdouts and scenario shifts.
- [ ] Compare policies using simulator oracle and, where valid, logged-policy estimators.
- [ ] Report cost-adjusted incremental outcomes and uncertainty.
Exit gate: reproducible evaluation report; no claim of real-world AI superiority.
Phase 4 — Real-data readiness (no real data required to finish earlier phases)
- [ ] Define privacy/permission boundary and a merchant-data adapter interface.
- [ ] Design calibration updates with observed real outcomes and drift monitoring.
- [ ] Preserve source/version provenance and rollback-safe policy changes.
Exit gate: an integration design that does not require a simulator rewrite.
12. Proposed repository structure
This is a target structure. Create files incrementally as phases are implemented.
.
├── README.md
├── pyproject.toml
├── configs/
│   ├── assumptions.yaml
│   ├── decline_rules.yaml
│   └── scenarios/
├── sources/
│   └── source_registry.yaml
├── docs/
│   ├── data_dictionary.md
│   ├── event_contracts.md
│   ├── metric_definitions.md
│   ├── architecture_decisions/
│   └── simulation_data_card.md
├── src/recoveryai_synthetic/
│   ├── cli.py
│   ├── domain/
│   ├── adapters/
│   ├── generators/
│   ├── simulation/
│   ├── policies/
│   ├── projections/
│   ├── calibration/
│   ├── evaluation/
│   └── validation/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── properties/
│   └── regression/
├── examples/
├── reports/
└── outputs/                 # generated, ignored by git
Planned command interface (not available until implemented)
# Install (after pyproject.toml is created)
python -m pip install -e '.[dev]'

# Produce a deterministic initial run
python -m recoveryai_synthetic generate \
  --invoices 10000 --merchants 20 --seed 42 --scenario baseline_b2b_saas

# Validate outputs and safety invariants
python -m recoveryai_synthetic validate --input outputs/latest

# Compare strategies in a defined world
python -m recoveryai_synthetic evaluate --scenario baseline_b2b_saas

# Run automated tests
python -m pytest
The CLI should print its manifest path, effective configuration, created output paths, validation summary, and failure exit code. Do not advertise a command as working in this README until it exists and has been executed successfully.
13. Mandatory tests and invariants
Financial integrity
- Amounts use minor units/decimals with explicit currency; negative charges require clearly named reversal/refund semantics.
- Paid + outstanding + valid adjustments reconcile with invoice obligations under the defined accounting model.
- An executed payment cannot result in duplicate collection from replayed events.
- Refunds, credit notes, disputes, fees and discounts are not double counted.
State and chronology
- No event occurs before its prerequisites.
- Payment attempt count and transitions match the event stream.
- Every referenced merchant, customer, invoice, payment method and action exists and belongs to the correct tenant.
- Delayed, duplicate and reordered event deliveries don't corrupt derived financial state.
- Event times and processing times are modeled separately.
Decision safety
- Every executed automatic retry passes the current provider/version safety rules.
- Forbidden or unknown action states cannot be bypassed by ML predictions.
- Customer consent and merchant settings gate communications.
- A decision log includes its admissible actions, policy version, and action probability.
Statistical fidelity
- Seed reproducibility is tested at the logical-record level (avoid assuming Parquet file binary hashes are stable across engine versions).
- Distributional behavior matches documented scenario constraints within tolerance.
- Empirical calibration compares like-with-like denominators with uncertainty.
- Synthetic ground-truth causal effects can be recovered under controlled sufficient-support experiments within confidence intervals.
- Models fail or degrade appropriately on challenging shifted scenarios—do not tune hidden holdouts until they look good.
Training safety
- No timestamp leakage or simulator oracle variables in observable exports.
- Data split manifests prevent invoice/customer/merchant overlap where required.
- Censored outcomes and missingness are represented correctly.
- Off-policy evaluation reports limited overlap or violations honestly.
CI blocking condition: no merge if required safety, financial, tenant-isolation or leakage tests fail. A skipped test is not evidence of passing.
14. Performance, privacy and operational safety
- Generate data in batches/streams; compressed Parquet is the preferred bulk output.
- Never commit large generated datasets, raw provider credentials, or local secrets. .gitignore should cover outputs/, .env, caches, and temporary extracts.
- Use test/sandbox provider integrations only and mark all synthetic payloads unambiguously.
- No external network calls during routine deterministic generation; research or optional provider API tests must be separately invoked and documented.
- Treat tenant isolation as a domain invariant, not just a database filter.
- Protect oracle_private/ from inadvertent use in ML training and serving workflows.
- Include dependency checks, static analysis, and secure secret-handling tests as the project matures.
- Set resource budgets and deterministic failure behavior for stress/load tests; avoid uncontrolled real API activity.
15. Agent collaboration contract
This section is intentionally written for future coding agents (Claude Code, Codex, Copilot, Cline, or other development assistants) that work in this repository.
Before changing code
1. Read this README, the current request, relevant source files, and the applicable tests.
2. Inspect the actual repository structure; do not assume planned modules already exist.
3. Review the source/assumption registry before changing payment probabilities, decline behavior, business rules, or evaluation metrics.
4. State the specific end-to-end behavior being added and the tests that will demonstrate it.
5. Prefer the smallest coherent implementation that can run and be audited.
While working
1. Never silently fabricate documentation, numerical evidence, test results, or payment behavior.
2. Preserve event ordering, point-in-time feature correctness, schema compatibility, and tenant isolation.
3. Build or update tests with each behavior change; regression tests for every discovered bug.
4. Keep provider-specific facts in adapters/rule files, not scattered magic constants.
5. Keep probabilistic assumptions in versioned configs, not buried as unexplained numbers inside functions.
6. Use explicit interfaces, type hints, descriptive names, deterministic seeds, and meaningful error messages.
7. Do not train or tune on oracle fields, future labels, or the held-out distribution-shift scenario.
8. Never bypass policy restrictions to improve a synthetic recovery metric.
9. Do not expand scope to additional PSPs, dashboards or advanced ML before the current vertical slice is passing.
10. Avoid refactors that change data semantics without adding a migration or compatibility note.
Before reporting completion
Execute the relevant generator, validation checks and test suite (when execution is available). Then provide:
- Changed files and brief reasons.
- Commands executed, with success/failure status.
- Generated artifacts and where to find them.
- Data/metric or schema changes and affected versions.
- Scientific assumptions introduced or altered.
- Known limitations, unexecuted checks, and follow-up risks.
- Next highest-value task consistent with the phase plan.
If tools are unavailable, say precisely which validations were not run. Never claim code passes merely because it looks plausible.
Review checklist for pull requests
- [ ] Clear business/scientific objective and acceptance criteria.
- [ ] End-to-end behavior demonstrated on reproducible synthetic fixtures.
- [ ] Provider constraints and citations reviewed where relevant.
- [ ] Determinism and lineage preserved.
- [ ] Financial, temporal and tenant invariants tested.
- [ ] No simulator oracle / future feature leakage.
- [ ] Benchmark denominators and metrics remain consistent.
- [ ] Data contracts, config, docs and tests updated.
- [ ] Commands and actual results reported; limitations stated.
Decision records
For cross-cutting architecture choices, create a short docs/architecture_decisions/NNNN-title.md containing: context, alternatives, chosen approach, evidence, risks, compatibility impact, and rollback strategy.
16. Quality bar and success criteria
A successful release is not "one million realistic-looking rows." It is a well-characterized synthetic environment that:
- Generates complete, internally coherent invoice and recovery trajectories.
- Enforces sourced payment safety constraints and financial invariants.
- Provides deterministic, documented and versioned simulations.
- Clearly separates observed features from latent/counterfactual oracle data.
- Supports reproducible baselines, uncertainty-aware comparisons and unseen worlds.
- Exposes where evidence ends and synthetic assumptions begin.
- Can later incorporate permissioned real merchant observations without erasing provenance.
The core scientific warning
A model that wins against its own simulator has demonstrated success inside that simulator. It has not demonstrated superior recovery on real banks, real customers, or actual Stripe merchants. Real-world claims require consented operational data, safe deployments, and carefully designed validation or experiments.

17. Immediate next task for the first coding agent
Implement Phase 0 plus the smallest complete Phase 1 vertical slice. Begin with the schema, source/assumption registries, 2–3 explicit merchant archetypes, an event scheduler, invoices, payment attempts, a conservative eligibility policy, observed outcome logging, private oracle separation, a reproducible seed and invariant tests. Generate and validate 10K invoices before increasing scale or sophistication.
Do not begin by fine-tuning a large language model or generating millions of unrelated payment rows.
Maintainer note: Keep this README aligned with reality. Move planned capabilities into verified status only after executing the implementation and its tests. Scientific integrity, decision safety, and auditable reproducibility are the project's defining product features.
