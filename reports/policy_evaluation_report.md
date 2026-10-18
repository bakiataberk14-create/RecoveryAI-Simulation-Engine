# Engine0.3 policy evaluation verification — 2026-10-18

## Delivered behavior

- Complete observe/fixed_retry/rule_based reruns share initial-world fingerprints
  and semantic event/calendar-window random shocks. Exact initial-failure cohort
  mismatches or source changes stop the comparison.
- Financial evaluation uses a new explicit30-day contract anchored at initial
  failure. It includes naturally paid invoices with no decision, excludes the
  initial sunk attempt cost, reconciles fees/refunds and remains currency-local.
- Administrative maturity reserves the configured maximum callback delay equally
  for successes and failures. Unresolved evidence blocks a currency rather than
  dropping cases. Unsupported partial payments/refunds fail explicitly.
- Logged-data trajectory IS multiplies conditional action ratios over the
  customer's entire relevant history, including earlier/overlapping invoices.
  The financial return appears once per invoice. Support diagnostics distinguish
  customers who had decisions from decisionless natural recovery.
- Source digests are checked against the imported code before and after each
  generation, and across policy reruns. A changed source cannot publish a complete
  simulation manifest. This closes a reproducibility gap during long experiments.

## Executed checks

| Check | Result |
|---|---|
| `python -m pytest -q --junitxml=reports/junit-v3.xml` |129 passed; zero skipped |
| `python tools/check_junit.py reports/junit-v3.xml` |129 executed; no failure/error/skip |
| `python -m compileall -q src tools` |Passed |
| Final matched comparison |12 runs,24,000 invoices,28.84 seconds locally |
| Each comparison child's validation |28 invariant groups passed |
| Same-source proof |One source digest across all12 runs |
| Randomized logged-data evaluation |3,000 invoices; all six currencies blocked for insufficient trajectory support |
| `git diff --check` |Passed |

Final comparison folder: `outputs/final-policy-comparison-v3`.
Logged-data folder: `outputs/final-randomized-v3`.
Runtime source digest:
`bfc7d450fc00ccae2a9c60c737f0de74826cfdf6cc24019b4d7d5e58f31df980`.
Large generated artifacts remain ignored by Git; commands/configs reproduce them.

The32 initial evaluation tests were extended with duplicate-cohort, unsupported
partial-amount and source-change regression cases, for37 new tests over the
previous92-test suite. These include exact toy trajectory weights, unknown/censored
returns, natural recovery without decisions, day30/day31 refunds, calendar/timezone
alignment, oracle-read denial, identical-world reruns, negative paired effects,
insufficient clusters, deterministic-log rejection and customer-history support.

## Observations and limits

The final experiment used baseline/saturation, seeds42/43,20 merchants and2,000
invoices per run. Every rule-based currency slice was flagged `limited_clusters`.
Baseline paired values had mixed signs; some positive intervals crossed zero.
All saturation rule-based point differences were negative. These patterns are
properties of the uncalibrated model and fixed worlds; they are not empirical
merchant lift, a model-selection win or a production stop recommendation.

The3,000-invoice randomized dataset had inadequate complete-history overlap for
the default ESS/merchant thresholds. The estimator correctly returned blocked
and null value/interval fields instead of fabricating a precise OPE result.

No real provider calls, merchant imports, billing changes or real controlled
experiment were performed. Sequential doubly robust estimation, automatic churn
and future invoice-generation effects remain outside this release. The fixed
cohort/no-customer-interference assumptions must be reconsidered before those
modules or real-data adapters are introduced. Existing one-step estimators stay
blocked on schema2.

Remote CI evidence is linked in the delivery message after the pushed commit's
Python3.11/3.12 runs are checked.
