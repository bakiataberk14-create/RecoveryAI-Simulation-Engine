"""Exogenous, synthetic subscription controls; no proration or provider calls."""
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class LifecycleEvent:
    customer_index: int
    day: int
    kind: str
    amount_minor: int | None = None
    interval_months: int | None = None

    def __post_init__(self):
        if type(self.customer_index) is not int or self.customer_index < 0:
            raise ValueError("Lifecycle customer_index must be nonnegative")
        if type(self.day) is not int or self.day < 1:
            raise ValueError("Lifecycle day must be a positive signup-relative day")
        if self.kind not in {"pause", "resume", "cancel", "plan"}:
            raise ValueError("Unknown lifecycle kind")
        if self.kind != "plan" and (self.amount_minor is not None or self.interval_months is not None):
            raise ValueError("Only plan events accept pricing fields")
        if self.kind == "plan" and self.amount_minor is None and self.interval_months is None:
            raise ValueError("Plan event requires amount or interval")
        if self.amount_minor is not None and (type(self.amount_minor) is not int or self.amount_minor <= 0):
            raise ValueError("Plan amount must be a positive integer in existing currency minor units")
        if self.interval_months is not None and (type(self.interval_months) is not int or not 1 <= self.interval_months <= 12):
            raise ValueError("Plan interval must be 1..12 months")


class LifecycleMixin:
    def seed_world(self):
        super().seed_world()
        customers = {payload[0]["id"]: payload[0] for _, _, kind, payload in self.queue if kind == "invoice"}
        for number, event in enumerate(self.config.lifecycle_events):
            cid = f"syn_cus_{event.customer_index:08d}"
            if cid not in customers:
                raise ValueError(f"Lifecycle customer does not exist: {cid}")
            customer = customers[cid]
            time = customer["signup"] + timedelta(days=event.day)
            if time > self.end:
                raise ValueError("Lifecycle event exceeds simulation horizon")
            self.schedule(time, "lifecycle", (customer, event, number))

    def on_lifecycle(self, time, payload):
        from .engine import add_months, stamp
        from .storage import encode
        from .state_machine import require_transition
        customer, event, number = payload
        db = self.store.db
        key = f"syn_lifecycle_{number:06d}"
        row = db.execute("SELECT * FROM subscriptions WHERE id=? AND tenant_id=? AND customer_id=?",
                         (customer["sub"], customer["tenant"], customer["id"])).fetchone()
        if row is None:
            raise ValueError("Subscription ownership mismatch")
        existing = db.execute("SELECT * FROM subscription_events WHERE id=?", (key,)).fetchone()
        if existing:
            if (existing["tenant_id"],existing["subscription_id"],existing["occurred_at"],existing["kind"]) != (row["tenant_id"],row["id"],stamp(time),event.kind):
                raise ValueError("Lifecycle idempotency key collision")
            return
        before = dict(row)
        if event.kind == "plan":
            if row["status"] == "cancelled":
                raise ValueError("Cancelled subscriptions cannot change plan")
            values = {name: getattr(event, name) for name in ("amount_minor", "interval_months") if getattr(event, name) is not None}
            self.store.update("subscriptions", row["id"], **values)
            if event.amount_minor is not None:
                customer["amount"] = event.amount_minor
            if event.interval_months is not None:
                # Keep the next billing anchor; replace only later, unissued slots.
                pending = [i for i, date in enumerate(customer["dates"]) if date >= time]
                for i in pending[1:]:
                    customer["dates"][i] = add_months(customer["dates"][i-1], event.interval_months)
        else:
            status = {"pause": "paused", "resume": "active", "cancel": "cancelled"}[event.kind]
            require_transition("subscriptions", row["status"], status)
            self.store.update("subscriptions", row["id"], status=status)
            for episode in list(self.episodes.values()):
                invoice = episode["invoice"]
                if invoice["customer"]["sub"] == row["id"]:
                    self.emit(invoice, time, f"subscription_{status}", {"status": status})
        after = dict(db.execute("SELECT * FROM subscriptions WHERE id=?", (row["id"],)).fetchone())
        self.store.insert("subscription_events", id=key, tenant_id=row["tenant_id"], subscription_id=row["id"],
                          occurred_at=stamp(time), kind=event.kind, before_json=encode(before), after_json=encode(after))

    def on_invoice(self, time, payload):
        from .engine import stamp
        customer, cycle = payload
        if time != customer["dates"][cycle]:
            # A queued renewal belongs to an obsolete interval; requeue its replacement.
            self.schedule(customer["dates"][cycle], "invoice", payload)
            return
        key = f"syn_slot_{customer['id']}_{cycle:03d}"
        if self.store.db.execute("SELECT 1 FROM renewal_slots WHERE id=?", (key,)).fetchone():
            return
        row = self.store.db.execute("SELECT * FROM subscriptions WHERE id=?", (customer["sub"],)).fetchone()
        active = row["status"] == "active"
        self.store.insert("renewal_slots", id=key, tenant_id=customer["tenant"], subscription_id=customer["sub"],
                          scheduled_at=stamp(time), cycle=cycle, status="issued" if active else row["status"],
                          amount_minor=row["amount_minor"], currency=row["currency"], interval_months=row["interval_months"],
                          invoice_id=f"syn_inv_{customer['id']}_{cycle:03d}" if active else None)
        if active:
            super().on_invoice(time, payload)
        elif cycle + 1 < len(customer["dates"]):
            # A skipped paused slot must not strand all subsequent renewals.
            self.schedule(customer["dates"][cycle+1], "invoice", (customer, cycle+1))
