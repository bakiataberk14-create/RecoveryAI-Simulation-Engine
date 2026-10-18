from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import pytest
from recoveryai_sim.config import Config, SCENARIOS
from recoveryai_sim.engine import generate
from recoveryai_sim.validation import validate
from recoveryai_sim.views import FEATURES, observable_features, load_training
from recoveryai_sim.evaluation import evaluate, evaluate_oracle
from recoveryai_sim.safety import Context, HARD, eligible_actions, select_action
from recoveryai_sim.causal import potential
from recoveryai_sim.randomness import Noise
from recoveryai_sim.replay import ReplayLedger
from recoveryai_sim.calibration import assess_aggregate


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "world"
    generate(Config(invoices=600, merchants=8, seed=7), root)
    return root


def test_all_invariants(dataset):
    report = validate(dataset)
    assert report["passed"], report
    assert len(report["checks"]) >= 15


def test_repeatable_bytes_independent_of_output_path(dataset, tmp_path):
    other = tmp_path / "again"
    generate(Config(invoices=600, merchants=8, seed=7), other)
    for path in dataset.rglob("*.jsonl"):
        assert path.read_bytes() == (other / path.relative_to(dataset)).read_bytes()
    assert (dataset / "manifest.json").read_bytes() == (other / "manifest.json").read_bytes()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenarios_reconcile(tmp_path, scenario):
    root = tmp_path / scenario
    generate(Config(invoices=180, merchants=5, scenario=scenario), root)
    assert validate(root)["passed"]


@pytest.mark.parametrize("code", sorted(HARD) + ["expired_card", "generic_decline", "not_a_real_code"])
def test_restricted_and_unknown_declines_never_auto_retry(code):
    assert "retry_day3" not in eligible_actions(Context(decline=code))


@pytest.mark.parametrize("change", [{"provider":"adyen"}, {"provider":"iyzico"}, {"provider":"paytr"},
    {"issuing_country":"IN"}, {"connected":False}, {"advice":"unknown"}, {"method_active":False}, {"retries":1}])
def test_retry_context_guards(change):
    assert "retry_day3" not in eligible_actions(replace(Context(), **change))


def test_consent_and_policy_support():
    eligible = eligible_actions(Context(consent=False))
    assert not set(eligible) & {"email", "request_update", "request_authentication"}
    for i in range(100):
        action, p = select_action("randomized", eligible, i/100)
        assert action in eligible and p == 1/len(eligible)


def test_observe_has_no_notifications(tmp_path):
    root = tmp_path / "holdout"
    generate(Config(invoices=300, merchants=3, policy="observe", failure_base=.9), root)
    db = sqlite3.connect(root / "simulation.sqlite")
    assert db.execute("SELECT count(*) FROM communications").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM actions WHERE selected<>'observe'").fetchone()[0] == 0
    db.close()


def test_oracle_never_in_features(dataset):
    for record in load_training(dataset):
        assert set(record["x"]) == FEATURES - {"available_at"}
        assert not {"reliability", "willingness", "recovery_day", "reward_minor"} & set(record["x"])
    assert (dataset / "oracle" / "oracle.jsonl").exists()


def test_unknown_or_future_feature_rejected():
    raw = dict.fromkeys(FEATURES, 0)
    raw["available_at"] = "2025-01-01"
    with pytest.raises(ValueError):
        observable_features(raw, "2024-01-01")
    raw["available_at"] = "2023-01-01"
    raw["latent_reliability"] = .9
    with pytest.raises(ValueError):
        observable_features(raw, "2024-01-01")


def test_censoring_exists(dataset):
    rows = list(load_training(dataset))
    assert any(r["y"]["retention_90d"] is None for r in rows)
    assert any(r["y"]["retention_90d"] is not None for r in rows)


def test_potential_outcomes_share_noise_and_allow_negative_effect():
    cfg = Config(scenario="saturation")
    negative = 0
    for i in range(200):
        args = (Noise(42), str(i))
        base = potential(*args, "observe", .8, .9, .8, 10000, cfg)
        email = potential(*args, "email", .8, .9, .8, 10000, cfg)
        negative += email.net < base.net
        assert base == potential(*args, "observe", .8, .9, .8, 10000, cfg)
    assert negative > 0


def test_duplicate_and_out_of_order_replay():
    ledger = ReplayLedger("syn_tenant_1")
    event = dict(id="syn_event_1", tenant_id="syn_tenant_1", invoice_id="syn_invoice_1",
                 synthetic=1, event_type="sim.refund", occurred_at="2024-01-02")
    ledger.apply(event)
    assert ledger.apply(event) is False
    payment = {**event, "id":"syn_event_2", "event_type":"sim.payment_succeeded", "occurred_at":"2024-01-01"}
    ledger.apply(payment)
    assert ledger.settled == set()
    with pytest.raises(ValueError):
        ledger.apply({**event, "tenant_id":"syn_tenant_2"})
    with pytest.raises(ValueError):
        ledger.apply({**event, "event_type":"sim.payment_succeeded"})


def test_validation_catches_tenant_corruption(dataset):
    db = sqlite3.connect(dataset / "simulation.sqlite")
    db.execute("UPDATE customers SET tenant_id='other' WHERE id=(SELECT id FROM customers LIMIT 1)")
    db.commit()
    db.close()
    assert not validate(dataset)["passed"]


def test_overwrite_rejected(dataset):
    with pytest.raises(FileExistsError):
        generate(Config(invoices=1, merchants=1), dataset)


@pytest.mark.parametrize("values", [{"seed":-1}, {"failure_base":float('nan')}, {"months":0},
    {"merchants":101,"invoices":100}, {"invoices":1.0}, {"max_retries":5}, {"start":"2024-01-01"}, {"scenario":"unknown"}])
def test_invalid_config(values):
    with pytest.raises(ValueError):
        Config(**values)


def test_ope_never_sums_currencies(dataset):
    result = evaluate(dataset, bootstrap=30)
    assert len(result["currencies"]) > 1
    assert "total_revenue" not in result
    assert all(v["effective_sample_size"] >= 0 for v in result["currencies"].values())


def test_deterministic_logging_blocks_ope(tmp_path):
    root = tmp_path / "deterministic"
    generate(Config(invoices=100, merchants=2, policy="observe", failure_base=.9), root)
    assert all(v["status"] == "blocked" for v in evaluate(root)["currencies"].values())


def test_calibration_requires_permission_and_denominator():
    record = dict(permission_granted=True, tenant_ref="agg_1", population="synthetic_contract_fixture",
                  period_start="2024-01-01T00:00:00+00:00", period_end="2024-02-01T00:00:00+00:00",
                  initial_attempts=100, initial_failures=10, metric_definition="failed_initial_attempts/initial_attempts", source_version="fixture-v1")
    assert assess_aggregate(record)["rate"] == .1
    for changes in ({"permission_granted":False}, {"metric_definition":"recovered/retries"},
                    {"initial_failures":101}, {"email":"never-import@example.invalid"},
                    {"population":"never-import@example.invalid"}, {"tenant_ref":"agg_me@example.invalid"}):
        with pytest.raises(ValueError):
            assess_aggregate({**record, **changes})


def test_parquet_roundtrip(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    root = tmp_path / "parquet"
    generate(Config(invoices=90, merchants=2), root, parquet=True)
    table = pq.read_table(root / "operational" / "invoices.parquet")
    assert table.num_rows == 90
    assert str(table.schema.field("amount_due").type) == "int64"


def test_oracle_baseline_zero_increment(dataset):
    report = evaluate_oracle(dataset, bootstrap=20)
    assert report["oracle_only"] is True
    assert all(r["mean_incremental_minor"] == 0 for r in report["results"] if r["policy"] == "observe")


def test_parameter_overrides_are_validated(tmp_path):
    config = Config(invoices=12, merchants=1, parameters={"communication_cost_minor":17})
    assert config.parameters.communication_cost_minor == 17
    with pytest.raises(ValueError):
        Config(parameters={"processing_cost_minor":1.5})
    with pytest.raises(ValueError):
        Config(parameters={"payment_spread_days":90})


def test_tiny_short_world_no_future_events(tmp_path):
    root = tmp_path / "short"
    generate(Config(invoices=1, merchants=1, months=1), root, parquet=True)
    assert validate(root)["passed"]


def test_delivery_outage_zero_observed_engagement(tmp_path):
    root = tmp_path / "outage"
    generate(Config(invoices=500, merchants=3, failure_base=.9, delivery_probability=0), root)
    db = sqlite3.connect(root / "simulation.sqlite")
    assert db.execute("SELECT count(*) FROM communications").fetchone()[0] > 0
    assert db.execute("SELECT count(*) FROM communications WHERE delivered=1 OR opened=1 OR clicked=1").fetchone()[0] == 0
    db.close()


def test_cash_refund_and_oracle_reward_agree_when_mature(tmp_path):
    root = tmp_path / "refund"
    generate(Config(invoices=400, merchants=4, failure_base=.8, refund_probability=1), root)
    db = sqlite3.connect(root / "simulation.sqlite")
    assert db.execute("SELECT count(*) FROM invoices WHERE refund_amount>0").fetchone()[0] > 0
    mismatches = db.execute("""SELECT count(*) FROM outcomes o JOIN actions a ON a.id=o.action_id
        JOIN oracle p ON p.action_id=a.id AND p.action=a.selected
        WHERE o.window_complete=1 AND o.net_revenue<>p.reward_minor""").fetchone()[0]
    assert mismatches == 0
    db.close()


def test_scenario_shift_not_cosmetic(tmp_path):
    failures = []
    for scenario in ("baseline", "economic_stress"):
        root = tmp_path / scenario
        generate(Config(invoices=1000, merchants=10, scenario=scenario), root)
        db = sqlite3.connect(root / "simulation.sqlite")
        failures.append(db.execute("SELECT count(*) FROM actions").fetchone()[0])
        db.close()
    assert failures[1] > failures[0] + 100


def test_snapshot_and_events_are_immutable(dataset):
    db = sqlite3.connect(dataset / "simulation.sqlite")
    for query in ("UPDATE actions SET features_json='{}'", "DELETE FROM events", "UPDATE oracle SET reward_minor=999"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(query)
        db.rollback()
    db.close()


def test_uniform_does_not_round_up_to_one(monkeypatch):
    class MaxHash:
        def digest(self):
            return b'\xff' * 32
    monkeypatch.setattr("recoveryai_sim.randomness.hashlib.sha256", lambda *args: MaxHash())
    assert 0 <= Noise(1).uniform("max") < 1


def test_hard_decline_recovery_uses_fresh_method(tmp_path):
    root = tmp_path / "expiry"
    generate(Config(invoices=600, merchants=4, scenario="expired_wave", failure_base=.8), root)
    db = sqlite3.connect(root / "simulation.sqlite")
    pairs = db.execute("""SELECT first.method_id,second.method_id FROM attempts first JOIN attempts second
        ON first.invoice_id=second.invoice_id WHERE first.number=1 AND first.decline='expired_card'
        AND second.result='succeeded'""").fetchall()
    assert pairs and all(old != new for old, new in pairs)
    db.close()
