"""Offline operational consumer: duplicate and out-of-order delivery is harmless."""
class ReplayLedger:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.seen = {}
        self.paid = set()
        self.refunded = set()

    def apply(self, event):
        if event["tenant_id"] != self.tenant_id or event["synthetic"] != 1:
            raise ValueError("Tenant/environment boundary violation")
        signature = (event["invoice_id"], event["event_type"], event["occurred_at"])
        if event["id"] in self.seen:
            if self.seen[event["id"]] != signature:
                raise ValueError("Conflicting duplicate event")
            return False
        self.seen[event["id"]] = signature
        if event["event_type"] == "sim.payment_succeeded":
            self.paid.add(event["invoice_id"])
        if event["event_type"] == "sim.refund":
            self.refunded.add(event["invoice_id"])
        return True

    @property
    def settled(self):
        return self.paid - self.refunded
