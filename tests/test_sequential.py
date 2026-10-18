from dataclasses import replace
from datetime import timedelta
import heapq
import json
import sqlite3
import pytest

from recoveryai_sim.config import Config
from recoveryai_sim.engine import generate, stamp
from recoveryai_sim.evaluation import evaluate,evaluate_oracle
from recoveryai_sim.randomness import Noise
from recoveryai_sim.sequential import SequentialWorld
from recoveryai_sim.sequential_views import SEQUENCE_FEATURES
from recoveryai_sim.storage import Store
from recoveryai_sim.validation import validate
from recoveryai_sim.views import load_training


class ControlledNoise:
    def __init__(self,delay=0,payment=.999999):
        self.base=Noise(42)
        self.delay,self.payment=delay,payment
    def uniform(self,*key):
        if key[-1]=="failure":
            return 0
        if "delay" in key:
            return self.delay
        if key[-1]=="window_payment":
            return self.payment
        if key[-1] in {"delivery","open","click"}:
            return 0
        return self.base.uniform(*key)
    def normal(self,*key):
        return self.base.normal(*key)
    def choose(self,values,*key):
        return "insufficient_funds" if key[-1]=="decline" else self.base.choose(values,*key)


def drain(world,until):
    while world.queue and world.queue[0][0]<=until:
        time,_,kind,payload=heapq.heappop(world.queue)
        getattr(world,f"on_{kind}")(time,payload)


@pytest.fixture
def harness(tmp_path):
    stores=[]
    def create(delay=0,policy="rule_based",**kwargs):
        cfg=Config(invoices=1,merchants=1,months=6,schema_version="2",policy=policy,
                   parameters={"webhook_max_delay_days":10},**kwargs)
        store=Store(tmp_path/f"world-{len(stores)}.sqlite","2")
        stores.append(store)
        world=SequentialWorld(cfg,store)
        world.noise=ControlledNoise(delay)
        world.seed_world()
        time,_,kind,payload=heapq.heappop(world.queue)
        world.on_invoice(time,payload)
        invoice=next(iter(world.episodes.values()))["invoice"]
        return world,invoice,time
    yield create
    for store in stores:
        store.db.close()


@pytest.fixture
def sequential_data(tmp_path):
    root=tmp_path/"sequence"
    generate(Config(invoices=500,merchants=8,schema_version="2",failure_base=.7,policy="rule_based"),root,parquet=True)
    return root


def test_decisions_wait_for_actual_delivery(harness):
    world,invoice,time=harness(delay=.9)
    drain(world,time+timedelta(days=8))
    assert world.store.db.execute("SELECT count(*) FROM actions").fetchone()[0]==0
    drain(world,time+timedelta(days=9))
    action=world.store.db.execute("SELECT * FROM actions").fetchone()
    assert action and action["decision_at"]==stamp(time+timedelta(days=9))
    sources=json.loads(action["sources_json"])
    assert all(ref["available_at"]<=action["decision_at"] for ref in sources)


def test_hidden_customer_history_cannot_leak(harness):
    world,invoice,time=harness()
    invoice["customer"]["success"]=999
    invoice["customer"]["failed"]=999
    drain(world,time)
    features=json.loads(world.store.db.execute("SELECT features_json FROM actions").fetchone()[0])
    assert features["past_successes"]==features["past_failures"]==0


def test_late_failure_cannot_reopen_paid_projection(harness):
    world,invoice,time=harness(delay=.9)
    world.noise.delay=0
    assert world.pay(time+timedelta(days=1),invoice)
    drain(world,time+timedelta(days=10))
    assert world.episode(invoice)["state"]=="paid"
    assert world.store.db.execute("SELECT count(*) FROM actions").fetchone()[0]==0
    assert world.store.db.execute("SELECT applied FROM observations WHERE event_type='sim.payment_failed'").fetchone()[0]==0


def test_refund_before_success_delivery_never_regresses(harness):
    world,invoice,time=harness(delay=.9)
    assert world.pay(time+timedelta(days=1),invoice)
    world.noise.delay=0
    world.on_sequence_refund(time+timedelta(days=2),invoice)
    drain(world,time+timedelta(days=12))
    assert world.episode(invoice)["state"]=="refunded"
    assert world.episode(invoice)["paid_at"]==stamp(time+timedelta(days=1))


def test_duplicate_deliveries_and_timers_do_not_duplicate_step(harness):
    world,invoice,time=harness(duplicate_probability=1)
    drain(world,time)
    event=world.store.db.execute("SELECT event_id FROM observations WHERE event_type='sim.payment_failed'").fetchone()[0]
    for _ in range(4):
        world.on_delivery(time,(invoice,event))
        world.request_decision(time,invoice)
    drain(world,time)
    assert world.store.db.execute("SELECT count(*) FROM actions").fetchone()[0]==1
    assert world.store.db.execute("SELECT count(*) FROM observations WHERE event_id=?",(event,)).fetchone()[0]==1


def test_duplicate_execution_dispatches_once(harness):
    world,invoice,time=harness()
    drain(world,time)
    aid=world.store.db.execute("SELECT id FROM actions").fetchone()[0]
    for _ in range(3):
        world.on_sequence_execute(time,(invoice,aid))
    assert world.store.db.execute("SELECT count(*) FROM communications").fetchone()[0]==1
    assert world.store.db.execute("SELECT count(*) FROM action_results").fetchone()[0]==1


@pytest.mark.parametrize("delay",[0,.9])
def test_subscription_cancel_stops_scheduled_retry_even_before_notification(harness,delay):
    world,invoice,time=harness(policy="fixed_retry")
    drain(world,time)
    world.noise.delay=delay
    world.on_control(time+timedelta(days=1),(invoice,"subscription","cancelled"))
    drain(world,time+timedelta(days=12))
    action=world.store.db.execute("SELECT status FROM actions").fetchone()[0]
    assert action in {"blocked","cancelled"}
    assert world.store.db.execute("SELECT count(*) FROM attempts").fetchone()[0]==1
    assert world.store.db.execute("SELECT count(*) FROM communications").fetchone()[0]==0


def test_success_before_retry_execution_reuses_terminal_payment(harness):
    world,invoice,time=harness(policy="fixed_retry")
    drain(world,time)
    world.noise.delay=.9
    assert world.pay(time+timedelta(days=1),invoice)
    drain(world,time+timedelta(days=4))
    result=world.store.db.execute("SELECT * FROM action_results").fetchone()
    assert result["result"]=="blocked" and result["reason"]=="invoice_terminal"
    assert world.store.db.execute("SELECT count(*) FROM attempts WHERE result='succeeded'").fetchone()[0]==1
    assert not world.pay(time+timedelta(days=5),invoice)


def test_revoked_method_blocks_already_planned_retry(harness):
    world,invoice,time=harness(policy="fixed_retry")
    drain(world,time)
    world.store.update("payment_methods",invoice["customer"]["method"],status="revoked")
    drain(world,time+timedelta(days=4))
    assert world.store.db.execute("SELECT reason FROM action_results").fetchone()[0]=="retry_no_longer_eligible"
    assert world.store.db.execute("SELECT count(*) FROM attempts").fetchone()[0]==1


def test_consent_preflight_blocks_contact_with_stale_observation(harness):
    world,invoice,time=harness()
    world.noise.delay=.9
    world.on_control(time,(invoice,"consent",False))
    drain(world,time)
    action=world.store.db.execute("SELECT * FROM actions").fetchone()
    assert action["selected"]=="email" and json.loads(action["features_json"])["consent"] is True
    assert world.store.db.execute("SELECT reason FROM action_results").fetchone()[0]=="consent_revoked"
    assert world.store.db.execute("SELECT count(*) FROM communications").fetchone()[0]==0


def test_unknown_payment_never_creates_another_collection(harness):
    world,invoice,time=harness(policy="fixed_retry")
    drain(world,time)
    world.store.insert("attempts",id="syn_unknown_attempt",tenant_id=invoice["tenant"],invoice_id=invoice["id"],
        method_id=invoice["customer"]["method"],occurred_at=stamp(time+timedelta(days=1)),number=2,
        result="unknown",decline=None,processing_cost=5)
    drain(world,time+timedelta(days=12))
    assert world.store.db.execute("SELECT reason FROM action_results").fetchone()[0]=="unresolved_provider_result"
    assert world.store.db.execute("SELECT count(*) FROM attempts").fetchone()[0]==2
    assert not world.pay(time+timedelta(days=13),invoice)
    drain(world,world.end)
    outcome=world.store.db.execute("SELECT * FROM outcomes").fetchone()
    assert outcome["measurement_status"]=="unresolved" and outcome["recovered_30d"] is None


@pytest.mark.parametrize("table,id_query,column,old,new",[
    ("invoices","SELECT id FROM invoices","status","paid","open"),
    ("subscriptions","SELECT id FROM subscriptions","status","cancelled","active"),
    ("payment_methods","SELECT id FROM payment_methods","status","replaced","active"),
    ("attempts","SELECT id FROM attempts","result","failed","pending"),
])
def test_database_rejects_terminal_state_regression(harness,table,id_query,column,old,new):
    world,invoice,time=harness()
    rid=world.store.db.execute(id_query).fetchone()[0]
    world.store.db.execute(f"UPDATE {table} SET {column}=? WHERE id=?",(old,rid))
    with pytest.raises(sqlite3.IntegrityError,match="illegal state transition"):
        world.store.db.execute(f"UPDATE {table} SET {column}=? WHERE id=?",(new,rid))


def test_terminal_action_cannot_execute_again(harness):
    world,invoice,time=harness()
    drain(world,time)
    with pytest.raises(sqlite3.IntegrityError):
        world.store.db.execute("UPDATE actions SET status='scheduled'")


def test_sequential_invariants_and_training_boundary(sequential_data):
    report=validate(sequential_data)
    assert report["passed"],report
    rows=list(load_training(sequential_data))
    assert rows and any(row["metadata"]["step"]>1 for row in rows)
    assert all(set(row["x"])==SEQUENCE_FEATURES-{"available_at"} for row in rows)
    assert all(row["reward_30d_minor"] is None for row in rows)
    episodes=[json.loads(line) for line in (sequential_data/"training/episodes.jsonl").read_text().splitlines()]
    assert len({row["invoice_id"] for row in episodes})==len(episodes)
    assert len(episodes)<len(rows)
    db=sqlite3.connect(sequential_data/"simulation.sqlite")
    sources=[json.loads(row[0]) for row in db.execute("SELECT sources_json FROM actions WHERE step>1")]
    assert any(any(ref.get("kind")=="execution" for ref in group) for group in sources)
    db.close()


def test_sequential_ope_cannot_reuse_single_step_estimators(sequential_data):
    assert evaluate(sequential_data)["status"]=="blocked"
    assert evaluate_oracle(sequential_data)["status"]=="blocked"


def test_sequential_repeatability(sequential_data,tmp_path):
    other=tmp_path/"repeat"
    generate(Config(invoices=500,merchants=8,schema_version="2",failure_base=.7,policy="rule_based"),other,parquet=True)
    for file in sequential_data.rglob("*.jsonl"):
        assert file.read_bytes()==(other/file.relative_to(sequential_data)).read_bytes()


def test_observe_policy_has_zero_customer_dispatch(tmp_path):
    root=tmp_path/"observe"
    generate(Config(invoices=200,merchants=5,schema_version="2",policy="observe",failure_base=.8),root)
    db=sqlite3.connect(root/"simulation.sqlite")
    assert db.execute("SELECT count(*) FROM communications").fetchone()[0]==0
    assert db.execute("SELECT count(*) FROM attempts WHERE action_id IS NOT NULL").fetchone()[0]==0
    db.close()
    assert validate(root)["passed"]


def test_censored_decision_labels_are_null(tmp_path):
    root=tmp_path/"short"
    generate(Config(invoices=30,merchants=2,months=1,schema_version="2",failure_base=.9),root)
    rows=list(load_training(root))
    assert rows and all(row["y"]["retention_90d"] is None for row in rows)
    assert validate(root)["passed"]


def test_stale_consent_grant_cannot_override_newer_revocation(harness):
    world,invoice,time=harness(delay=.9)
    world.on_control(time+timedelta(days=1),(invoice,"consent",True))
    world.noise.delay=0
    world.on_control(time+timedelta(days=2),(invoice,"consent",False))
    drain(world,time+timedelta(days=12))
    assert world.episode(invoice)["consent"] is False
    assert world.store.db.execute("SELECT applied FROM observations WHERE event_type='sim.consent_changed' ORDER BY occurred_at LIMIT 1").fetchone()[0]==0


def test_stale_pause_cannot_override_newer_reactivation(harness):
    world,invoice,time=harness(delay=.9)
    world.on_control(time+timedelta(days=1),(invoice,"subscription","paused"))
    world.noise.delay=0
    world.on_control(time+timedelta(days=2),(invoice,"subscription","active"))
    drain(world,time+timedelta(days=12))
    assert not world.episode(invoice)["stopped"]


def test_voided_invoice_stops_already_planned_retry(harness):
    world,invoice,time=harness(policy="fixed_retry")
    drain(world,time)
    world.noise.delay=.9
    world.on_control(time+timedelta(days=1),(invoice,"invoice","voided"))
    drain(world,time+timedelta(days=12))
    assert world.store.db.execute("SELECT reason FROM action_results").fetchone()[0]=="invoice_terminal"
    assert world.episode(invoice)["state"]=="voided"


def test_action_results_record_dispatch_costs(sequential_data):
    db=sqlite3.connect(sequential_data/"simulation.sqlite")
    assert db.execute("SELECT sum(communication_cost) FROM action_results").fetchone()[0]==db.execute("SELECT sum(cost_minor) FROM communications").fetchone()[0]
    assert db.execute("SELECT sum(processing_cost) FROM action_results").fetchone()[0]==db.execute("SELECT coalesce(sum(processing_cost),0) FROM attempts WHERE action_id IS NOT NULL AND id IN (SELECT p.id FROM attempts p JOIN actions a ON a.id=p.action_id WHERE a.selected='retry_day3')").fetchone()[0]
    db.close()


def test_unknown_result_requires_definitive_reconciliation(harness):
    world,invoice,time=harness(policy="fixed_retry",max_retries=2)
    drain(world,time+timedelta(days=3))
    pending=world.store.db.execute("SELECT id FROM attempts WHERE result='pending'").fetchone()[0]
    world.store.update("attempts",pending,result="unknown")
    world.emit(invoice,time+timedelta(days=4),"payment_unknown")
    drain(world,time+timedelta(days=4))
    assert world.episode(invoice)["unknown"]
    world.store.update("attempts",pending,result="failed",decline="insufficient_funds")
    world.emit(invoice,time+timedelta(days=5),"payment_failed")
    drain(world,time+timedelta(days=5))
    assert not world.episode(invoice)["unknown"]
    assert world.store.db.execute("SELECT count(*) FROM attempts").fetchone()[0]==2


@pytest.mark.parametrize("kind,value",[("consent",1),("invoice","paid")])
def test_control_contract_rejects_ambiguous_mutations(harness,kind,value):
    world,invoice,time=harness()
    with pytest.raises(ValueError):
        world.on_control(time,(invoice,kind,value))
