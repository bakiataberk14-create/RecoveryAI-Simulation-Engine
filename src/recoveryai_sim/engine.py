"""Chronological queue, persistent customer history and bounded batch output."""
import bisect
import calendar
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import heapq
import json
import math
import hashlib
from pathlib import Path

from . import __version__
from .causal import potential
from .config import Config, SCENARIOS
from .randomness import Noise
from .safety import CATEGORY, Context, HARD, RULE_VERSION, eligible_actions, select_action
from .storage import Store, encode, export_tables

COUNTRIES = ("US", "GB", "DE", "FR", "CA", "AU", "TR")
CURRENCIES = {"US": "USD", "GB": "GBP", "DE": "EUR", "FR": "EUR", "CA": "CAD", "AU": "AUD", "TR": "TRY"}
INDUSTRIES = ("b2b_saas", "consumer_saas", "ai_subscription", "developer_tools", "education", "digital_service")


def source_digest():
    digest=hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n",b"\n"))
    return digest.hexdigest()


IMPORTED_SOURCE_DIGEST=source_digest()


def add_months(date, months):
    year, month = divmod(date.year * 12 + date.month - 1 + months, 12)
    return date.replace(year=year, month=month + 1, day=min(date.day, calendar.monthrange(year, month + 1)[1]))


def stamp(date):
    return date.astimezone(timezone.utc).isoformat()


def generate(config: Config, output: Path, parquet=False):
    if source_digest()!=IMPORTED_SOURCE_DIGEST:
        raise RuntimeError("Source changed since process import; restart the simulation")
    if parquet:
        import pyarrow  # fail before creating output if optional dependency is absent
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    store = Store(output / "simulation.sqlite", config.schema_version)
    if config.schema_version == "2":
        from .sequential import SequentialWorld
        world = SequentialWorld(config, store)
    else:
        world = World(config, store)
    try:
        world.run()
        store.db.commit()
        counts = export_tables(store.db, output, parquet, store.schema)
        if config.schema_version == "2":
            from .sequential_views import export_training_v2
            export_training_v2(store.db, output)
            from .trajectory import export_causal_episodes
            export_causal_episodes(store.db,output,config)
        else:
            from .views import export_training
            export_training(store.db, output)
        checksums = {}
        for path in sorted(output.rglob("*.jsonl")):
            with path.open("rb") as content:
                checksums[path.relative_to(output).as_posix()] = hashlib.file_digest(content, "sha256").hexdigest()
        if source_digest()!=IMPORTED_SOURCE_DIGEST:
            raise RuntimeError("Source changed during simulation; no complete manifest published")
        manifest = {"label": "SYNTHETIC / NOT REAL TRANSACTIONS", "billable": False,
                    "engine_version": __version__, "config": asdict(config), "config_sha256": config.digest,
                    "rule_version": RULE_VERSION, "counts": counts, "status": "complete",
                    "source_sha256": IMPORTED_SOURCE_DIGEST, "logical_checksums": checksums,
                    "source_registry_version": "2026-10-18.4",
                    "lifecycle_contract": "exogenous-calendar-v1" if config.schema_version=="2" else None,
                    "initial_world_sha256": world.initial_world_sha256,
                    "causal_episode_contract": "failure-anchored-30d-v1" if config.schema_version=="2" else None,
                    "oracle_warning": "oracle/ and simulation.sqlite contain hidden truth; NEVER train directly from them"}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        store.db.close()
    return manifest


class World:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.parameters = config.parameters
        self.noise = Noise(config.seed)
        self.start = datetime.fromisoformat(config.start).astimezone(timezone.utc)
        self.end = add_months(self.start, config.months)
        self.queue = []
        self.serial = 0
        self.created = 0

    def schedule(self, time, kind, payload):
        if time <= self.end:
            self.serial += 1
            heapq.heappush(self.queue, (time, self.serial, kind, payload))

    def emit(self, invoice, time, kind):
        event_id = f"syn_evt_{invoice['id']}_{kind}"
        reference = {"invoice_created": "invoice.created", "payment_failed": "invoice.payment_failed",
                     "payment_succeeded": "invoice.payment_succeeded"}.get(kind)
        self.store.insert("events", id=event_id, tenant_id=invoice["tenant"], invoice_id=invoice["id"],
                          occurred_at=stamp(time), event_type=f"sim.{kind}", provider_reference_type=reference)
        # Delivery delays can reorder business events; duplicates share the event ID.
        copies = 2 if self.noise.uniform(event_id, "duplicate") < self.config.duplicate_probability else 1
        for copy in range(copies):
            delay = self.noise.uniform(event_id, "delay", copy) * self.parameters.webhook_max_delay_days
            delivered = time + timedelta(days=delay)
            if delivered <= self.end:
                self.store.insert("deliveries", id=f"syn_delivery_{event_id}_{copy}", tenant_id=invoice["tenant"],
                                  event_id=event_id, delivered_at=stamp(delivered))

    def seed_world(self):
        cumulative, merchants = [], []
        for i in range(self.config.merchants):
            mid = f"syn_mer_{i:05d}"
            tenant = f"syn_tenant_{i:05d}"
            country = self.noise.choose(COUNTRIES, mid, "country")
            currency = CURRENCIES[country]
            self.store.insert("merchants", id=mid, tenant_id=tenant, country=country, currency=currency,
                              industry=self.noise.choose(INDUSTRIES, mid, "industry"), provider="stripe")
            weight = min(self.parameters.merchant_size_cap, (1 - self.noise.uniform(mid, "size")) ** (-1 / self.parameters.merchant_size_shape))
            cumulative.append(weight + (cumulative[-1] if cumulative else 0))
            merchants.append((mid, tenant, country, currency, self.parameters.merchant_effect_sd * self.noise.normal(mid, "effect")))
        planned, customer_index = 0, 0
        while planned < self.config.invoices:
            cid = f"syn_cus_{customer_index:08d}"
            # First cohorts cover each merchant; remaining acquisition follows heavy-tailed weights.
            merchant_index = customer_index if customer_index < len(merchants) else bisect.bisect_left(
                cumulative, self.noise.uniform(cid, "merchant") * cumulative[-1])
            mid, tenant, country, currency, effect = merchants[merchant_index]
            interval = self.noise.choose((1, 1, 1, 1, 3, 12), cid, "interval")
            signup = self.start + timedelta(days=self.noise.uniform(cid, "signup") * min(self.parameters.acquisition_days, (self.end-self.start).days/2))
            dates, date = [], signup
            # Reserve at least one invoice for each merchant's first customer.
            reserve = max(0, self.config.merchants - customer_index - 1)
            capacity = self.config.invoices - planned - reserve
            while date < self.end and len(dates) < capacity:
                dates.append(date)
                date = add_months(date, interval)
            planned += len(dates)
            reliability = max(0.05, min(0.98, self.parameters.reliability_mean + self.parameters.reliability_sd * self.noise.normal(cid, "reliability")))
            engagement = self.noise.uniform(cid, "engagement")
            consent = self.noise.uniform(cid, "consent") < self.parameters.consent_probability
            willingness = self.noise.uniform(cid, "willingness")
            base = self.parameters.enterprise_amount_minor if self.config.scenario == "enterprise" else self.parameters.consumer_amount_minor if self.config.scenario == "consumer" else self.parameters.amount_base_minor
            amount = max(100, int(base * math.exp(self.parameters.amount_log_sd * self.noise.normal(cid, "amount"))))
            sub, method = f"syn_sub_{customer_index:08d}", f"syn_pm_{customer_index:08d}"
            self.store.insert("customers", id=cid, tenant_id=tenant, merchant_id=mid, signup_at=stamp(signup), consent=int(consent), engagement=engagement)
            self.store.insert("subscriptions", id=sub, tenant_id=tenant, customer_id=cid, interval_months=interval,
                              amount_minor=amount, currency=currency, start_at=stamp(signup), status="active")
            self.store.insert("payment_methods", id=method, tenant_id=tenant, customer_id=cid,
                              method_type="card", issuing_country=country, status="active")
            self.store.insert("oracle_world", id=cid, tenant_id=tenant, merchant_effect=effect,
                              reliability=reliability, willingness=willingness)
            customer = dict(id=cid, tenant=tenant, merchant=mid, country=country, currency=currency,
                            effect=effect, reliability=reliability, engagement=engagement, consent=consent,
                            willingness=willingness, amount=amount, sub=sub, method=method,
                            dates=dates, signup=signup, success=0, failed=0)
            self.schedule(dates[0], "invoice", (customer, 0))
            customer_index += 1

    def run(self):
        self.seed_world()
        initial_hash=hashlib.sha256()
        for table in ("merchants","customers","subscriptions","payment_methods","oracle_world"):
            initial_hash.update(table.encode())
            for row in self.store.db.execute(f"SELECT * FROM {table} ORDER BY id"):
                initial_hash.update((encode(dict(row))+"\n").encode())
        initial_hash.update(encode([asdict(event) for event in self.config.lifecycle_events]).encode())
        for _,_,kind,payload in sorted(self.queue):
            if kind != "invoice":
                continue
            customer,_ = payload
            initial_hash.update(encode({"customer":customer["id"],"renewals":[stamp(date) for date in customer["dates"]]}).encode())
        self.initial_world_sha256=initial_hash.hexdigest()
        while self.queue:
            time, _, kind, payload = heapq.heappop(self.queue)
            getattr(self, f"on_{kind}")(time, payload)
            if self.serial % 5000 == 0:
                self.store.db.commit()

    def on_invoice(self, time, payload):
        customer, cycle = payload
        iid = f"syn_inv_{customer['id']}_{cycle:03d}"
        invoice = dict(id=iid, tenant=customer["tenant"], customer=customer, time=time, amount=customer["amount"])
        self.store.insert("invoices", id=iid, tenant_id=customer["tenant"], subscription_id=customer["sub"],
                          currency=customer["currency"], amount_due=customer["amount"], amount_remaining=customer["amount"],
                          created_at=stamp(time), status="open")
        self.emit(invoice, time, "invoice_created")
        self.created += 1
        shift = SCENARIOS[self.config.scenario][0]
        elapsed = (time-self.start).days
        outage = self.config.scenario == "issuer_outage" and 180 <= elapsed % 365 <= 194
        common_shock = self.parameters.weekly_shock_sd * self.noise.normal("world", elapsed // 7)
        probability = max(0.01, min(0.95, self.config.failure_base + shift + customer["effect"]
                                  + (self.parameters.reliability_mean-customer["reliability"]) * self.parameters.failure_reliability_weight + common_shock + (self.parameters.outage_failure_shift if outage else 0)))
        failed = self.noise.uniform(iid, "failure") < probability
        decline = None
        if failed:
            decline = "issuer_not_available" if outage else self.noise.choose(
                ("insufficient_funds", "insufficient_funds", "expired_card", "authentication_required", "generic_decline", "lost_card"), iid, "decline")
            if self.config.scenario == "expired_wave" and self.noise.uniform(iid, "expired") < self.parameters.expired_wave_probability:
                decline = "expired_card"
        self.store.insert("attempts", id=f"syn_attempt_{iid}_1", tenant_id=invoice["tenant"], invoice_id=iid,
                          method_id=customer["method"], occurred_at=stamp(time), number=1,
                          result="failed" if failed else "succeeded", decline=decline, processing_cost=self.parameters.processing_cost_minor)
        if failed:
            customer["failed"] += 1
            invoice["decline"] = decline
            self.emit(invoice, time, "payment_failed")
            self.decide(time, invoice)
        else:
            customer["success"] += 1
            self.store.update("invoices", iid, amount_paid=customer["amount"], amount_remaining=0, paid_at=stamp(time), status="paid")
            self.emit(invoice, time, "payment_succeeded")
        if cycle + 1 < len(customer["dates"]):
            self.schedule(customer["dates"][cycle+1], "invoice", (customer, cycle+1))

    def decide(self, time, invoice):
        c, iid = invoice["customer"], invoice["id"]
        aid = f"syn_action_{iid}"
        ctx = Context(decline=invoice["decline"], consent=c["consent"], issuing_country=c["country"], max_retries=self.config.max_retries)
        eligible = eligible_actions(ctx)
        chosen, propensity = select_action(self.config.policy, eligible, self.noise.uniform(iid, "policy"))
        features = {"amount_minor": c["amount"], "currency": c["currency"], "decline_reason": invoice["decline"],
                    "decline_category": CATEGORY.get(invoice["decline"], "unknown"), "attempt_count": 1,
                    "subscription_age_days": (time-c["signup"]).days, "past_successes": c["success"],
                    "past_failures": c["failed"]-1, "engagement": c["engagement"], "consent": c["consent"],
                    "available_at": stamp(time)}
        self.store.insert("actions", id=aid, tenant_id=c["tenant"], invoice_id=iid, customer_id=c["id"],
                          decision_at=stamp(time), features_json=encode(features), eligible_json=encode(eligible),
                          selected=chosen, propensity=propensity, policy=self.config.policy, policy_version="1",
                          rule_version=RULE_VERSION, status="scheduled")
        potentials = {action: potential(self.noise, iid, action, c["reliability"], c["willingness"],
                                       c["engagement"], c["amount"], self.config) for action in eligible}
        for action, result in potentials.items():
            self.store.insert("oracle", id=f"syn_oracle_{aid}_{action}", tenant_id=c["tenant"], action_id=aid,
                              action=action, recovery_day=result.recovery_day, retained_90d=int(result.retained),
                              refund_day=result.refund_day, reward_minor=result.net, latent_reliability=c["reliability"])
        invoice.update(action=aid, chosen=chosen, result=potentials[chosen], processed=False, paid=False, refund=0, comm_cost=0)
        execution = time + timedelta(days=3 if chosen == "retry_day3" else 0)
        self.schedule(execution, "execute", invoice)
        result = potentials[chosen]
        if result.recovery_day is not None:
            self.schedule(time+timedelta(days=result.recovery_day), "recovered", invoice)
        if result.refund_day is not None:
            self.schedule(time+timedelta(days=result.refund_day), "refund", invoice)
        self.schedule(min(self.end, time+timedelta(days=90)), "outcome", invoice)

    def on_execute(self, time, invoice):
        chosen, c, result = invoice["chosen"], invoice["customer"], invoice["result"]
        self.store.update("actions", invoice["action"], execution_at=stamp(time),
                          status="observed" if chosen == "observe" else "review_only" if chosen == "review" else "executed")
        if chosen in {"email", "request_update", "request_authentication"}:
            invoice["comm_cost"] = result.communication_cost
            self.store.insert("communications", id=f"syn_comm_{invoice['action']}", tenant_id=c["tenant"],
                              action_id=invoice["action"], sent_at=stamp(time), delivered=int(result.delivered),
                              opened=int(result.opened), clicked=int(result.clicked), cost_minor=invoice["comm_cost"])
        if chosen == "retry_day3":
            invoice["processed"] = True
            # A scheduled retry is the single retry in this slice; settlement can be later.
            self.store.insert("attempts", id=f"syn_attempt_{invoice['id']}_2", tenant_id=c["tenant"],
                              invoice_id=invoice["id"], method_id=c["method"], occurred_at=stamp(time), number=2,
                              result="pending" if result.recovery_day is not None else "failed", decline=None,
                              action_id=invoice["action"], processing_cost=self.parameters.processing_cost_minor)

    def on_recovered(self, time, invoice):
        c = invoice["customer"]
        invoice["paid"] = True
        c["success"] += 1
        self.store.update("invoices", invoice["id"], amount_paid=c["amount"], amount_remaining=0,
                          paid_at=stamp(time), status="paid")
        if invoice["processed"]:
            self.store.update("attempts", f"syn_attempt_{invoice['id']}_2", result="succeeded")
        else:
            # Baseline recovery is customer-initiated; it is NOT an unauthorized automatic retry.
            if invoice["decline"] in HARD or invoice["decline"] == "expired_card":
                # Explicitly simulate a fresh method, never collect again on a lost/expired card.
                fresh_method = f"syn_pm_update_{invoice['id']}"
                self.store.update("payment_methods", c["method"], status="replaced")
                self.store.insert("payment_methods", id=fresh_method, tenant_id=c["tenant"], customer_id=c["id"],
                                  method_type="card", issuing_country=c["country"], status="active")
                c["method"] = fresh_method
                self.emit(invoice, time, "customer_payment_requirements_resolved")
            self.store.insert("attempts", id=f"syn_attempt_{invoice['id']}_2", tenant_id=c["tenant"],
                              invoice_id=invoice["id"], method_id=c["method"], occurred_at=stamp(time), number=2,
                              result="succeeded", decline=None, action_id=invoice["action"], processing_cost=self.parameters.processing_cost_minor)
        self.emit(invoice, time, "payment_succeeded")

    def on_refund(self, time, invoice):
        invoice["refund"] = invoice["amount"]
        self.store.update("invoices", invoice["id"], refund_amount=invoice["refund"], status="refunded")
        self.emit(invoice, time, "refund")

    def on_outcome(self, time, invoice):
        result, created, c = invoice["result"], invoice["time"], invoice["customer"]
        age = (time-created).total_seconds()/86400
        recovered = created+timedelta(days=result.recovery_day) if invoice["paid"] else None
        labels = {f"recovered_{days}d": (int(recovered is not None and recovered <= created+timedelta(days=days))
                  if age >= days else None) for days in (7, 14, 30)}
        gross = invoice["amount"] if invoice["paid"] else 0
        cost = self.parameters.processing_cost_minor if invoice["processed"] or invoice["paid"] else 0
        # Net reward is the 30-day economic horizon; later refunds remain in invoice ledger.
        refund30 = invoice["refund"] if result.refund_day is not None and result.refund_day <= 30 else 0
        self.store.insert("outcomes", id=f"syn_outcome_{invoice['id']}", tenant_id=c["tenant"],
                          invoice_id=invoice["id"], action_id=invoice["action"], currency=c["currency"],
                          recovered_at=stamp(recovered) if recovered else None, gross_recovered=gross,
                          processing_cost=cost, communication_cost=invoice["comm_cost"], refund_amount=refund30,
                          net_revenue=gross-cost-invoice["comm_cost"]-refund30, **labels,
                          retention_90d=int(result.retained) if age >= 90 else None,
                          window_complete=int(age >= 30), observed_until=stamp(time))
