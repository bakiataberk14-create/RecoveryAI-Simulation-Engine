# Decision engine program — first implementation increment

Branch: `codex/decision-learning-foundation`. Engine version:0.5.0.

## Delivered

Workstreams1–4 now have an offline first-decision data foundation:

- Versioned 30-day observed net cash objective; no claim that raw recovery is
  incremental or caused by the selected action. Service fees are observed inputs,
  not newly calculated billable commissions.
- Exact allowlisted contract for permission, environment, tenant-scoped linkage,
  decision-time features/provenance, selected action, execution, delivery and
  provider-outcome assertions. Missing inputs remain null.
- Fail-closed quality controls: tenant/environment mixing, future/stale features,
  invalid monetary values, immature/unknown labels, missing delivery evidence,
  holdout dispatch, unsupported Turkish native retries and repeated provider events.
- Identical duplicate rows deduplicate; conflicting immutable decisions or multiple
  decisions per recovery block the batch. No independent per-step reward attribution.
- Feature/label/lineage separation; preregistered merchant-disjoint future holdout,
  label-availability embargo, artifact/split checksums and an expiry-aware loader.
- Invalid batches publish static diagnostic codes only, without raw rejected rows
  or training files. Size limits and no-overwrite behavior are enforced.
- Existing simulator training remains isolated from these research exports.
- CI now executes a synthetic contract preparation smoke test in addition to the
  full existing simulation/evaluation suite.

## Executed verification

- `python -m pytest -q tests/test_learning_foundation.py`: **66 passed**.
- `python -m pytest -q --junitxml=reports/junit-v5.xml`: **219 passed**, no skips.
- `python tools/check_junit.py reports/junit-v5.xml`:219 executed tests,
  no skipped/failed/error tests (not merely collection).
- `python -m compileall -q src tools`: passed.
- `git diff --check`: passed.
- `tools/create_learning_example.py outputs/final-learning-example-v5`, followed
  by `prepare-learning`: passed, two **synthetic** episodes, one train/one held-out
  test. Explicit loader reads both partitions successfully. These counts do not
  establish statistical adequacy or model quality.
- Unknown/PII/secret field canaries are rejected without copying their values into
  output diagnostics; wrong-type, deeply nested, oversized, malformed and ambiguous
  JSON are rejected. Conflicting decision, cross-tenant customer, reused payment,
  future-label, consent and holdout leakage cases are covered.

Remote CI status is reported separately after branch publication.

## Remaining / not claimed

The full twelve-workstream program is **not complete**. The implementation and
acceptance criteria are tracked in `docs/decision_engine_program.md`.

The local permission manifest is an operator attestation, not authentication or
legal approval. Provider-confirmed fields are exporter assertions; an Alroca
read-only exporter must independently verify access, signatures, reversal accounting
and complete observation windows. Actual product usage/support/finance sources
have not been specified. No real merchant records were imported.

No model was trained, no causal effect was inferred, and no empirical calibration,
merchant-specific fitting, uncertainty model, learned sequential policy, long-term
LTV estimator or production shadow/pilot was enabled. Existing synthetic policy
and lifecycle capabilities remain available, but do not prove real merchant lift.

Next safe increment: map actual Alroca sources and implement a read-only permissioned
export in an isolated worktree. Keep unavailable usage/LTV/support fields unknown;
then fit/evaluate conservative baselines on a sufficiently supported dataset.
