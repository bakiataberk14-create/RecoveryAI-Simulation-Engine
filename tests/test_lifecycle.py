from dataclasses import replace
from datetime import timedelta
import heapq
import json
import sqlite3

import pytest

from recoveryai_sim.config import Config
from recoveryai_sim.engine import add_months, generate
from recoveryai_sim.sequential import SequentialWorld
from recoveryai_sim.storage import Store
from recoveryai_sim.validation import validate


def config(*events, **kwargs):
    return Config(schema_version="2", invoices=12, merchants=1, months=12,
                  lifecycle_events=events, **kwargs)


def event(day, kind, **kwargs):
    return dict(customer_index=0, day=day, kind=kind, **kwargs)


def read(root, table):
    with sqlite3.connect(root / "simulation.sqlite") as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]


def test_pause_resume_skips_but_does_not_strand_renewals(tmp_path):
    generate(config(event(20,"pause"), event(75,"resume")), tmp_path/"run")
    slots = read(tmp_path/"run", "renewal_slots")
    assert len(slots) == 12
    assert [s["cycle"] for s in slots if s["status"] == "paused"] == [1,2]
    assert len(read(tmp_path/"run", "invoices")) == 10
    assert validate(tmp_path/"run")["passed"]


def test_cancel_terminal_no_future_invoice_or_resume(tmp_path):
    generate(config(event(20,"cancel")), tmp_path/"run")
    assert len(read(tmp_path/"run", "invoices")) == 1
    assert all(s["status"] == "cancelled" for s in read(tmp_path/"run", "renewal_slots")[1:])
    with pytest.raises(ValueError, match="Illegal"):
        config(event(20,"cancel"), event(30,"resume"))


def test_plan_changes_only_future_invoice_terms_and_preserves_next_anchor(tmp_path):
    generate(config(), tmp_path/"base")
    generate(config(event(20,"plan", amount_minor=7777, interval_months=3)), tmp_path/"plan")
    base, plan = read(tmp_path/"base", "invoices"), read(tmp_path/"plan", "invoices")
    assert plan[0]["amount_due"] == base[0]["amount_due"]
    assert plan[0]["created_at"] == base[0]["created_at"]
    assert plan[1]["created_at"] == base[1]["created_at"]
    assert all(i["amount_due"] == 7777 for i in plan[1:])
    from datetime import datetime
    for prior, current in zip(plan[1:],plan[2:]):
        assert datetime.fromisoformat(current["created_at"]) == add_months(datetime.fromisoformat(prior["created_at"]),3)
    assert len(plan) == 5
    assert validate(tmp_path/"plan")["passed"]


def test_interval_shortening_no_duplicate_or_budget_overflow(tmp_path):
    cfg = config(event(20,"plan",interval_months=3),event(130,"plan",interval_months=1))
    generate(cfg,tmp_path/"run")
    rows = read(tmp_path/"run", "renewal_slots")
    assert len(rows) <= cfg.invoices
    assert len({r["scheduled_at"] for r in rows}) == len(rows)
    assert validate(tmp_path/"run")["passed"]


def test_duplicate_control_and_renewal_are_idempotent(tmp_path):
    with_store = Store(tmp_path/"world.sqlite","2")
    try:
        world = SequentialWorld(config(event(20,"plan",amount_minor=7777)),with_store)
        world.seed_world()
        first, *rest = sorted(world.queue)
        world.on_invoice(first[0],first[3])
        world.on_invoice(first[0],first[3])
        control = next(row for row in rest if row[2] == "lifecycle")
        world.on_lifecycle(control[0],control[3])
        world.on_lifecycle(control[0],control[3])
        assert with_store.db.execute("SELECT count(*) FROM invoices").fetchone()[0] == 1
        assert with_store.db.execute("SELECT count(*) FROM subscription_events").fetchone()[0] == 1
    finally:
        with_store.db.close()


@pytest.mark.parametrize("table,column,value",[("invoices","amount_due",1),("renewal_slots","amount_minor",1),
                                               ("subscription_events","kind","pause")])
def test_immutable_lifecycle_evidence(tmp_path,table,column,value):
    generate(config(event(20,"plan",amount_minor=7777)),tmp_path/"run")
    with sqlite3.connect(tmp_path/"run"/"simulation.sqlite") as db:
        with pytest.raises(sqlite3.IntegrityError,match="immutable|append-only"):
            db.execute(f"UPDATE {table} SET {column}=?",(value,))


def test_active_recovery_uses_old_invoice_amount_after_plan_change(tmp_path):
    from test_sequential import ControlledNoise
    store = Store(tmp_path/"world.sqlite","2")
    try:
        world = SequentialWorld(config(event(1,"plan",amount_minor=7777),failure_base=.9),store)
        world.noise = ControlledNoise(delay=.5)
        world.seed_world()
        start = min(t for t,_,k,_ in world.queue if k == "invoice")
        while world.queue and world.queue[0][0] <= start+timedelta(days=6):
            time,_,kind,payload = heapq.heappop(world.queue)
            getattr(world,f"on_{kind}")(time,payload)
        invoice = store.db.execute("SELECT amount_due FROM invoices ORDER BY created_at LIMIT 1").fetchone()[0]
        features = [json.loads(r[0]) for r in store.db.execute("SELECT features_json FROM actions")]
        assert invoice != 7777 and features
        assert all(f["amount_minor"] == invoice for f in features)
    finally:
        store.db.close()


def test_lifecycle_is_deterministic_and_policy_independent(tmp_path):
    cfg = config(event(20,"pause"),event(75,"resume"),event(100,"plan",amount_minor=7777))
    a = generate(cfg,tmp_path/"a")
    b = generate(replace(cfg,policy="observe"),tmp_path/"b")
    c = generate(cfg,tmp_path/"c")
    assert a["initial_world_sha256"] == b["initial_world_sha256"]
    assert a["logical_checksums"] == c["logical_checksums"]
    assert read(tmp_path/"a","renewal_slots") == read(tmp_path/"b","renewal_slots")


@pytest.mark.parametrize("item",[event(0,"pause"),event(1,"bad"),event(1,"plan"),
    event(1,"plan",amount_minor=True),event(1,"plan",amount_minor=-1),
    event(1,"plan",interval_months=13),event(1,"pause",amount_minor=1)])
def test_invalid_lifecycle_config(item):
    with pytest.raises(ValueError):
        config(item)


def test_unknown_customer_and_out_of_horizon_fail_explicitly(tmp_path):
    for i,cfg in enumerate((config(dict(customer_index=999,day=1,kind="pause")),config(event(900,"pause")))):
        with pytest.raises(ValueError):
            generate(cfg,tmp_path/str(i))
        assert not (tmp_path/str(i)/"manifest.json").exists()


def test_schema_one_rejects_lifecycle_and_conflicting_days():
    with pytest.raises(ValueError,match="schema 2"):
        Config(lifecycle_events=[event(1,"pause")])
    with pytest.raises(ValueError,match="one lifecycle"):
        config(event(1,"pause"),event(1,"resume"))
    with pytest.raises(ValueError,match="after cancellation"):
        config(event(1,"cancel"),event(2,"plan",amount_minor=1))


def test_control_at_exact_renewal_boundary_precedes_invoice(tmp_path):
    # Seed42 customer0 starts Jan25; first monthly renewal is exactly day31.
    generate(config(event(31,"pause"),event(32,"resume")),tmp_path/"run")
    slots = read(tmp_path/"run","renewal_slots")
    assert slots[1]["status"] == "paused"
    assert slots[2]["status"] == "issued"


@pytest.mark.parametrize("cancel_day,expected",[(40,0),(120,1)])
def test_retention_uses_lifecycle_state_at_label_boundary_not_final_state(tmp_path,cancel_day,expected):
    from test_sequential import ControlledNoise
    class RetentionNoise(ControlledNoise):
        def uniform(self,*key):
            return 0 if key[-1] == "retention" else super().uniform(*key)
    store = Store(tmp_path/"w.sqlite","2")
    try:
        world = SequentialWorld(config(event(cancel_day,"cancel")),store)
        world.noise = RetentionNoise()
        world.run()
        assert store.db.execute("SELECT retention_90d FROM outcomes ORDER BY invoice_id LIMIT 1").fetchone()[0] == expected
    finally:
        store.db.close()


def test_merchant_ownership_is_checked_before_control_mutation(tmp_path):
    store = Store(tmp_path/"w.sqlite","2")
    try:
        world = SequentialWorld(config(event(20,"cancel")),store)
        world.seed_world()
        time,_,_,payload = next(row for row in world.queue if row[2] == "lifecycle")
        customer,control,number = payload
        with pytest.raises(ValueError,match="ownership"):
            world.on_lifecycle(time,({**customer,"tenant":"syn_other"},control,number))
        assert store.db.execute("SELECT status FROM subscriptions").fetchone()[0] == "active"
        assert store.db.execute("SELECT count(*) FROM subscription_events").fetchone()[0] == 0
    finally:
        store.db.close()


def test_policy_comparison_accepts_only_same_exogenous_lifecycle_cohort(tmp_path):
    from recoveryai_sim.policy_comparison import compare_policies
    cfg = replace(config(event(20,"pause"),event(75,"resume")),invoices=100,merchants=3)
    report = compare_policies(cfg,tmp_path/"comparison",seeds=(42,),bootstrap=20)
    assert report["status"] == "complete"
    assert len({run["initial_world_sha256"] for run in report["runs"]}) == 1
    assert len({run["failed_invoice_cohort"] for run in report["runs"]}) == 1
