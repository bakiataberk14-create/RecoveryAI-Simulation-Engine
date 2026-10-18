# v0.1 local verification — 2026-10-18

Executed on Windows, CPython 3.11.15, using the isolated `.venv` and the pinned
dependencies in `requirements-dev.lock`.

| Verification | Result |
|---|---|
| `python -m pytest -q --junitxml=reports/junit-local.xml` | 63 passed, zero skipped |
| `python tools/check_junit.py reports/junit-local.xml` | 63 executed; zero skip/failure/error |
| `python -m compileall -q src` | Passed |
| 100,000-invoice baseline generation, seed42, 100 merchants, Zstd Parquet | Completed in 60.22 seconds on this machine |
| `validate --input outputs/verified-100k` | All 19 invariant groups passed |
| `train --input outputs/verified-100k` | Constant/logistic/histogram boosting evaluated |
| `evaluate --input outputs/verified-100k` | Currency-separated IPS, support and cluster intervals produced |
| `oracle-evaluate --input outputs/verified-100k` | Paired observe/fixed-retry/rule-based comparisons produced |
| `tools/run_research.py --output outputs/research-v1 --invoices 1000` | Six validated runs: three worlds, two seeds |
| `validate --input examples/sample_dataset` | All 19 invariant groups passed |

The validated 100K run contains 5,745 customers/subscriptions, 7,367 payment-method
records including replacements, 103,893 attempts, 10,697 recovery decisions and
observed outcomes, 3,436 communications, 205,027 internal events, 224,978 delivery
records and 38,455 isolated potential-outcome rows.

Verified source digest:
`ae6cacf5529861ee6ad7e3eda384bfbe68ad6071db9ef0580368f34436f54ee2`.
Effective configuration digest:
`56e274f03d3bead89a8f5a26319157dfc9b8844a260af57ed48e4460ab4be112`.
The complete manifest and per-export logical checksums remain in the generated
run folder. Large datasets and local SQLite stores are ignored by Git; only the
small synthetic JSONL sample is included in the repository.

Tests cover repeatability, all scenario configurations, hard/unknown decline
guards, disconnected/unknown provider and advice restrictions, consent,
no-action communications, oracle isolation, future features, censored labels,
negative intervention effects, replay/order/tenant failures, invalid config,
immutable evidence, refund accounting, replacement methods, Parquet round-trip,
OPE overlap restrictions and permissioned aggregate validation. Hypothesis tests
exercise arbitrary decline input. Network connections are blocked by the test
fixture.

Not executed locally: Linux/Python3.12 CI, a 1M-invoice performance run, live or
sandbox PSP calls, provider API-version payload certification, PostgreSQL import
or real merchant calibration. GitHub workflow results must be checked separately;
this local report does not claim a remote workflow or branch-protection result.
