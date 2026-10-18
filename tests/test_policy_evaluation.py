from collections import Counter
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
import math
import sqlite3
import pytest

from recoveryai_sim.config import Config
from recoveryai_sim.engine import generate,stamp
from recoveryai_sim.storage import Store,encode
from recoveryai_sim.trajectory import causal_episodes
from recoveryai_sim.policy_comparison import compare_policies,paired_currency_report
from recoveryai_sim.policy_statistics import contrast_summary
from recoveryai_sim.trajectory_evaluation import trajectory_weight,support,evaluate_trajectories


@pytest.fixture
def ledger(tmp_path):
    stores=[]
    def create(paid_day=3,refund_day=None,unknown=False,config=None):
        cfg=config or Config(invoices=1,merchants=1,months=2,schema_version="2")
        store=Store(tmp_path/f"ledger-{len(stores)}.sqlite","2")
        stores.append(store)
        t=datetime.fromisoformat(cfg.start).astimezone(timezone.utc)
        store.insert("merchants",id="syn_m",tenant_id="syn_t",country="TR",currency="TRY",industry="b2b_saas",provider="stripe")
        store.insert("customers",id="syn_c",tenant_id="syn_t",merchant_id="syn_m",signup_at=stamp(t),consent=1,engagement=.5)
        store.insert("subscriptions",id="syn_s",tenant_id="syn_t",customer_id="syn_c",interval_months=1,amount_minor=1000,currency="TRY",start_at=stamp(t),status="active")
        store.insert("payment_methods",id="syn_pm",tenant_id="syn_t",customer_id="syn_c",method_type="card",issuing_country="TR",status="active")
        paid=paid_day is not None and not unknown
        store.insert("invoices",id="syn_i",tenant_id="syn_t",subscription_id="syn_s",currency="TRY",amount_due=1000,
            amount_paid=1000 if paid else 0,amount_remaining=0 if paid else 1000,refund_amount=1000 if refund_day is not None else 0,
            created_at=stamp(t),paid_at=stamp(t+timedelta(days=paid_day)) if paid else None,
            status="refunded" if refund_day is not None else "paid" if paid else "open")
        store.insert("attempts",id="syn_a1",tenant_id="syn_t",invoice_id="syn_i",method_id="syn_pm",occurred_at=stamp(t),number=1,result="failed",decline="insufficient_funds",processing_cost=99)
        events=[("payment_failed",0,{"attempt_number":1})]
        if paid or unknown:
            store.insert("attempts",id="syn_a2",tenant_id="syn_t",invoice_id="syn_i",method_id="syn_pm",occurred_at=stamp(t+timedelta(days=paid_day or 2)),number=2,
                result="unknown" if unknown else "succeeded",decline=None,processing_cost=5)
        if paid:
            events.append(("payment_succeeded",paid_day,{}))
        if refund_day is not None:
            events.append(("refund",refund_day,{}))
        for index,(kind,day,payload) in enumerate(events):
            event=f"syn_e{index}"
            at=stamp(t+timedelta(days=day))
            store.insert("events",id=event,tenant_id="syn_t",invoice_id="syn_i",occurred_at=at,event_type=f"sim.{kind}",payload_json=encode(payload))
            store.insert("deliveries",id=f"syn_d{index}",tenant_id="syn_t",event_id=event,delivered_at=at)
            store.insert("observations",id=f"syn_o{index}",tenant_id="syn_t",invoice_id="syn_i",event_id=event,occurred_at=at,available_at=at,event_type=f"sim.{kind}",applied=1,payload_json=encode(payload))
        return store.db,cfg
    yield create
    for store in stores:
        store.db.close()


def test_native_payment_without_any_decision_is_included(ledger):
    db,cfg=ledger()
    rows=list(causal_episodes(db,cfg))
    assert len(rows)==1
    row=rows[0]
    assert row["status"]=="mature" and row["decision_count"]==0
    assert row["reward_minor"]==995 and row["processing_cost_minor"]==5
    assert row["restricted_unpaid_days"]==3
    assert datetime.fromisoformat(row["financial_deadline"])-datetime.fromisoformat(row["failure_at"])==timedelta(days=30)


@pytest.mark.parametrize("refund_day,expected",[(7,-5),(30,-5),(31,995)])
def test_refund_uses_fixed_30_day_financial_window(ledger,refund_day,expected):
    db,cfg=ledger(refund_day=refund_day)
    row=next(causal_episodes(db,cfg))
    assert row["reward_minor"]==expected
    assert row["recovered_30d"]==1


def test_payment_after_day30_does_not_enter_reward(ledger):
    db,cfg=ledger(paid_day=40)
    row=next(causal_episodes(db,cfg))
    assert row["reward_minor"]==0 and row["processing_cost_minor"]==0 and row["recovered_30d"]==0


def test_administrative_censoring_is_independent_of_early_success(ledger):
    cfg=Config(invoices=1,merchants=1,months=1,schema_version="2")
    for paid_day in (3,None):
        db,_=ledger(paid_day=paid_day,config=cfg)
        row=next(causal_episodes(db,cfg))
        assert row["status"]=="censored" and row["reward_minor"] is None


def test_utc_calendar_matches_world_clock(ledger):
    cfg=Config(invoices=1,merchants=1,months=1,schema_version="2",start="2024-03-01T00:00:00+03:00",parameters={"webhook_max_delay_days":0})
    db,_=ledger(config=cfg)
    row=next(causal_episodes(db,cfg))
    assert row["observed_until"]=="2024-03-29T21:00:00+00:00"
    assert row["status"]=="censored"


def test_unknown_result_has_no_financial_label(ledger):
    db,cfg=ledger(paid_day=None,unknown=True)
    row=next(causal_episodes(db,cfg))
    assert row["status"]=="unresolved" and row["reward_minor"] is None


def test_causal_projection_cannot_read_oracle_columns(ledger):
    db,cfg=ledger()
    def authorize(operation,table,column,*args):
        return sqlite3.SQLITE_DENY if operation==sqlite3.SQLITE_READ and table in {"oracle","oracle_world","step_oracle"} else sqlite3.SQLITE_OK
    db.set_authorizer(authorize)
    assert next(causal_episodes(db,cfg))["reward_minor"]==995


@pytest.mark.parametrize("partial",["payment","refund"])
def test_unsupported_partial_amounts_are_not_promoted_to_full_recovery(ledger,partial):
    db,cfg=ledger(paid_day=None if partial=="payment" else 3)
    if partial=="payment":
        db.execute("UPDATE invoices SET amount_paid=400,amount_remaining=600")
    else:
        db.execute("UPDATE invoices SET refund_amount=200")
    with pytest.raises(ValueError,match="newer causal return contract"):
        list(causal_episodes(db,cfg))


def action(selected="observe",propensity=.5,logging_policy="randomized"):
    return {"eligible":["observe","retry_day3"],"selected":selected,"propensity":propensity,
            "logging_policy":logging_policy,"prior_contacts":0}


def test_joint_weight_multiplies_across_customer_history():
    assert trajectory_weight("observe",[action() for _ in range(4)])==pytest.approx(16)
    assert trajectory_weight("observe",[])==1
    assert trajectory_weight("observe",[action(),action("retry_day3")])==0


@pytest.mark.parametrize("p",[0,-1,float("nan"),float("inf"),True,.4])
def test_invalid_or_inconsistent_behavior_propensity_is_rejected(p):
    with pytest.raises(ValueError):
        trajectory_weight("observe",[action(propensity=p)])


def test_no_silent_weight_clipping_or_deterministic_support_claim():
    with pytest.raises(ValueError,match="numeric range"):
        trajectory_weight("observe",[action() for _ in range(1100)])
    with pytest.raises(ValueError,match="randomized"):
        trajectory_weight("observe",[action(logging_policy="observe")])


def test_decisionless_customers_cannot_hide_absent_intervention_support():
    diagnostic=support([1]*100+[0],[False]*100+[True])
    assert diagnostic["effective_sample_size"]==100
    assert diagnostic["decision_customer_ess"]==0
    assert diagnostic["matched_decision_customers"]==0


def test_exact_negative_paired_contrast_has_negative_interval():
    units=[{"world":"42","merchant":str(i),"n":1,"baseline":100,"target":80} for i in range(6)]
    report=contrast_summary(units,bootstrap=30)
    assert report["delta_minor_per_failed_invoice"]==-20
    assert report["ci95"]==[-20,-20]
    assert report["ci_entirely_negative"] is True


def test_one_merchant_cannot_get_a_bootstrap_interval():
    report=contrast_summary([{"world":"42","merchant":"only","n":1,"baseline":100,"target":80}],bootstrap=30)
    assert report["status"]=="limited_clusters" and report["ci95"] is None


@pytest.fixture(scope="module")
def logged_world(tmp_path_factory):
    root=tmp_path_factory.mktemp("logged")/"world"
    generate(Config(invoices=400,merchants=8,months=6,schema_version="2",policy="randomized",failure_base=.6),root)
    return root


def test_causal_export_contains_all_initial_failures(logged_world):
    rows=[json.loads(line) for line in (logged_world/"evaluation/causal_episodes.jsonl").read_text().splitlines()]
    db=sqlite3.connect(logged_world/"simulation.sqlite")
    n=db.execute("SELECT count(*) FROM attempts WHERE number=1 AND result='failed'").fetchone()[0]
    db.close()
    assert len(rows)==n==len({(r["tenant_id"],r["invoice_id"]) for r in rows})


def test_trajectory_ope_reports_support_and_keeps_currencies_separate(logged_world):
    report=evaluate_trajectories(logged_world,bootstrap=30,min_ess=1,min_clusters=1)
    assert report["currencies"] and "total_value" not in report
    for row in report["currencies"].values():
        assert "target_support" in row
        if row["status"]=="insufficient_support":
            assert row["delta_minor_per_failed_invoice"] is None and row["ci95"] is None


def test_ope_self_comparison_is_exactly_zero_where_supported(logged_world):
    report=evaluate_trajectories(logged_world,target_policy="observe",bootstrap=30,min_ess=1,min_clusters=1)
    supported=[r for r in report["currencies"].values() if r["delta_minor_per_failed_invoice"] is not None]
    assert supported and all(r["delta_minor_per_failed_invoice"]==0 for r in supported)


def test_deterministic_log_is_not_treated_as_randomized(tmp_path):
    root=tmp_path/"fixed"
    generate(Config(invoices=30,merchants=2,schema_version="2",policy="observe"),root)
    assert evaluate_trajectories(root)["status"]=="blocked"


def test_complete_rollout_has_same_world_and_zero_self_contrast(tmp_path):
    report=compare_policies(Config(invoices=100,merchants=4,schema_version="2",failure_base=.5),tmp_path/"rollouts",seeds=(42,),bootstrap=30)
    assert len(report["runs"])==3
    assert len({r["initial_world_sha256"] for r in report["runs"]})==1
    results=report["scenarios"]["baseline"]["observe"]
    assert results and all(r["delta_minor_per_failed_invoice"]==0 for r in results.values() if r["n"]>0)


def test_different_cohorts_are_rejected_instead_of_inner_joined(logged_world):
    rows=[json.loads(line) for line in (logged_world/"evaluation/causal_episodes.jsonl").read_text().splitlines()]
    original=rows[0]
    wrong={**original,"customer_id":"other"}
    with pytest.raises(ValueError,match="cohort"):
        paired_currency_report([("42",original,wrong)],bootstrap=30)


def test_missing_provider_evidence_blocks_instead_of_dropping(logged_world):
    rows=[json.loads(line) for line in (logged_world/"evaluation/causal_episodes.jsonl").read_text().splitlines()]
    original=next(r for r in rows if r["status"]=="mature")
    other={**original,"invoice_id":"syn_other_invoice"}
    bad={**other,"status":"unresolved","reward_minor":None}
    result=paired_currency_report([("42",original,original),("42",other,bad)],bootstrap=30)
    assert result[original["currency"]]["status"]=="blocked"


def test_comparison_cannot_count_an_invoice_twice(logged_world):
    row=json.loads((logged_world/"evaluation/causal_episodes.jsonl").read_text().splitlines()[0])
    with pytest.raises(ValueError,match="Duplicate"):
        paired_currency_report([("42",row,row),("42",row,row)],bootstrap=30)


@pytest.mark.parametrize("kwargs",[{"seeds":(42,42)},{"seeds":(-1,)},{"scenarios":("invalid",)},
    {"policies":("unknown",)},{"bootstrap":10}])
def test_invalid_experiment_design_fails_before_output(tmp_path,kwargs):
    root=tmp_path/"must-not-exist"
    with pytest.raises(ValueError):
        compare_policies(Config(invoices=5,merchants=1,schema_version="2"),root,**kwargs)
    assert not root.exists()


def test_source_change_before_generation_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setattr("recoveryai_sim.engine.source_digest",lambda:"changed")
    root=tmp_path/"must-not-exist"
    with pytest.raises(RuntimeError,match="restart"):
        generate(Config(invoices=1,merchants=1),root)
    assert not root.exists()


def test_source_change_during_generation_cannot_publish_complete_manifest(tmp_path,monkeypatch):
    from recoveryai_sim.engine import IMPORTED_SOURCE_DIGEST
    values=iter((IMPORTED_SOURCE_DIGEST,"changed"))
    monkeypatch.setattr("recoveryai_sim.engine.source_digest",lambda:next(values))
    root=tmp_path/"incomplete"
    with pytest.raises(RuntimeError,match="no complete manifest"):
        generate(Config(invoices=1,merchants=1),root)
    assert not (root/"manifest.json").exists()
