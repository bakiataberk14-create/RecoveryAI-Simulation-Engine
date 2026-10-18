# Implementation guide (actual v0.1 commands)

Use Python 3.11+ and an isolated virtual environment. The core needs only the
standard library. `pip install -r requirements-dev.lock` reproduces the tested
Parquet/ML/test toolchain; then `pip install -e .`. Alternatively use the extras
in the README for compatible ranges. Windows activation: `.venv\Scripts\Activate.ps1`.

## Run

```bash
python -m recoveryai_sim generate --config configs/baseline.json --output outputs/run-100k --parquet
python -m recoveryai_sim validate --input outputs/run-100k
python -m recoveryai_sim evaluate --input outputs/run-100k --target-policy rule_based
python -m recoveryai_sim oracle-evaluate --input outputs/run-100k
python -m recoveryai_sim train --input outputs/run-100k
```

Outputs cannot overwrite an existing directory. Errors are nonzero exit codes;
a partially written directory has no complete manifest. JSONL logical hashes are
the reproducibility contract, not Parquet byte identity across library versions.
The manifest contains schema/engine/rule versions, code-content digest, source
registry version, effective configuration/seed and table counts/checksums.

`simulation.sqlite` is a normalized local research store with foreign keys and
immutable snapshot/event/oracle triggers. `operational/` has synthetic tables;
`training/` contains only an allowlisted learning view; `oracle/` holds hidden
truth. Never mount the SQLite/oracle artifacts into a production learner. JSONL
exports stream from SQLite; Parquet uses fixed SQL-derived schemas and 2048-row
batches. Runtime state is proportional to customer cohorts/pending events, not
an in-memory list of every generated table row. ML evaluation loads its smaller
failed-invoice view into memory; it is not a distributed trainer.

## Scenario and policy experiments

Scenario names: baseline, funds_shock, expired_wave, issuer_outage, high_churn,
enterprise, consumer, economic_stress, saturation, unseen_market.
Policies: randomized, observe, fixed_retry, rule_based.

```bash
python -m recoveryai_sim generate --invoices 10000 --merchants 30 --seed 43 --scenario saturation --output outputs/saturation
python -m recoveryai_sim evaluate --input outputs/saturation
python -m recoveryai_sim oracle-evaluate --input outputs/saturation
```

No-action is an explicit legal arm. Behavior propensities are exact over safe
actions. IPS refuses deterministic logging without full support and reports
effective sample size. Both IPS and oracle comparisons stay currency-separated.
Intervals bootstrap merchant clusters; one-cluster slices have no interval.
Oracle comparisons use the same exogenous noise for each action and report
increment relative to observe. They are one-decision comparisons on logged
contexts, not end-to-end multi-period policy values.

Run a predeclared multi-world/two-seed robustness experiment with
`python tools/run_research.py --output outputs/research --invoices 1000`.
It validates every run and compares baseline/saturation/economic stress without
tuning. `unseen_market` remains untouched as a future distribution-shift holdout.

Baseline predictors: constant training prevalence, scaled logistic regression,
histogram gradient boosting. The latter is an intentionally lightweight
scikit-learn baseline instead of adding LightGBM/CatBoost to this first slice.
Training and test merchants are disjoint; later test times and mature training
windows prevent temporal leakage. Only `x` enters the models. Output includes
Brier, PR-AUC, ROC-AUC and calibration bins. No trained model is silently deployed.

## Modules

| Module | Responsibility |
|---|---|
| config / parameters | validated versioned configuration and explicit assumptions |
| randomness | keyed, branch-independent deterministic exogenous noise |
| safety | conservative provider constraints and safe behavior-policy selection |
| causal | shared-noise legal potential outcomes, costs and negative effects |
| engine | chronological scheduler, persistent customer history and lifecycle |
| storage / views | relational store, immutable evidence, batched exports, feature allowlist |
| replay / validation | duplicate/order/tenant handling and artifact invariants |
| evaluation | grouped temporal models, currency-separated IPS and explicit oracle evaluation |
| calibration | permissioned aggregate contract; no automated parameter fitting |
| cli | executable commands and structured reports |

## Release/testing limits

The GitHub Actions workflow installs all test dependencies, runs the suite,
rejects skipped/empty JUnit results, compiles source, generates/validates 10K
invoices, runs OPE/oracle/model baselines and uploads reports. Workflow presence
alone does not prove a GitHub run passed or branch protection is enabled.

1M generation is configurable but not yet a validated performance promise.
Provider sandbox calls, full Stripe API-version payload contracts, PostgreSQL
imports, adversarial concurrency in a real service, production auth and real
merchant calibration are outside this executable offline slice.
