from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import pytest

from recoveryai_sim.learning_contract import ContractError, FEATURE_SOURCES, validate_episode, validate_permission
from recoveryai_sim.learning_dataset import prepare_learning, load_learning_partition
from tools.create_learning_example import example, ref

NOW = datetime(2026,10,18,tzinfo=timezone.utc)


@pytest.fixture
def data():
    return example()


def prepare(tmp_path,data,raw=None):
    permission,split,records = data
    for name,value in (("permission",permission),("split",split)):
        (tmp_path/f"{name}.json").write_text(json.dumps(value),encoding="utf-8")
    (tmp_path/"rows.jsonl").write_text(raw if raw is not None else "\n".join(json.dumps(r) for r in records)+"\n",encoding="utf-8")
    return prepare_learning(tmp_path/"rows.jsonl",tmp_path/"permission.json",tmp_path/"split.json",tmp_path/"out",now=NOW)


def test_prepares_disjoint_temporal_features_and_labels_without_automatic_training(tmp_path,data):
    result = prepare(tmp_path,data)
    assert result["passed"] and result["evaluation_partition_ready"]
    assert result["partitions"] == {"test":1,"train":1}
    assert result["currencies"] == {"test:TRY":1,"train:TRY":1}
    assert not result["production_authorized"] and not result["automatic_training"]
    features = [json.loads(line) for line in (tmp_path/"out/research/features.jsonl").read_text().splitlines()]
    labels = [json.loads(line) for line in (tmp_path/"out/research/labels.jsonl").read_text().splitlines()]
    assert all(set(row)=={"sample_id","x"} for row in features)
    assert all(row["observed_net_cash_30d_minor"]==8495 and row["causal_effect"] is None for row in labels)
    assert all(row["x"]["estimated_ltv_minor"] is None for row in features)


def test_permission_required_unexpired_and_nonfuture(data):
    permission,_,_ = data
    assert validate_permission(permission,NOW)
    for patch in ({"permission_granted":False},{"permission_granted":1},{"expires_at":"2026-01-01T00:00:00Z"},
                  {"retention_until":"2026-01-01T00:00:00Z"},{"exported_at":"2099-01-01T00:00:00Z"},
                  {"purpose":"billing"},{"data_origin":"merchant_export"}):
        with pytest.raises(ContractError):
            validate_permission({**permission,**patch},NOW)


@pytest.mark.parametrize("field,value",[("customer_email","private@example.invalid"),("provider_secret","SECRET_CANARY"),
    ("raw_payload",{"sensitive":"SECRET_CANARY"}),("customer_name","PERSON_CANARY")])
def test_unknown_pii_or_secret_field_blocks_entire_dataset_without_raw_quarantine(tmp_path,data,field,value):
    data[2][1][field] = value
    result = prepare(tmp_path,data)
    assert not result["passed"] and result["status"]=="blocked"
    assert not (tmp_path/"out/research").exists()
    text = (tmp_path/"out/prepare_learning_report.json").read_text()
    assert "CANARY" not in text and "private@" not in text


@pytest.mark.parametrize("patch",[{"tenant_ref":ref("t","unauthorized")},{"environment":"live"},
    {"customer_ref":"person@example.invalid"},{"decision_at":"2025-01-01T00:00:00Z"},
    {"amount_minor":True},{"amount_minor":-1},{"currency":"XXX"},{"attempt_count":False},
    {"propensity":0},{"propensity":True},{"selected_action":"native_retry"},
    {"eligible_actions":["observe","observe"]},{"provider":"unknown"},{"policy_version":"https://secret.invalid"}])
def test_episode_input_rejects_invalid_or_unsafe_values(data,patch):
    with pytest.raises(ContractError):
        validate_episode({**data[2][0],**patch},data[0])


def feature(value,source="product",occurred="2026-01-01T00:00:00Z",available="2026-01-01T00:00:00Z"):
    return dict(value=value,source=source,occurred_at=occurred,available_at=available)


@pytest.mark.parametrize("item",[feature(2,available="2026-01-02T00:00:00Z"),feature(2,source="finance"),
    feature(2,occurred="2025-01-01T00:00:00Z",available="2025-01-01T00:00:00Z"),feature(8),feature(True)])
def test_future_stale_wrong_source_and_invalid_features_are_rejected(data,item):
    data[2][0]["features"]["customer_active_days_7d"] = item
    with pytest.raises(ContractError):
        validate_episode(data[2][0],data[0])


def test_missing_features_stay_unknown_and_window_consistency_is_checked(data):
    row = data[2][0]
    prepared = validate_episode(row,data[0])
    assert set(prepared["missing_features"]) == set(FEATURE_SOURCES)
    row["features"]["customer_active_days_7d"] = feature(5)
    row["features"]["customer_active_days_30d"] = feature(3)
    with pytest.raises(ContractError,match="activity_window_mismatch"):
        validate_episode(row,data[0])


def test_unresolved_is_not_a_failed_or_zero_reward_label(tmp_path,data):
    row = data[2][0]
    row["outcome"].update(status="unresolved",provider_event_ref=None,paid_at=None,gross_recovered_minor=None,refund_minor=None)
    result = prepare(tmp_path,data)
    assert result["passed"] and not result["evaluation_partition_ready"]
    assert result["exclusions"]["unresolved_label"] == 1
    row["outcome"]["gross_recovered_minor"] = 0
    with pytest.raises(ContractError,match="fabricated_label"):
        validate_episode(row,data[0])


@pytest.mark.parametrize("patch",[{"available_at":"2026-01-15T00:00:00Z"},{"gross_recovered_minor":10001},
    {"refund_minor":10001},{"processing_cost_minor":-1},{"provider_event_ref":None},
    {"paid_at":"2026-03-01T00:00:00Z"},{"window_end":"2026-02-01T00:00:00Z"}])
def test_outcome_evidence_window_and_financial_invariants(data,patch):
    data[2][0]["outcome"].update(patch)
    with pytest.raises(ContractError):
        validate_episode(data[2][0],data[0])


def test_refund_and_costs_can_produce_negative_observed_net_cash(data):
    data[2][0]["outcome"]["refund_minor"] = 10000
    assert validate_episode(data[2][0],data[0])["observed_net_cash_30d_minor"] == -1505


def test_holdout_cannot_have_execution_or_delivery(data):
    data[2][0]["execution"].update(status="executed",execution_ref=ref("x","dispatch"),executed_at="2026-01-02T00:00:00Z")
    with pytest.raises(ContractError,match="holdout_action_leakage"):
        validate_episode(data[2][0],data[0])


def test_contact_requires_known_consent_and_delivery_evidence(data):
    row = data[2][0]
    row.update(selected_action="email",eligible_actions=["observe","email"])
    row["execution"].update(status="executed",execution_ref=ref("x","dispatch"),executed_at="2026-01-02T00:00:00Z")
    with pytest.raises(ContractError,match="consent"):
        validate_episode(row,data[0])
    row["features"]["consent"] = feature(True,source="communications")
    assert validate_episode(row,data[0])
    row["execution"]["delivery_status"] = "delivered"
    with pytest.raises(ContractError,match="delivery_evidence"):
        validate_episode(row,data[0])


def test_turkish_provider_native_retry_support_not_invented(data):
    data[2][0].update(selected_action="retry_day3",eligible_actions=["observe","retry_day3"])
    with pytest.raises(ContractError,match="unsupported_provider_retry"):
        validate_episode(data[2][0],data[0])


def test_exact_duplicate_is_deduplicated_but_conflicting_snapshot_blocks(tmp_path,data):
    data[2].append(deepcopy(data[2][0]))
    report = prepare(tmp_path,data)
    assert report["accepted_unique_episodes"] == 2 and report["duplicate_identical_rows"] == 1


@pytest.mark.parametrize("kind",["snapshot","recovery","customer_tenant","provider_event"])
def test_conflicting_identity_or_event_relationships_block_whole_dataset(tmp_path,data,kind):
    first,second = data[2]
    if kind=="snapshot":
        second["decision_ref"] = first["decision_ref"]
    elif kind=="recovery":
        second["tenant_ref"] = first["tenant_ref"]
        second["recovery_ref"] = first["recovery_ref"]
    elif kind=="customer_tenant":
        second["customer_ref"] = first["customer_ref"]
    else:
        second["outcome"]["provider_event_ref"] = first["outcome"]["provider_event_ref"]
    assert not prepare(tmp_path,data)["passed"]
    assert not (tmp_path/"out/research").exists()


def test_training_labels_crossing_cutoff_are_embargoed(tmp_path,data):
    data[2][0]["outcome"]["available_at"] = "2026-03-02T00:00:00Z"
    result = prepare(tmp_path,data)
    assert result["exclusions"]["training_time_or_label_embargo"] == 1
    assert not result["evaluation_partition_ready"]


def test_mixed_currencies_remain_separate(tmp_path,data):
    data[2][1]["currency"] = "USD"
    report = prepare(tmp_path,data)
    assert report["currencies"] == {"train:TRY":1,"test:USD":1}
    assert "total_reward" not in report


@pytest.mark.parametrize("raw",['{"x":1,"x":2}', '{"secret":"SECRET_CANARY", "x":NaN}',
    "NOT_JSON_SECRET_CANARY", "["*1000, "x"*65537, ""],
    ids=["duplicate-key","nonfinite","malformed","deep-nesting","oversized","empty"])
def test_malformed_oversized_empty_and_ambiguous_json_fail_closed(tmp_path,data,raw):
    result = prepare(tmp_path,data,raw)
    assert not result["passed"]
    assert "CANARY" not in json.dumps(result)
    assert not (tmp_path/"out/research").exists()


def test_split_must_have_separate_heldout_merchants(tmp_path,data):
    data[1]["heldout_tenants"] = data[0]["tenant_refs"]
    assert not prepare(tmp_path,data)["passed"]


def test_research_exports_do_not_enter_existing_synthetic_training_loader(tmp_path,data):
    from recoveryai_sim.views import load_training
    prepare(tmp_path,data)
    with pytest.raises(FileNotFoundError):
        list(load_training(tmp_path/"out"))


def test_refuses_overwriting_existing_artifacts(tmp_path,data):
    prepare(tmp_path,data)
    with pytest.raises(FileExistsError):
        prepare(tmp_path,data)


def test_loader_requires_explicit_partition_and_separates_merchant_features(tmp_path,data):
    prepare(tmp_path,data)
    train = list(load_learning_partition(tmp_path/"out","train",now=NOW))
    test = list(load_learning_partition(tmp_path/"out","test",now=NOW))
    assert len(train) == len(test) == 1
    assert train[0]["sample_id"] != test[0]["sample_id"]
    assert set(train[0]) == {"sample_id","x","observed_net_cash_30d_minor","currency"}
    with pytest.raises(ContractError):
        list(load_learning_partition(tmp_path/"out","excluded",now=NOW))


def test_loader_rechecks_expiry_before_use(tmp_path,data):
    data[0]["expires_at"] = "2026-10-19T00:00:00Z"
    prepare(tmp_path,data)
    with pytest.raises(ContractError,match="expired"):
        list(load_learning_partition(tmp_path/"out",now=datetime(2026,10,20,tzinfo=timezone.utc)))


@pytest.mark.parametrize("name",["features.jsonl","labels.jsonl","lineage.jsonl"])
def test_loader_rejects_tampered_artifacts(tmp_path,data,name):
    prepare(tmp_path,data)
    path = tmp_path/"out/research"/name
    path.write_text(path.read_text()+"\n",encoding="utf-8")
    with pytest.raises(ContractError):
        list(load_learning_partition(tmp_path/"out",now=NOW))


def test_provider_unpaid_is_explicit_not_inferred_from_missing_payment(data):
    data[2][0]["outcome"].update(status="provider_confirmed_unpaid",paid_at=None,gross_recovered_minor=0,refund_minor=0)
    assert validate_episode(data[2][0],data[0])["observed_net_cash_30d_minor"] == -1505


def test_same_reference_in_different_decisions_cannot_hide_conflict(tmp_path,data):
    row = deepcopy(data[2][0])
    row["outcome"]["refund_minor"] = 1
    data[2].append(row)
    report = prepare(tmp_path,data)
    assert report["rejections"][0]["code"] == "conflicting_immutable_decision"


def test_json_objects_and_values_with_wrong_types_do_not_echo_data(tmp_path,data):
    data[2][0]["currency"] = {"secret":"SECRET_CANARY"}
    report = prepare(tmp_path,data)
    assert not report["passed"] and "CANARY" not in json.dumps(report)


def test_loader_still_rejects_heldout_in_training_after_rehashed_metadata(tmp_path,data):
    prepare(tmp_path,data)
    root = tmp_path/"out"
    path = root/"research/lineage.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["partition"] = "train"
    path.write_text("\n".join(json.dumps(r) for r in rows)+"\n",encoding="utf-8")
    report_path = root/"prepare_learning_report.json"
    report = json.loads(report_path.read_text())
    report["artifact_sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report),encoding="utf-8")
    with pytest.raises(ContractError,match="partition_leakage"):
        list(load_learning_partition(root,now=NOW))


def test_cli_blocked_exit_and_safe_diagnostics(tmp_path,data,capsys):
    from recoveryai_sim.cli import main
    data[2][0]["provider_secret"] = "SECRET_CANARY"
    prepare(tmp_path,data)
    status = main(["prepare-learning","--input",str(tmp_path/"rows.jsonl"),
        "--permission",str(tmp_path/"permission.json"),"--split",str(tmp_path/"split.json"),"--output",str(tmp_path/"cli")])
    assert status == 1 and "CANARY" not in capsys.readouterr().out
    assert not (tmp_path/"cli/research").exists()


def test_loader_rejects_blocked_report(tmp_path,data):
    data[0]["permission_granted"] = False
    prepare(tmp_path,data)
    with pytest.raises(ContractError,match="unapproved"):
        list(load_learning_partition(tmp_path/"out",now=NOW))


def test_dataset_preparation_does_not_modify_source_files(tmp_path,data):
    prepare(tmp_path,data)
    for name,value in (("permission",data[0]),("split",data[1])):
        assert json.loads((tmp_path/f"{name}.json").read_text()) == value
    assert [json.loads(line) for line in (tmp_path/"rows.jsonl").read_text().splitlines()] == data[2]
