"""Schema-2 world: delayed observations, bounded decisions, execution-time guards.

Physical provider state and merchant knowledge are deliberately separate. A
decision reads only delivered evidence; a dispatch also performs a current-state
preflight. All actions and payments are offline synthetic operations.
"""
from datetime import datetime, timedelta
import json

from .engine import World, stamp
from .config import SCENARIOS
from .safety import CATEGORY, Context, HARD, RULE_VERSION, eligible_actions
from .sequence_policy import choose, POLICY_VERSION
from .storage import encode
from .lifecycle import LifecycleMixin

CONTACT = {"email", "request_update", "request_authentication"}
TERMINAL = {"paid", "refunded", "voided", "written_off"}


class SequentialWorld(LifecycleMixin, World):
    def __init__(self, config, store):
        super().__init__(config, store)
        self.episodes, self.event_numbers, self.timers = {}, {}, set()

    def on_control(self,time,payload):
        """Explicit synthetic merchant controls; their notifications can arrive late."""
        invoice,kind,value=payload
        c=invoice["customer"]
        if kind=="consent":
            if type(value) is not bool:
                raise ValueError("Consent control requires a boolean")
            self.store.update("customers",c["id"],consent=int(value))
            self.emit(invoice,time,"consent_changed",{"consent":bool(value)})
        elif kind=="subscription":
            current=self.store.db.execute("SELECT status FROM subscriptions WHERE id=?",(c["sub"],)).fetchone()[0]
            if current!=value:
                self.store.update("subscriptions",c["sub"],status=value)
                self.emit(invoice,time,f"subscription_{value}",{"status":value})
        elif kind=="invoice":
            if value not in {"voided","written_off"}:
                raise ValueError("Invoice control only supports void/write-off")
            self.store.update("invoices",invoice["id"],status=value)
            self.emit(invoice,time,"invoice_closed",{"status":value})
        else:
            raise ValueError("Unknown synthetic control")

    def episode(self, invoice):
        if invoice["id"] not in self.episodes:
            self.episodes[invoice["id"]] = dict(invoice=invoice, state="unknown", decline=None,
                attempt_count=0, method_id=invoice["customer"]["method"], method_state="active",
                consent=invoice["customer"]["consent"], observations=[], actions=[], retries=0,
                contacts=0, delivered=0, active=None, paid_at=None, refund_at=None,
                first_decision=None, last_decision=None, last_failure=None, source=None,
                tick=0, last_tick=invoice["time"], stopped=False, unknown=False, planned_methods={}, control_versions={}, result_version=None)
        return self.episodes[invoice["id"]]

    def emit(self, invoice, time, kind, payload=None):
        self.episode(invoice)
        number = self.event_numbers.get(invoice["id"], 0) + 1
        self.event_numbers[invoice["id"]] = number
        eid = f"syn_evt_{invoice['id']}_{number:04d}"
        if payload is None:
            attempt = self.store.db.execute("SELECT * FROM attempts WHERE invoice_id=? ORDER BY number DESC LIMIT 1", (invoice["id"],)).fetchone()
            payload = {"decline": attempt["decline"] if attempt else None,
                       "attempt_number": attempt["number"] if attempt else 0,
                       "attempt_id":attempt["id"] if attempt else None,
                       "action_id":attempt["action_id"] if attempt else None,
                       "method_id": attempt["method_id"] if attempt else invoice["customer"]["method"]}
        reference = {"invoice_created":"invoice.created", "payment_failed":"invoice.payment_failed",
                     "payment_succeeded":"invoice.payment_succeeded"}.get(kind)
        self.store.insert("events", id=eid, tenant_id=invoice["tenant"], invoice_id=invoice["id"],
            occurred_at=stamp(time), event_type=f"sim.{kind}", provider_reference_type=reference, payload_json=encode(payload))
        # Couple environmental delivery noise across policy worlds using semantic
        # event identity, not an ordinal changed by intervention-generated events.
        suffix = payload.get("action_id") if kind.startswith("communication_") else payload.get("attempt_number") if kind=="payment_failed" else stamp(time) if kind.startswith("subscription_") or kind=="consent_changed" else "single"
        noise_key=(invoice["id"],kind,suffix)
        copies = 2 if self.noise.uniform(*noise_key,"duplicate") < self.config.duplicate_probability else 1
        for copy in range(copies):
            delivered = time + timedelta(days=self.noise.uniform(*noise_key,"delay",copy)*self.parameters.webhook_max_delay_days)
            if delivered <= self.end:
                self.store.insert("deliveries", id=f"syn_delivery_{eid}_{copy}", tenant_id=invoice["tenant"],
                                  event_id=eid, delivered_at=stamp(delivered))
                self.schedule(delivered,"delivery",(invoice,eid))

    def decide(self, time, invoice):
        """Called on physical failure by v1 invoice generation: no immediate decision."""
        self.episode(invoice)
        self.schedule(time+timedelta(days=min(self.config.step_interval_days,self.config.recovery_window_days)),"tick",invoice)

    def request_decision(self, time, invoice):
        key = (invoice["id"], stamp(time))
        if key not in self.timers:
            self.timers.add(key)
            self.schedule(time,"decision",invoice)

    def on_delivery(self, time, payload):
        invoice, eid = payload
        event = self.store.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        if event is None or event["tenant_id"] != invoice["tenant"] or event["invoice_id"] != invoice["id"]:
            raise ValueError("Observation tenant/invoice mismatch")
        if self.store.db.execute("SELECT 1 FROM observations WHERE event_id=?",(eid,)).fetchone():
            return
        if stamp(time) < event["occurred_at"]:
            raise ValueError("Observation precedes physical event")
        state = self.episode(invoice)
        data, kind, applied = json.loads(event["payload_json"]), event["event_type"], True
        if kind == "sim.payment_failed":
            version=(data["attempt_number"],event["occurred_at"],event["id"])
            applied = state["state"] not in TERMINAL and (state["result_version"] is None or version>=state["result_version"])
            if applied:
                state["result_version"],state["unknown"]=version,False
                state.update(state="failed", decline=data["decline"], last_failure=event["occurred_at"],
                             method_id=data["method_id"], attempt_count=max(state["attempt_count"],data["attempt_number"]))
                state["method_state"] = "expired" if data["decline"] == "expired_card" else "revoked" if data["decline"] in HARD else "active"
                state["source"] = f"syn_obs_{eid}"
        elif kind == "sim.payment_succeeded":
            if state["state"] != "refunded":
                state["state"] = "paid"
            state["paid_at"] = event["occurred_at"]
            state["unknown"] = False
        elif kind == "sim.refund":
            state["state"], state["refund_at"] = "refunded", event["occurred_at"]
            state["unknown"] = False
        elif kind.startswith("sim.subscription_") or kind=="sim.consent_changed":
            group="subscription" if kind.startswith("sim.subscription_") else "consent"
            version=(event["occurred_at"],event["id"])
            applied=group not in state["control_versions"] or version>=state["control_versions"][group]
            if applied:
                state["control_versions"][group]=version
                if group=="subscription":
                    state["stopped"]=data["status"]!="active"
                else:
                    state["consent"]=bool(data["consent"])
        elif kind=="sim.invoice_closed":
            if data["status"] not in {"voided","written_off"}:
                raise ValueError("Invalid invoice close observation")
            state["state"]=data["status"]
        elif kind == "sim.payment_unknown":
            version=(data["attempt_number"],event["occurred_at"],event["id"])
            applied=state["state"] not in TERMINAL and (state["result_version"] is None or version>=state["result_version"])
            if applied:
                state["result_version"]=version
                state["unknown"] = True
        elif kind.startswith("sim.communication_"):
            field = kind.removeprefix("sim.communication_")
            # Out-of-order funnel events imply their prerequisites, never regress.
            values = {"delivered":1}
            if field in {"opened","clicked"}:
                values["opened"] = 1
            if field == "clicked":
                values["clicked"] = 1
            self.store.update("communications",f"syn_comm_{data['action_id']}",**values)
            state["delivered"]=self.store.db.execute("SELECT count(*) FROM communications c JOIN actions a ON a.id=c.action_id WHERE a.invoice_id=? AND c.delivered=1",(invoice["id"],)).fetchone()[0]
        obsid = f"syn_obs_{eid}"
        self.store.insert("observations", id=obsid, tenant_id=invoice["tenant"], invoice_id=invoice["id"],
            event_id=eid, occurred_at=event["occurred_at"], available_at=stamp(time), event_type=kind,
            applied=int(applied), payload_json=event["payload_json"])
        if applied:
            state["observations"].append(obsid)
        if state["state"] in TERMINAL or state["stopped"] or state["unknown"]:
            self.cancel_pending(time,invoice,"terminal_observation" if not state["unknown"] else "unresolved_provider_result")
        elif applied and kind == "sim.payment_failed":
            self.request_decision(time,invoice)

    def on_decision(self, time, invoice):
        s, c = self.episode(invoice), invoice["customer"]
        if s["state"] != "failed" or s["stopped"] or s["unknown"] or len(s["actions"]) >= self.config.max_steps:
            return
        if time >= invoice["time"] + timedelta(days=self.config.recovery_window_days):
            return
        if self.store.db.execute("SELECT 1 FROM actions WHERE invoice_id=? AND status='scheduled'",(invoice["id"],)).fetchone():
            return
        if s["last_decision"] and time < s["last_decision"]+timedelta(days=self.config.step_interval_days):
            self.request_decision(s["last_decision"]+timedelta(days=self.config.step_interval_days),invoice)
            return
        context = Context(decline=s["decline"],consent=s["consent"],method_active=s["method_state"]=="active",
                          issuing_country=c["country"],retries=s["retries"],max_retries=self.config.max_retries)
        eligible = eligible_actions(context)
        used = {a["selected"] for a in self.store.db.execute("SELECT selected FROM actions WHERE invoice_id=? AND status='executed'",(invoice["id"],))}
        eligible = tuple(a for a in eligible if a not in CONTACT or a not in used)
        step = len(s["actions"])+1
        chosen, probability = choose(self.config.policy,eligible,s["contacts"],self.noise.uniform(invoice["id"],step,"policy"))
        history = self.store.db.execute("""SELECT e.event_type,count(DISTINCT i.id) FROM observations o
            JOIN events e ON e.id=o.event_id JOIN invoices i ON i.id=o.invoice_id
            JOIN subscriptions sub ON sub.id=i.subscription_id
            WHERE sub.customer_id=? AND o.tenant_id=? AND o.available_at<=? AND i.id<>?
            AND e.event_type IN ('sim.payment_succeeded','sim.payment_failed') GROUP BY e.event_type""",
            (c["id"],c["tenant"],stamp(time),invoice["id"])).fetchall()
        history = dict(history)
        sources = [dict(r) for r in self.store.db.execute(
            "SELECT id,available_at FROM observations WHERE invoice_id=? AND applied=1 AND available_at<=? ORDER BY available_at,id",
            (invoice["id"],stamp(time)))]
        # Historical counts also carry exact evidence dependencies.
        sources += [dict(r) for r in self.store.db.execute("""SELECT o.id,o.available_at FROM observations o
            JOIN invoices i ON i.id=o.invoice_id JOIN subscriptions sub ON sub.id=i.subscription_id
            WHERE sub.customer_id=? AND o.tenant_id=? AND o.available_at<=? AND i.id<>?
            AND o.event_type IN ('sim.payment_succeeded','sim.payment_failed') ORDER BY o.available_at,o.id""",
            (c["id"],c["tenant"],stamp(time),invoice["id"]))]
        sources += [dict(id=r["id"],available_at=r["recorded_at"],kind="execution") for r in self.store.db.execute(
            "SELECT r.id,r.recorded_at FROM action_results r JOIN actions a ON a.id=r.action_id WHERE a.invoice_id=? AND a.tenant_id=? AND r.recorded_at<=? ORDER BY r.recorded_at,r.id",
            (invoice["id"],c["tenant"],stamp(time)))]
        features = dict(amount_minor=invoice["amount"],currency=c["currency"],decline_reason=s["decline"],
            decline_category=CATEGORY.get(s["decline"],"unknown"),attempt_count=s["attempt_count"],
            subscription_age_days=(time-c["signup"]).days,past_successes=history.get("sim.payment_succeeded",0),
            past_failures=history.get("sim.payment_failed",0),engagement=c["engagement"],consent=s["consent"],
            available_at=max(r["available_at"] for r in sources),step=step,prior_contact_count=s["contacts"],
            prior_retry_count=s["retries"],known_invoice_state=s["state"],known_method_state=s["method_state"],
            observed_delivery_count=s["delivered"],observation_lag_days=(time-datetime.fromisoformat(s["last_failure"])).total_seconds()/86400)
        aid = f"syn_action_{invoice['id']}_{step:02d}"
        self.store.insert("actions",id=aid,tenant_id=c["tenant"],invoice_id=invoice["id"],customer_id=c["id"],
            decision_at=stamp(time),features_json=encode(features),eligible_json=encode(eligible),selected=chosen,
            propensity=probability,policy=self.config.policy,policy_version=POLICY_VERSION,rule_version=RULE_VERSION,
            status="scheduled",step=step,previous_action_id=s["actions"][-1] if s["actions"] else None,
            source_observation_id=s["source"],sources_json=encode(sources))
        s["actions"].append(aid)
        s["last_decision"] = time
        s["planned_methods"][aid] = s["method_id"]
        if s["first_decision"] is None:
            s["first_decision"] = time
            self.schedule(min(self.end,time+timedelta(days=90)),"sequence_outcome",invoice)
        self.schedule(time+timedelta(days=3 if chosen=="retry_day3" else 0),"sequence_execute",(invoice,aid))

    def finish_action(self,time,invoice,aid,status,reason=None,method=None):
        chosen=self.store.db.execute("SELECT selected FROM actions WHERE id=?",(aid,)).fetchone()[0]
        self.store.update("actions",aid,status=status,execution_at=stamp(time) if status in {"executed","observed","review_only"} else None)
        self.store.insert("action_results",id=f"syn_result_{aid}",tenant_id=invoice["tenant"],action_id=aid,
            result=status,reason=reason,recorded_at=stamp(time),method_id=method,
            processing_cost=self.parameters.processing_cost_minor if chosen=="retry_day3" and status=="executed" else 0,
            communication_cost=self.parameters.communication_cost_minor if chosen in CONTACT and status=="executed" else 0)

    def cancel_pending(self,time,invoice,reason):
        for row in self.store.db.execute("SELECT id FROM actions WHERE invoice_id=? AND status='scheduled'",(invoice["id"],)).fetchall():
            self.finish_action(time,invoice,row["id"],"cancelled",reason)

    def on_sequence_execute(self,time,payload):
        invoice,aid = payload
        action = self.store.db.execute("SELECT * FROM actions WHERE id=?",(aid,)).fetchone()
        if action["status"] != "scheduled":
            return
        s,c = self.episode(invoice),invoice["customer"]
        actual = self.store.db.execute("SELECT status FROM invoices WHERE id=?",(invoice["id"],)).fetchone()[0]
        sub = self.store.db.execute("SELECT status FROM subscriptions WHERE id=?",(c["sub"],)).fetchone()[0]
        reason = "invoice_terminal" if actual != "open" else "subscription_inactive" if sub != "active" else None
        if time >= invoice["time"]+timedelta(days=self.config.recovery_window_days):
            reason = "recovery_window_closed"
        method = s["planned_methods"][aid]
        if action["selected"] in CONTACT and not self.store.db.execute("SELECT consent FROM customers WHERE id=?",(c["id"],)).fetchone()[0]:
            reason = "consent_revoked"
        if self.store.db.execute("SELECT 1 FROM attempts WHERE invoice_id=? AND result IN ('pending','unknown')",(invoice["id"],)).fetchone():
            reason = "unresolved_provider_result"
        if action["selected"]=="retry_day3":
            method_state = self.store.db.execute("SELECT status FROM payment_methods WHERE id=?",(method,)).fetchone()[0]
            ctx = Context(decline=s["decline"],consent=s["consent"],method_active=method_state=="active",
                          issuing_country=c["country"],retries=s["retries"],max_retries=self.config.max_retries)
            if "retry_day3" not in eligible_actions(ctx):
                reason = reason or "retry_no_longer_eligible"
        if reason:
            self.finish_action(time,invoice,aid,"blocked",reason)
            return
        chosen = action["selected"]
        status = "observed" if chosen=="observe" else "review_only" if chosen=="review" else "executed"
        self.finish_action(time,invoice,aid,status,method=method)
        active = dict(id=aid,selected=chosen,eligible=json.loads(action["eligible_json"]),delivered=False,attempt=None)
        if chosen in CONTACT:
            s["contacts"] += 1
            delivered = self.noise.uniform(aid,"delivery") < self.config.delivery_probability
            active["delivered"] = delivered
            self.store.insert("communications",id=f"syn_comm_{aid}",tenant_id=c["tenant"],action_id=aid,sent_at=stamp(time),
                delivered=0,opened=0,clicked=0,cost_minor=self.parameters.communication_cost_minor)
            if delivered:
                for index,kind in enumerate(("delivered","opened","clicked")):
                    if kind=="opened" and self.noise.uniform(aid,"open") >= self.parameters.open_base+c["engagement"]*self.parameters.open_engagement_weight:
                        break
                    if kind=="clicked" and self.noise.uniform(aid,"click") >= c["willingness"]:
                        break
                    self.schedule(time+timedelta(minutes=index+1),"communication_event",(invoice,aid,kind))
        if chosen=="retry_day3":
            s["retries"] += 1
            number = self.store.db.execute("SELECT max(number)+1 FROM attempts WHERE invoice_id=?",(invoice["id"],)).fetchone()[0]
            active["attempt"] = f"syn_attempt_{invoice['id']}_{number}"
            self.store.insert("attempts",id=active["attempt"],tenant_id=c["tenant"],invoice_id=invoice["id"],method_id=method,
                occurred_at=stamp(time),number=number,result="pending",decline=None,action_id=aid,processing_cost=self.parameters.processing_cost_minor)
        s["active"] = active
        if chosen != "review":
            self.request_decision(time+timedelta(days=self.config.step_interval_days),invoice)

    def on_communication_event(self,time,payload):
        invoice,aid,kind=payload
        self.emit(invoice,time,f"communication_{kind}",{"action_id":aid})

    def window_probability(self,invoice,action,delivered,days):
        c,p = invoice["customer"],self.parameters
        natural = min(.99,max(0,p.natural_recovery_base+p.natural_recovery_reliability_weight*c["reliability"]))
        effect = {"observe":0,"review":0,"retry_day3":p.retry_effect,"email":p.email_effect,
                  "request_update":p.update_effect,"request_authentication":p.authentication_effect}[action]
        if action not in {"observe","review"}:
            effect += SCENARIOS[self.config.scenario][1]
            if action in CONTACT:
                effect = effect*c["willingness"] if delivered else 0
        rate = min(.99,max(0,natural+effect))
        return 1-(1-rate)**(days/30)

    def on_tick(self,time,invoice):
        s,c = self.episode(invoice),invoice["customer"]
        boundary = invoice["time"]+timedelta(days=self.config.recovery_window_days)
        if time > boundary:
            return
        if time < boundary:
            self.schedule(min(boundary,time+timedelta(days=self.config.step_interval_days)),"tick",invoice)
        actual = self.store.db.execute("SELECT status FROM invoices WHERE id=?",(invoice["id"],)).fetchone()[0]
        sub = self.store.db.execute("SELECT status FROM subscriptions WHERE id=?",(c["sub"],)).fetchone()[0]
        if actual != "open" or sub != "active":
            return
        active = s["active"]
        if self.store.db.execute("SELECT 1 FROM attempts WHERE invoice_id=? AND result='unknown'",(invoice["id"],)).fetchone():
            return
        s["tick"] += 1
        chosen = active["selected"] if active else "observe"
        delivered = active["delivered"] if active else False
        draw = self.noise.uniform(invoice["id"],stamp(time),"window_payment")
        days = (time-s["last_tick"]).total_seconds()/86400
        s["last_tick"] = time
        probability = self.window_probability(invoice,chosen,delivered,days)
        if active:
            for alternative in active["eligible"]:
                alt_delivery = self.noise.uniform(active["id"],"delivery") < self.config.delivery_probability
                p = self.window_probability(invoice,alternative,alt_delivery,days)
                self.store.insert("step_oracle",id=f"syn_oracle_{active['id']}_{alternative}",tenant_id=c["tenant"],
                    action_id=active["id"],window_end=stamp(time),alternative=alternative,probability=p,potential_success=int(draw<p))
        if draw < probability:
            self.pay(time,invoice,active)
        elif active and active["attempt"]:
            self.store.update("attempts",active["attempt"],result="failed",decline="insufficient_funds")
            self.emit(invoice,time,"payment_failed")
        s["active"] = None

    def pay(self,time,invoice,active=None):
        c,s = invoice["customer"],self.episode(invoice)
        if self.store.db.execute("SELECT status FROM invoices WHERE id=?",(invoice["id"],)).fetchone()[0] != "open":
            return False
        pending = self.store.db.execute("SELECT id FROM attempts WHERE invoice_id=? AND result IN ('pending','unknown')",(invoice["id"],)).fetchall()
        if any(row["id"] != (active["attempt"] if active else None) for row in pending):
            return False
        if active and active["attempt"]:
            self.store.update("attempts",active["attempt"],result="succeeded")
        else:
            if invoice["decline"] in HARD or invoice["decline"]=="expired_card":
                fresh = f"syn_pm_update_{invoice['id']}"
                self.store.update("payment_methods",c["method"],status="replaced")
                self.store.insert("payment_methods",id=fresh,tenant_id=c["tenant"],customer_id=c["id"],
                                  method_type="card",issuing_country=c["country"],status="active")
                c["method"] = fresh
            number = self.store.db.execute("SELECT max(number)+1 FROM attempts WHERE invoice_id=?",(invoice["id"],)).fetchone()[0]
            self.store.insert("attempts",id=f"syn_attempt_{invoice['id']}_{number}",tenant_id=c["tenant"],invoice_id=invoice["id"],
                method_id=c["method"],occurred_at=stamp(time),number=number,result="succeeded",decline=None,
                action_id=active["id"] if active and active["selected"] not in {"observe","review"} else None,
                processing_cost=self.parameters.processing_cost_minor)
        self.store.update("invoices",invoice["id"],status="paid",amount_paid=invoice["amount"],amount_remaining=0,paid_at=stamp(time))
        self.emit(invoice,time,"payment_succeeded")
        if self.noise.uniform(invoice["id"],"refund") < self.config.refund_probability:
            self.schedule(time+timedelta(days=self.parameters.refund_delay_days),"sequence_refund",invoice)
        return True

    def on_sequence_refund(self,time,invoice):
        self.store.update("invoices",invoice["id"],status="refunded",refund_amount=invoice["amount"])
        self.emit(invoice,time,"refund")

    def on_sequence_outcome(self,time,invoice):
        s,c = self.episode(invoice),invoice["customer"]
        start = s["first_decision"]
        self.cancel_pending(time,invoice,"observation_horizon_closed")
        actual = self.store.db.execute("SELECT * FROM invoices WHERE id=?",(invoice["id"],)).fetchone()
        paid_at = datetime.fromisoformat(s["paid_at"]) if s["paid_at"] else None
        age = (time-start).total_seconds()/86400
        unresolved=self.store.db.execute("SELECT 1 FROM attempts WHERE invoice_id=? AND result IN ('pending','unknown')",(invoice["id"],)).fetchone()
        measured = (not actual["paid_at"] or s["paid_at"] is not None) and (not actual["refund_amount"] or s["refund_at"] is not None) and not s["unknown"] and not unresolved
        labels = {f"recovered_{d}d":int(paid_at is not None and paid_at<=start+timedelta(days=d)) if age>=d and measured else None for d in (7,14,30)}
        end30=stamp(start+timedelta(days=30))
        costs=self.store.db.execute("SELECT coalesce(sum(processing_cost),0) FROM attempts WHERE invoice_id=? AND number>1 AND occurred_at<=?",(invoice["id"],end30)).fetchone()[0]
        comm=self.store.db.execute("SELECT coalesce(sum(c.cost_minor),0) FROM communications c JOIN actions a ON a.id=c.action_id WHERE a.invoice_id=? AND c.sent_at<=?",(invoice["id"],end30)).fetchone()[0]
        gross=invoice["amount"] if paid_at and paid_at<=start+timedelta(days=30) else 0
        refund=invoice["amount"] if s["refund_at"] and s["refund_at"]<=end30 else 0
        retention=self.noise.uniform(invoice["id"],"retention") < max(0,min(1,self.parameters.retention_base+self.parameters.retention_engagement_weight*c["engagement"]-SCENARIOS[self.config.scenario][2]))
        lifecycle = self.store.db.execute("""SELECT after_json FROM subscription_events
            WHERE subscription_id=? AND occurred_at<=? ORDER BY occurred_at DESC,id DESC LIMIT 1""",
            (c["sub"],stamp(start+timedelta(days=90)))).fetchone()
        if lifecycle and json.loads(lifecycle[0])["status"] != "active":
            retention = False
        self.store.insert("outcomes",id=f"syn_outcome_{invoice['id']}",tenant_id=c["tenant"],invoice_id=invoice["id"],
            action_id=s["actions"][0],currency=c["currency"],recovered_at=stamp(paid_at) if paid_at else None,
            gross_recovered=gross,processing_cost=costs,communication_cost=comm,refund_amount=refund,
            net_revenue=gross-costs-comm-refund,**labels,retention_90d=int(retention) if age>=90 and measured else None,
            window_complete=int(age>=30 and measured),observed_until=stamp(time),measurement_status="observed" if measured else "unresolved")
