import argparse
from dataclasses import asdict
import json
from pathlib import Path
from .config import Config, SCENARIOS, POLICIES
from .engine import generate
from .storage import encode


def main(argv=None):
    parser = argparse.ArgumentParser(description="RecoveryAI: SYNTHETIC / NOT REAL TRANSACTIONS")
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate")
    gen.add_argument("--config", type=Path)
    gen.add_argument("--invoices", type=int)
    gen.add_argument("--merchants", type=int)
    gen.add_argument("--seed", type=int)
    gen.add_argument("--scenario", choices=SCENARIOS)
    gen.add_argument("--policy", choices=POLICIES)
    gen.add_argument("--output", type=Path, required=True)
    gen.add_argument("--parquet", action="store_true")
    for command in ("validate", "evaluate", "train", "oracle-evaluate"):
        sub = commands.add_parser(command)
        sub.add_argument("--input", type=Path, required=True)
        if command == "evaluate":
            sub.add_argument("--target-policy", choices=[p for p in POLICIES if p != "randomized"], default="rule_based")
    calibrate = commands.add_parser("assess-calibration")
    calibrate.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "generate":
        cfg = asdict(Config.load(args.config)) if args.config else {}
        for key in ("invoices", "merchants", "seed", "scenario", "policy"):
            if getattr(args, key) is not None:
                cfg[key] = getattr(args, key)
        result = generate(Config(**cfg), args.output, args.parquet)
    elif args.command == "validate":
        from .validation import validate
        result = validate(args.input.resolve())
    elif args.command == "evaluate":
        from .evaluation import evaluate
        result = evaluate(args.input, args.target_policy)
    elif args.command == "train":
        from .evaluation import train_baselines
        result = train_baselines(args.input)
    elif args.command == "oracle-evaluate":
        from .evaluation import evaluate_oracle
        result = evaluate_oracle(args.input)
    else:
        from .calibration import assess_aggregate
        result = assess_aggregate(json.loads(args.input.read_text(encoding="utf-8")))
    if args.command in ("validate", "evaluate", "train", "oracle-evaluate"):
        (args.input / f"{args.command}_report.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if result.get("passed") is False or result.get("status") == "blocked" else 0
