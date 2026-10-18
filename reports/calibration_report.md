# Calibration and model evidence — v0.1

No real merchant dataset or externally matched numeric benchmark was used.
Payment behavior, causal effects, costs, populations and stress intensities are
explicit synthetic assumptions/hypotheses. See the source registry and assumption
register. No empirical market calibration or real recovery lift is claimed.

The aggregate calibration adapter validates permission, population/source codes,
period and exact denominator, then returns a descriptive rate and Wilson interval.
It does not infer all latent parameters or update configs automatically.

On the validated 100K baseline run, the grouped temporal split used 4,575 mature
training decisions and 633 test decisions from disjoint merchants. Brier scores
(lower is better) were:

| Predictor | Test Brier |
|---|---:|
| Constant training prevalence | 0.218120 |
| Scaled logistic regression | 0.216655 |
| Histogram gradient boosting | 0.218794 |

The logistic improvement is small and has no reported significance test. Gradient
boosting did not beat the constant baseline on this metric. The earlier 10K smoke
run also showed that more complex models can perform worse. These results are
pipeline checks within an invented world, not a reason to deploy a model.

IPS and oracle comparisons report values separately for AUD/CAD/EUR/GBP/TRY/USD;
there is no cross-currency financial total. Merchant-cluster bootstrap intervals
and support diagnostics accompany the estimates. Oracle comparisons use known
potential outcomes only in the explicit oracle evaluator. Both estimators concern
one decision on a logged failed-invoice context, not a whole longitudinal policy.

Six predeclared robustness runs exercised baseline, saturation and economic stress
at seeds42/43. The unseen-market scenario was not used for model selection. Formal
scenario-holdout model evaluation, doubly robust estimation and calibrated
hierarchical merchant models remain future work.
