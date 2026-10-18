"""Currency-separated one-step OPE with merchant-cluster bootstrap diagnostics."""
from collections import defaultdict
import random
from statistics import mean
from .safety import select_action
from .views import load_training
import json


def sequential_estimator_block(root):
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    if manifest["config"]["schema_version"]=="2":
        return {"status":"blocked","synthetic_only":True,"reason":"Sequential trajectories require sequential policy evaluation; one-step IPS/oracle values are not identified by this estimator."}


def evaluate(root, target_policy="rule_based", seed=42, bootstrap=200):
    blocked=sequential_estimator_block(root)
    if blocked:
        return blocked
    groups = defaultdict(list)
    for row in load_training(root):
        if row["reward_30d_minor"] is not None:
            groups[row["x"]["currency"]].append(row)
    report = {"synthetic_only": True, "estimand": "30-day one-decision policy value on logged failed-invoice contexts",
              "target_policy": target_policy, "currencies": {},
              "limitations": "Not a longitudinal policy rollout or real causal evidence; review has zero modeled intervention."}
    for currency, rows in groups.items():
        if any(r["policy"]["logging_policy"] != "randomized" for r in rows):
            report["currencies"][currency] = {"status": "blocked", "reason": "Logging policy lacks known full support"}
            continue
        clusters, weights = defaultdict(list), []
        for row in rows:
            selected = select_action(target_policy, tuple(row["policy"]["eligible"]), 0)[0]
            propensity = row["policy"]["propensity"]
            if not 0 < propensity <= 1:
                raise ValueError("Invalid logged propensity")
            weight = (row["policy"]["selected"] == selected) / propensity
            weights.append(weight)
            clusters[row["metadata"]["merchant_id"]].append(weight * row["reward_30d_minor"])
        values = [v for cluster in clusters.values() for v in cluster]
        rng = random.Random(seed)
        keys = sorted(clusters)
        estimates = []
        if len(keys) >= 2 and sum(weights) > 0:
            for _ in range(bootstrap):
                sample = [v for _ in keys for v in clusters[rng.choice(keys)]]
                estimates.append(mean(sample))
            estimates.sort()
        ess = sum(weights)**2 / sum(w*w for w in weights) if any(weights) else 0
        report["currencies"][currency] = {"n": len(rows), "merchant_clusters": len(keys), "effective_sample_size": ess,
            "ips_value_minor_per_failed_invoice": mean(values), "mean_importance_weight": mean(weights),
            "ci95_merchant_bootstrap": [estimates[int(.025*len(estimates))], estimates[min(len(estimates)-1,int(.975*len(estimates)))]] if estimates else None,
            "status": "low_support" if ess < 30 or len(keys) < 5 else "simulation_estimate"}
    return report


def train_baselines(root):
    import numpy as np
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import brier_score_loss, average_precision_score, roc_auc_score
    rows = [r for r in load_training(root) if r["y"]["recovered_30d"] is not None]
    if not rows:
        return {"status": "blocked", "reason": "No mature labels"}
    times = sorted(r["metadata"]["decision_at"] for r in rows)
    cutoff = times[int(.7 * (len(times)-1))]
    # Group holdout AND temporal embargo: labels cannot cross training cutoff.
    holdout = lambda r: int(r["metadata"]["merchant_id"].rsplit("_", 1)[1]) % 5 == 0
    train = [r for r in rows if not holdout(r) and r["metadata"]["observed_until"] < cutoff]
    test = [r for r in rows if holdout(r) and r["metadata"]["decision_at"] >= cutoff]
    if min(len(train), len(test)) < 20 or len({r["y"]["recovered_30d"] for r in train}) < 2:
        return {"status": "blocked", "reason": "Insufficient mature grouped temporal split", "train": len(train), "test": len(test)}
    vectorizer = DictVectorizer(sparse=False)
    x_train = vectorizer.fit_transform([r["x"] for r in train])
    x_test = vectorizer.transform([r["x"] for r in test])
    y_train = np.array([r["y"]["recovered_30d"] for r in train])
    y_test = np.array([r["y"]["recovered_30d"] for r in test])
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    models = {"logistic": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=42)),
              "hist_gradient_boosting": HistGradientBoostingClassifier(max_iter=60, max_leaf_nodes=15, random_state=42)}
    predictions = {"constant_train_rate": np.full(len(test), y_train.mean())}
    for name, model in models.items():
        model.fit(x_train, y_train)
        predictions[name] = model.predict_proba(x_test)[:, 1]
    results = {}
    for name, prob in predictions.items():
        bins = []
        for lo in range(10):
            mask = (prob >= lo/10) & (prob < (lo+1)/10 if lo < 9 else prob <= 1)
            if mask.any():
                bins.append({"count": int(mask.sum()), "predicted": float(prob[mask].mean()), "observed": float(y_test[mask].mean())})
        results[name] = {"brier": float(brier_score_loss(y_test, prob)),
                         "pr_auc": float(average_precision_score(y_test, prob)) if y_test.any() else None,
                         "roc_auc": float(roc_auc_score(y_test, prob)) if len(set(y_test)) == 2 else None,
                         "calibration_bins": bins}
    return {"synthetic_only": True, "target": "observed recovery within 30 days under logging policy",
            "train": len(train), "test": len(test), "cutoff": cutoff, "split": "disjoint merchants + time + label maturity embargo",
            "models": results, "warning": "Predictive performance is not treatment uplift or evidence for live policy deployment."}


def evaluate_oracle(root, seed=42, bootstrap=200):
    """Explicit oracle-only path. Paired current-context value, not training input."""
    blocked=sequential_estimator_block(root)
    if blocked:
        return blocked
    import sqlite3
    import json
    db = sqlite3.connect(f"{(root.resolve() / 'simulation.sqlite').as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    groups = defaultdict(lambda: defaultdict(list))
    try:
        for row in db.execute("""SELECT a.id,a.eligible_json,c.merchant_id,o.currency FROM actions a
            JOIN outcomes o ON o.action_id=a.id AND o.tenant_id=a.tenant_id
            JOIN customers c ON c.id=a.customer_id AND c.tenant_id=a.tenant_id WHERE o.window_complete=1"""):
            rewards = {p[0]: p[1] for p in db.execute("SELECT action,reward_minor FROM oracle WHERE action_id=?", (row["id"],))}
            for policy in ("observe", "fixed_retry", "rule_based"):
                chosen = select_action(policy, json.loads(row["eligible_json"]), 0)[0]
                groups[(row["currency"], policy)][row["merchant_id"]].append(rewards[chosen]-rewards["observe"])
    finally:
        db.close()
    result = []
    for (currency, policy), clusters in sorted(groups.items()):
        keys, rng, draws = sorted(clusters), random.Random(seed), []
        values = [v for cluster in clusters.values() for v in cluster]
        if len(keys) >= 2:
            for _ in range(bootstrap):
                draws.append(mean(v for _ in keys for v in clusters[rng.choice(keys)]))
            draws.sort()
        result.append({"currency":currency, "policy":policy, "failed_invoices":len(values),
                       "merchant_clusters":len(keys), "mean_incremental_minor":mean(values),
                       "ci95_merchant_bootstrap":[draws[int(.025*len(draws))],draws[min(len(draws)-1,int(.975*len(draws)))]] if draws else None})
    return {"oracle_only":True, "synthetic_only":True, "results":result,
            "warning":"Known simulator potential outcomes on current logged contexts. Not real uplift or full longitudinal policy value."}
