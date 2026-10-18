"""Fixed, pre-action cohort and 30-day financial return for policy evaluation.

No oracle values are read. Includes failed invoices with no recovery decisions.
Administrative maturity is independent of payment outcome and policy choice.
"""
from datetime import datetime,timedelta,timezone
import json
from .engine import add_months,stamp
from .storage import encode

CONTRACT="failure-anchored-30d-v1"


def causal_episodes(db,config):
    observed_until=add_months(datetime.fromisoformat(config.start).astimezone(timezone.utc),config.months)
    rows=db.execute("""SELECT i.*,first.occurred_at AS failure_at,s.customer_id,c.merchant_id FROM invoices i
        JOIN attempts first ON first.invoice_id=i.id AND first.number=1 AND first.result='failed'
        JOIN subscriptions s ON s.id=i.subscription_id AND s.tenant_id=i.tenant_id
        JOIN customers c ON c.id=s.customer_id AND c.tenant_id=i.tenant_id ORDER BY i.id""")
    for row in rows:
        if row["amount_paid"] not in (0,row["amount_due"]) or row["refund_amount"] not in (0,row["amount_paid"]):
            raise ValueError("Partial payment/refund requires a newer causal return contract")
        start=datetime.fromisoformat(row["failure_at"])
        end=start+timedelta(days=30)
        # Reserve the entire known maximum callback delay, even for early success.
        mature_after=end+timedelta(days=config.parameters.webhook_max_delay_days)
        status="mature" if observed_until>=mature_after else "censored"
        events=db.execute("""SELECT e.event_type,e.occurred_at,e.payload_json,o.available_at
            FROM events e LEFT JOIN observations o ON o.event_id=e.id AND o.tenant_id=e.tenant_id
            WHERE e.invoice_id=? AND e.tenant_id=? AND e.occurred_at<=?""",
            (row["id"],row["tenant_id"],stamp(end))).fetchall()
        seen=lambda e:e["available_at"] is not None and e["available_at"]<=stamp(observed_until)
        failure_seen=any(e["event_type"]=="sim.payment_failed" and json.loads(e["payload_json"]).get("attempt_number")==1 and seen(e) for e in events)
        paid=row["paid_at"] is not None and row["paid_at"]<=stamp(end)
        success_seen=any(e["event_type"]=="sim.payment_succeeded" and seen(e) for e in events)
        refunded=any(e["event_type"]=="sim.refund" for e in events)
        refund_seen=any(e["event_type"]=="sim.refund" and seen(e) for e in events)
        unresolved=db.execute("SELECT 1 FROM attempts WHERE invoice_id=? AND tenant_id=? AND occurred_at<=? AND result IN ('pending','unknown')",
            (row["id"],row["tenant_id"],stamp(end))).fetchone()
        if status=="mature" and unresolved:
            status="unresolved"
        if status=="mature" and (not failure_seen or (paid and not success_seen) or (refunded and not refund_seen)):
            status="unobserved_provider"
        processing=db.execute("SELECT coalesce(sum(processing_cost),0) FROM attempts WHERE invoice_id=? AND tenant_id=? AND number>1 AND occurred_at<=?",
            (row["id"],row["tenant_id"],stamp(end))).fetchone()[0]
        contact=db.execute("""SELECT coalesce(sum(c.cost_minor),0) FROM communications c JOIN actions a ON a.id=c.action_id
            WHERE a.invoice_id=? AND a.tenant_id=? AND c.sent_at<=?""",(row["id"],row["tenant_id"],stamp(end))).fetchone()[0]
        if processing<0 or contact<0:
            raise ValueError("Negative cost in causal episode ledger")
        count=db.execute("SELECT count(*) FROM actions WHERE invoice_id=? AND tenant_id=?",(row["id"],row["tenant_id"])).fetchone()[0]
        gross=row["amount_due"] if paid else 0
        refund=row["amount_due"] if refunded else 0
        net=gross-refund-processing-contact
        yield {"contract":CONTRACT,"synthetic":True,"billable":False,"invoice_id":row["id"],"tenant_id":row["tenant_id"],
            "merchant_id":row["merchant_id"],"customer_id":row["customer_id"],"currency":row["currency"],
            "amount_due_minor":row["amount_due"],"failure_at":row["failure_at"],"financial_deadline":stamp(end),
            "mature_after":stamp(mature_after),"observed_until":stamp(observed_until),"status":status,"decision_count":count,
            "gross_recovered_minor":gross if status=="mature" else None,"refund_minor":refund if status=="mature" else None,
            "processing_cost_minor":processing if status=="mature" else None,"communication_cost_minor":contact if status=="mature" else None,
            "reward_minor":net if status=="mature" else None,"recovered_30d":int(paid) if status=="mature" else None,
            "restricted_unpaid_days":min(30,(datetime.fromisoformat(row["paid_at"])-start).total_seconds()/86400) if paid and status=="mature" else 30 if status=="mature" else None}


def export_causal_episodes(db,root,config):
    folder=root/"evaluation"
    folder.mkdir()
    with (folder/"causal_episodes.jsonl").open("w",encoding="utf-8",newline="\n") as output:
        for row in causal_episodes(db,config):
            output.write(encode(row)+"\n")
