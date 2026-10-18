"""Reproducible multi-world comparisons; never tune on the unseen-market world."""
import argparse
from pathlib import Path
import json
from recoveryai_sim.config import Config
from recoveryai_sim.engine import generate
from recoveryai_sim.validation import validate
from recoveryai_sim.evaluation import evaluate, evaluate_oracle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--invoices", type=int, default=1000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    # Fixed experiment design, no reward-based parameter selection.
    for scenario in ("baseline", "saturation", "economic_stress"):
        for seed in (42, 43):
            folder = args.output / f"{scenario}-{seed}"
            manifest = generate(Config(invoices=args.invoices, merchants=min(20,args.invoices), scenario=scenario, seed=seed), folder)
            checks = validate(folder.resolve())
            if not checks["passed"]:
                raise RuntimeError(f"Invariant failure: {scenario}, seed {seed}: {checks['failures']}")
            results.append({"scenario":scenario, "seed":seed, "initial_failure_rate":manifest["counts"]["actions"]/args.invoices,
                            "ips":evaluate(folder, bootstrap=100), "oracle":evaluate_oracle(folder, bootstrap=100)})
    report = {"synthetic_only":True, "design":"3 predetermined worlds x 2 seeds; no tuning, unseen_market untouched", "runs":results}
    (args.output / "research_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Validated {len(results)} simulation runs; report: {args.output / 'research_report.json'}")


if __name__ == "__main__":
    main()
