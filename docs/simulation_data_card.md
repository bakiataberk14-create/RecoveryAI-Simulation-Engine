# Simulation data card — v0.1

**SYNTHETIC / NOT REAL TRANSACTIONS. Not billable. Not real causal evidence.**

Intended use: local operational invariant tests, reproducible model pipelines,
one-decision policy estimator research and leakage tests. Not intended for
training/deploying an autonomous collector without real-world validation.

No live/sandbox provider requests, credentials, card details, names, email
addresses or phone numbers are used. No web server or upload endpoint exists.
Country and currency assignments are fictional, not a statement that a merchant
in each geography can open a Stripe account. Provider safety is a conservative
documented subset, not complete network/regulatory authorization.

Oracle JSONL/Parquet outputs and `simulation.sqlite` contain hidden truth. Only
`training/` should be mounted into a learner's environment. Folder separation and
the feature allowlist prevent accidental inclusion; they are NOT an OS access
control boundary. Use separate storage credentials if oracle data is hosted.

The first implementation supports one intervention per failed invoice. Retention
is a synthetic endpoint proxy, not actual subscription cancellation. Action
effects, refund frequencies, costs and populations are uncalibrated. Missing
provider capability is blocked instead of assumed. `review` does not execute an
unmodeled human intervention. No automatic production calibration or model
deployment exists. See the original README blueprint for planned capabilities.

No model should be selected because it wins only in this engine. Compare across
seeds/scenarios, report failure to beat a constant/heuristic baseline, keep an
untouched market holdout, then validate on consented real observations and
controlled experiments. A positive synthetic effect is never revenue proof.
