# Subscription lifecycle v0.4 — local verification

## Scope

Offline synthetic engine only. No production Alroca files, provider endpoints,
merchant data or credentials were used. Feature branch: `codex/subscription-lifecycle`.

## Changes

- Added configurable pause, resume, terminal cancellation and future price/interval
  changes, with strict configuration and ownership checks.
- Fixed paused renewal processing stranding all subsequent invoices.
- Added immutable subscription event and renewal-slot evidence, bounded issuance,
  stale queued-date handling and idempotent event/slot replay.
- Preserved original invoice terms during plan changes; fixed decision snapshots
  reading a changed subscription amount for an already-existing invoice.
- Kept retention boundary state distinct from later cancellation; retention remains
  a synthetic label, not empirically calibrated churn.
- Included exogenous lifecycle configuration in the paired-world fingerprint and
  documented that 30-day recovery comparison does not estimate long-term LTV.
- Added lifecycle generation, validation and policy-comparison steps to CI.

## Executed checks

- `.venv/Scripts/python.exe -m pytest -q --junitxml=reports/junit-v4.xml`:
  **153 passed**, no skips (24 lifecycle tests; 129 existing regressions).
- `.venv/Scripts/python.exe tools/check_junit.py reports/junit-v4.xml`:
  checks execution rather than collection, and rejects empty/skipped/failed tests.
- `.venv/Scripts/python.exe -m compileall -q src tools`: passed.
- Generation with `configs/lifecycle.json`, Parquet enabled:
  `outputs/final-lifecycle-v4`, 1,000 planned slots, 995 within horizon,
  987 issued invoices, 8 skipped inactive slots, 4 subscription controls.
  Five planned positions fall outside the horizon after interval changes.
- `validate --input outputs/final-lifecycle-v4`: **31 invariant groups passed**.
- `compare-policies --config configs/lifecycle.json --seeds 42`:
  `outputs/final-lifecycle-comparison-v4`, observe/fixed_retry/rule_based;
  all three passed 31 invariant groups and enrolled the same 83 failed invoices.
  Same initial-world and runtime-source hashes across all three runs.
- Runtime source SHA256:
  `700a091269491867d48b0d8ce673d1613efa5042e4b6b02671249c29932ae4e8`.
- Initial world SHA256:
  `00db02004ae6f926e8c6bbf6c4ad0b2d540a59e9c4d971759b740c50f6d39b4d`.

## Limits / next research work

One-seed smoke comparison is not evidence of real lift; currency groups have limited
merchant clusters. Configured lifecycle controls are exogenous, not learned or
caused by a recovery policy. Proration, currency conversion, policy-induced churn,
unrestricted renewal forecasts and subscription-level LTV estimands are intentionally
not implemented. Old schema2 datasets are not rewritten; regenerate them for the
new validator. Remote CI status is separate from these local results.
