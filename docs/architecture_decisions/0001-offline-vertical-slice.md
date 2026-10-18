# ADR 0001 — Offline simulation before provider or platform integration

Context: the master prompt spans an entire research platform. Alroca's existing
working tree contains unrelated changes and has live financial boundaries.

Decision: independent repository, Python standard-library core, streaming SQLite
canonical artifact, batched JSONL and optional Zstd Parquet. Separate safety,
policy, structural causal mechanism, event engine, projections and evaluation.
No provider SDK, network requests, API, production database or billing adapter.

Alternative: extend Alroca or require PostgreSQL/Docker for generation. Rejected
for this slice because it couples experimental data to production and adds
infrastructure without improving the causal model. Optional PostgreSQL adapters
can later validate imports against an isolated schema.

Scope: one recovery decision and at most one retry per failed invoice. Oracle
is a one-decision counterfactual, not a whole-future policy rollout. All numeric
behavior is configurable and labeled hypothetical. Real-data calibration remains
an explicit aggregate contract, not silent fitting or transfer learning.

Risks: same-simulator training/evaluation overstates real value; incomplete
provider rules; endpoint retention is not churn dynamics; time-delayed webhook
stress does not delay policy observation. Document these rather than add fake
complexity. Rollback: discard the versioned generated folder and rerun a prior
config/code digest; never overwrite outputs in place.
