# Decision engine program — 12 ordered workstreams

Status is evidence-based. "Offline foundation" never means production approval.
This program does not install a new model, enable collection, start a merchant
experiment, or change Alroca production/billing behavior.

| # | Workstream | Current status | Exit criterion / dependency |
|---|---|---|---|
| 1 | Objective and safety constraints | Initial research objective implemented; commercial trade-offs not signed off | 30-day observed net cash is explicit; experimental contrasts establish incremental effect, not a raw payment label. Long-term penalties/weights need product approval. |
| 2 | Decision/action/result lineage | Offline first-decision contract implemented | Real Alroca exporter must prove tenant membership, provider signature/provenance, reversal reconciliation and decision/execution joins. No invented attribution. |
| 3 | Time-correct feature layer | Offline contract implemented | Every nonmissing feature has source, event time and availability time; sources must be mapped to real systems. Unknown is never zero. |
| 4 | Fixed evaluation and regression boundary | Offline partitions, checksums, guarded loader and adversarial tests implemented | Preregister merchant/time splits, adequate per-currency support and baseline comparisons before model selection. The two-row example is only a contract smoke test. |
| 5 | Calibrated simulation | Existing aggregate validation; fitting pending | Permissioned, representative data; identifiable parameter subset, uncertainty and held-out discrepancy report. Produce a candidate config, never overwrite production automatically. |
| 6 | Action-specific outcome models | Pending | Adequate supported action histories. Start with interpretable observational baselines; grouped future evaluation and probability calibration. First-decision labels do not identify each follow-up action's effect. |
| 7 | Incremental-effect learning | Synthetic paired rollout/trajectory evaluation exists; real experiment pending | Merchant-approved randomized assignment, holdout nonintervention, provider-confirmed outcomes, reversals, observation windows, stop rules and preregistered estimand. |
| 8 | Merchant-specific calibration | Pending | Fit only on training histories; partial pooling/global fallback for sparse merchants, merchant-specific reliability plots and held-out checks. No unsupported per-merchant accuracy promise. |
| 9 | Uncertainty and abstention | Simulator execution guards exist; model gate pending | Calibrated uncertainty, missingness/out-of-distribution checks, explicit review/observe fallback and merchant-readable reasons. Thresholds set using validation, not the final test set. |
| 10 | Sequential timing and action selection | Bounded sequential simulator exists; learned policy pending | Separate full-trajectory contract, valid logging propensities, overlap/effective support, stable financial window and no duplicate attribution. Do not feed repeated 30-day invoice rewards as independent action labels. |
| 11 | Long-term subscription value | Exogenous lifecycle simulation exists; real LTV/retention model pending | Observed 90/180-day windows, censoring, margins/costs and a subscription-level enrollment/estimand; validate survival/retention on future merchants. |
| 12 | Shadow → pilot → controlled automation | CI regression gate exists; serving/shadow/pilot pending | Signed model/config lineage, no-action shadow adapter, quality/drift reports, merchant authorization, limited exposure, independent safety checks, kill switch and tested rollback. |

## Delivery order

1. Implement and test the offline foundation (this increment: workstreams 1–4).
2. Review the source mapping and implement a permissioned, read-only Alroca export.
   Product usage/support sources are currently **not specified**; keep them missing.
3. Fit and compare calibration/outcome baselines (5–6), using no final-test feedback.
4. Run a separately authorized real experiment and merchant calibration (7–8).
5. Introduce uncertainty-aware sequential candidates and long-term value (9–11).
6. Validate shadow behavior, then ask for a bounded pilot before any automation (12).

## Research objective v1

`observed_net_cash_30d_minor = provider_confirmed_gross - confirmed_refunds
- followup_processing_cost - communication_cost - observed_service_fee`.

All values are integer minor units in the episode currency. Fees come from the
exported ledger; this code never computes a new billable commission or applies a
180 TL threshold. Initial-attempt sunk costs are outside the follow-up objective.
Refund timing must follow the preregistered 30-day window; later reversals require
a separately versioned longer-window dataset, not silently changing this target.

This label is an **observed return**, not causal attribution. A customer may pay
without intervention; observe/review episodes can recover money. Net cash can be
negative after refunds/costs. Unknown outcomes remain null and excluded. No
currency totals, default FX rates, synthetic billing or automatic model promotion.

Long-term churn harm, contact fatigue and gross-margin-adjusted objectives cannot
be fabricated from missing fields. Decide and preregister these before optimizing
them. An LLM may draft permitted messages/explanations, but must not own payment
authorization, arithmetic or experiment assignment.
