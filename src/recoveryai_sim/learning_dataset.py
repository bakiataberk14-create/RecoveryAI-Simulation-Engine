"""Fail-closed local dataset preparation; never a provider or training/serving API."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .learning_contract import (CONTRACT, OBJECTIVE, ContractError, fields, reference,
                                require, timestamp, validate_episode, validate_permission)
from .storage import encode

MAX_LINE = 65536
MAX_ROWS = 100000
MAX_BYTES = 64 * 1024 * 1024


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def invalid(_):
        raise ContractError("nonfinite_json")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ContractError("invalid_json") from None


def small_json(path):
    with Path(path).open("rb") as source:
        content = source.read(MAX_LINE + 1)
    require(len(content) <= MAX_LINE, "manifest_too_large")
    return strict_json(content)


def validate_split(spec, permission):
    fields(spec, {"contract", "train_before", "test_from", "heldout_tenants"}, "split_fields")
    require(spec["contract"] == CONTRACT, "split_contract")
    cutoff, test = timestamp(spec["train_before"]), timestamp(spec["test_from"])
    require(cutoff <= test <= timestamp(permission["exported_at"]), "invalid_split_time")
    tenants = spec["heldout_tenants"]
    require(type(tenants) is list and tenants, "heldout_tenants_required")
    for tenant in tenants:
        reference(tenant, "t")
    require(len(set(tenants)) == len(tenants) and set(tenants) < set(permission["tenant_refs"]),
            "heldout_scope_requires_disjoint_training_tenants")
    return cutoff, test, set(tenants)


def prepare_learning(input_path, permission_path, split_path, output, now=None):
    """Invalid input publishes safe diagnostics ONLY, not a partial training set.

    Permission is an operator attestation, not cryptographic proof of merchant
    consent. Real connector/access-control review is a separate release gate.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    now = now or datetime.now(timezone.utc)
    rows, duplicates, errors = [], 0, []
    source_hash = hashlib.sha256()
    try:
        permission = validate_permission(small_json(permission_path), now)
        split_spec = small_json(split_path)
        cutoff, test_from, heldout = validate_split(split_spec, permission)
        decisions, recoveries, customer_tenants, provider_events = {}, set(), {}, {}
        with Path(input_path).open("rb") as source:
            line_number = 0
            total_bytes = 0
            while line := source.readline(MAX_LINE + 1):
                line_number += 1
                source_hash.update(line)
                total_bytes += len(line)
                if len(line) > MAX_LINE or line_number > MAX_ROWS or total_bytes > MAX_BYTES:
                    errors.append({"line": line_number, "code": "input_size_limit"})
                    break
                try:
                    record = strict_json(line)
                    prepared = validate_episode(record, permission)
                    key = record["decision_ref"]
                    canonical = encode(record)
                    if key in decisions:
                        require(decisions[key] == canonical, "conflicting_immutable_decision")
                        duplicates += 1
                        continue
                    recovery = (record["tenant_ref"], record["recovery_ref"])
                    require(recovery not in recoveries, "multiple_decisions_require_trajectory_contract")
                    customer = record["customer_ref"]
                    require(customer not in customer_tenants or customer_tenants[customer] == record["tenant_ref"],
                            "customer_reference_crosses_tenant")
                    provider_ref = record["outcome"]["provider_event_ref"]
                    provider_key = (record["provider"], record["environment"], provider_ref)
                    if provider_ref is not None:
                        require(provider_key not in provider_events, "provider_event_reused")
                    decisions[key] = canonical
                    recoveries.add(recovery)
                    customer_tenants[customer] = record["tenant_ref"]
                    if provider_ref is not None:
                        provider_events[provider_key] = recovery
                    rows.append((record, prepared))
                except ContractError as error:
                    errors.append({"line": line_number, "code": str(error)})
                except (TypeError, KeyError, OverflowError, RecursionError):
                    errors.append({"line": line_number, "code": "invalid_field_type"})
        require(rows or errors, "empty_dataset")
    except ContractError as error:
        errors.append({"line": None, "code": str(error)})
    except (OSError, TypeError, KeyError, OverflowError):
        errors.append({"line": None, "code": "input_or_manifest_unreadable"})
    report = {"contract": CONTRACT, "objective": OBJECTIVE, "passed": not errors,
              "status": "blocked" if errors else "prepared", "accepted_unique_episodes": len(rows),
              "duplicate_identical_rows": duplicates, "rejections": errors, "billable": False,
              "automatic_training": False, "automatic_parameter_update": False,
              "production_authorized": False, "causal_effect_estimated": False}
    if not errors:
        require(now.tzinfo is not None, "timezone_required")
        exclusions, missing = Counter(), Counter()
        partition_counts, currency_counts = Counter(), Counter()
        folder = output / "research"
        folder.mkdir()
        with (folder/"features.jsonl").open("w",encoding="utf-8",newline="\n") as features, \
             (folder/"labels.jsonl").open("w",encoding="utf-8",newline="\n") as labels, \
             (folder/"lineage.jsonl").open("w",encoding="utf-8",newline="\n") as lineage:
            for record, prepared in sorted(rows, key=lambda pair: pair[0]["decision_ref"]):
                sample = hashlib.sha256(encode([record[k] for k in ("tenant_ref","recovery_ref","decision_ref")]).encode()).hexdigest()
                missing.update(prepared["missing_features"])
                decision = timestamp(record["decision_at"])
                if prepared["observed_net_cash_30d_minor"] is None:
                    exclusion, partition = "unresolved_label", "excluded"
                elif record["tenant_ref"] in heldout:
                    partition = "test" if decision >= test_from else "excluded"
                    exclusion = "heldout_before_test"
                elif decision < cutoff and timestamp(record["outcome"]["available_at"]) < cutoff:
                    exclusion, partition = None, "train"
                else:
                    exclusion, partition = "training_time_or_label_embargo", "excluded"
                partition_counts[partition] += 1
                if partition == "excluded":
                    exclusions[exclusion] += 1
                else:
                    currency_counts[f"{partition}:{record['currency']}"] += 1
                features.write(encode({"sample_id": sample, "x": prepared["x"]})+"\n")
                labels.write(encode({"sample_id": sample,"currency": record["currency"],
                    "observed_net_cash_30d_minor":prepared["observed_net_cash_30d_minor"],"causal_effect":None})+"\n")
                lineage.write(encode({"sample_id":sample,"partition":partition,"exclusion":exclusion if partition=="excluded" else None,
                    **{k:record[k] for k in ("tenant_ref","customer_ref","recovery_ref","decision_ref","decision_at",
                        "first_failure_at","policy_version","model_version","selected_action","eligible_actions","propensity","environment","provider")},
                    "feature_provenance": record["features"],"execution":record["execution"],"outcome":record["outcome"]})+"\n")
        report.update(partitions=dict(partition_counts),currencies=dict(currency_counts),exclusions=dict(exclusions),
                      missing_features=dict(missing),evaluation_partition_ready=all(partition_counts[k]>0 for k in ("train","test")),
                      environment=permission["environment"],data_origin=permission["data_origin"],
                      permission_expires_at=permission["expires_at"],retention_until=permission["retention_until"],
                      source_version=permission["source_version"],source_sha256=source_hash.hexdigest(),
                      split_spec=split_spec,
                      permission_sha256=hashlib.sha256(encode(permission).encode()).hexdigest(),
                      split_sha256=hashlib.sha256(encode(split_spec).encode()).hexdigest())
        report["artifact_sha256"] = {}
        for path in sorted(folder.glob("*.jsonl")):
            with path.open("rb") as content:
                report["artifact_sha256"][path.name] = hashlib.file_digest(content,"sha256").hexdigest()
        report["limitations"] = ["Operator-attested permission is not authentication or legal approval.",
            "Provider-confirmed fields are exporter assertions, not independently verified webhook evidence.",
            "Only the first decision per recovery is accepted; no per-action causal attribution or trajectory IS.",
            "Nonempty partitions do not establish statistical support, causal lift, calibration or model readiness.",
            "Pseudonymous lineage remains sensitive and requires restricted access and retention enforcement."]
    (output/"prepare_learning_report.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    return report


def load_learning_partition(root, partition="train", now=None):
    """Explicit research loader: verify artifacts, permissions and leakage boundaries.

    This is not an authenticity signature: the operator controls local artifacts.
    A separate connector authorization boundary is required for real data.
    """
    require(partition in {"train","test"}, "invalid_partition")
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    report = small_json(root/"prepare_learning_report.json")
    require(report.get("contract") == CONTRACT and report.get("passed") is True
            and report.get("production_authorized") is False and report.get("billable") is False, "unapproved_research_artifact")
    require(now < timestamp(report["permission_expires_at"]) and now < timestamp(report["retention_until"]),
            "permission_expired_or_future")
    require(set(report["artifact_sha256"]) == {"features.jsonl","labels.jsonl","lineage.jsonl"}, "artifact_inventory")
    tables = {}
    for name, expected in report["artifact_sha256"].items():
        path = root/"research"/name
        digest = hashlib.sha256()
        items = {}
        with path.open("rb") as source:
            count = 0
            total_bytes = 0
            while line := source.readline(MAX_LINE + 1):
                count += 1
                total_bytes += len(line)
                require(len(line) <= MAX_LINE and count <= MAX_ROWS and total_bytes <= MAX_BYTES, "artifact_size_limit")
                digest.update(line)
                row = strict_json(line)
                require(type(row) is dict and type(row.get("sample_id")) is str, "artifact_row_fields")
                require(row["sample_id"] not in items, "duplicate_artifact_sample")
                items[row["sample_id"]] = row
        require(digest.hexdigest() == expected, "artifact_checksum_mismatch")
        tables[name] = items
    features, labels, lineage = (tables[k] for k in ("features.jsonl","labels.jsonl","lineage.jsonl"))
    require(set(features) == set(labels) == set(lineage), "artifact_join_mismatch")
    require(len(features) == report["accepted_unique_episodes"], "artifact_count_mismatch")
    split = report["split_spec"]
    require(hashlib.sha256(encode(split).encode()).hexdigest() == report["split_sha256"], "split_checksum_mismatch")
    heldout, cutoff, test_from = set(split["heldout_tenants"]), timestamp(split["train_before"]), timestamp(split["test_from"])
    for key in sorted(features):
        row = lineage[key]
        if row["partition"] != partition:
            continue
        decision = timestamp(row["decision_at"])
        if partition == "train":
            require(row["tenant_ref"] not in heldout and decision < cutoff
                    and timestamp(row["outcome"]["available_at"]) < cutoff, "training_partition_leakage")
        else:
            require(row["tenant_ref"] in heldout and decision >= test_from, "test_partition_leakage")
        require(labels[key]["observed_net_cash_30d_minor"] is not None, "unresolved_training_label")
        yield {"sample_id": key, "x":features[key]["x"],
               "observed_net_cash_30d_minor":labels[key]["observed_net_cash_30d_minor"],
               "currency":labels[key]["currency"]}
