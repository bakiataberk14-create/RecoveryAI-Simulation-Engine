# Permissioned real-data boundary

The calibration adapter accepts **aggregates only**, not real event streams. The
`assess-calibration` CLI validates explicit permission, pseudonymous tenant
reference, population, UTC period, source version, integer counts and an exact
initial-failure denominator. Unknown fields (including PII) are rejected. Its
descriptive interval does not automatically alter simulator parameters.

Before real merchant integration:

1. Establish permission, retention policy and tenant-scoped export access.
2. Build a separately reviewed adapter mapping provider-confirmed records to a
   versioned observable schema. Exclude secrets and identity fields at source.
3. Preserve event/availability time, currency, live/sandbox and observation
   completeness. Never join synthetic records into billing or revenue ledgers.
4. Match population, denominator and window. Estimate a small identifiable
   parameter subset; record uncertainty. One aggregate cannot identify an entire
   customer behavior model. Keep held-out merchants and future periods untouched.
5. Produce a new explicit config/version with source lineage, before/after
   discrepancy report, sensitivity ranges and rollback to the prior config.
6. Run invariants, grouped temporal model validation and shadow evaluation. Only
   a separately approved real experiment can establish causal lift.

The separate [offline first-decision contract](learning_data_contract.md) now
validates operator-attested episode exports and guarded evaluation partitions.
It is not an authenticated Alroca export or a calibration fitter.

Planned, not implemented: authenticated merchant adapter, hierarchical Bayesian fitting,
drift monitoring, retraining scheduler, real-data model registry and serving.
Do not pretend those capabilities exist because this contract is documented.
