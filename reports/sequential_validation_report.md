# v0.2 sequential release verification — 2026-10-18

Scope: delayed evidence, legal state transitions, bounded multi-step recovery.
Schema1 remains supported. No real provider, live merchant or production billing
operations were performed.

## Changes and reasons

| Files | Behavior/gap closed |
|---|---|
| `sequential.py` | Physical events and received knowledge are separate; decisions require delivered evidence. Bounded follow-up, conditional propensities, current-state dispatch guards and native observation paths. |
| `state_machine.py`, `sequential_schema.py`, `storage.py` | SQL-enforced legal state transitions, immutable evidence, unique step/result/observation keys and versioned schema extension. |
| `sequential_views.py`, `views.py` | Per-step observed features/labels and evidence references; financial episode reward exported once. |
| `sequential_validation.py`, `validation.py` | 26 validation groups for financial, tenant, temporal, execution, training and export invariants. |
| `evaluation.py` | Rejects one-step IPS/oracle evaluation for sequential trajectories rather than duplicating invoice rewards. Predictive baselines can still consume the observed view. |
| `config.py`, `engine.py`, `configs/sequential.json` | Explicit schema2 selection, bounded configuration, compatible schema1 path and source registry version. |
| `tests/test_sequential.py` | 29 focused behavioral tests, including delayed/reordered/duplicate events, state regression, cancellation, consent, unknown results and holdout attribution. |
| CI workflow and documentation | Adds generation/validation/model smoke tests for schema2 on both Python versions; explains the statistical scope and limits. |

## Executed local checks

- `python -m pytest -q --junitxml=reports/junit-v2.xml`: **92 passed**, zero skipped,
  including the original63 tests and29 sequential tests. Runtime23.49 seconds.
- `python tools/check_junit.py reports/junit-v2.xml`: executed test count accepted;
  zero skip/failure/error.
- `python -m compileall -q src tools`: passed.
- `generate --config configs/sequential.json --output outputs/verified-sequential-v2 --parquet`:
  completed in12.71 seconds on this Windows/Python3.11 machine.
- `validate --input outputs/verified-sequential-v2`: **26 invariant groups passed**.
- `train --input outputs/verified-sequential-v2`: constant/logistic/histogram
  boosting evaluated with disjoint merchants and a temporal maturity embargo.
- `git diff --check`: passed.

The verified dataset contains10,000 invoices,3,220 decisions,854 episode outcomes,
10,769 attempts,1,029 communications,22,402 observations,3,220 immutable dispatch
results and8,313 oracle-only next-window alternative rows. Some failed invoices
have no decision because payment is observed before an actionable failure or
because the horizon closes before evidence arrives.

Source digest:
`ef38ff2dde1f74b31f0590d8a7dd3b195b582bdde7b548cbdf9129689891025c`.
Configuration digest:
`c20ddeb19e6d15c496dec8abdfbb7755c8406da5b39fd27d54bbfe933d7c01ce`.

## Findings fixed and retested

1. Native observe payments initially inherited the observation action ID. Fixed:
   natural payments have no intervention action ID; holdout has zero customer
   notification or automated payment dispatch. Regression test passed.
2. Reordered control messages could overwrite newer consent/subscription state.
   Fixed with per-control business-time/event-ID versions. Stale grant and pause
   regressions passed.
3. Pending/unknown provider results could be mistaken for a mature negative
   outcome without a delivered uncertainty message. Fixed by checking unresolved
   provider attempts at the outcome boundary; labels/reward remain null.
4. Dispatch bookkeeping initially omitted hypothetical step costs. Fixed:
   immutable action results match communication/retry cost records; episode
   reconciliation and focused tests passed.

## Statistical result and remaining limits

For this simulated sequential run, the constant Brier score was0.123063,
logistic0.165330 and histogram boosting0.161434. Both trained models performed
worse than the constant baseline on this metric. No improvement or real recovery
lift is claimed.

The window hazard and customer responses are uncalibrated synthetic hypotheses.
Next-window oracle alternatives are not full counterfactual trajectories. The
existing one-step policy estimators intentionally return blocked for schema2.
Sequential causal evaluation is a later development, not a failing required
integration. Retention remains a synthetic episode endpoint; real cancellation
dynamics, real-data calibration and provider integrations remain separate tasks.

This report records local evidence. Remote GitHub Actions results are linked in
the delivery message after the pushed commit is checked.
