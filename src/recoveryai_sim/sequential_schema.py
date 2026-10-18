"""Schema 2 extends, rather than mutates, the one-decision schema."""
from .storage import SCHEMA

SCHEMA_V2 = dict(SCHEMA)
SCHEMA_V2["actions"] = SCHEMA["actions"].replace("invoice_id TEXT NOT NULL UNIQUE", "invoice_id TEXT NOT NULL") + ", step INTEGER NOT NULL CHECK(step>0), previous_action_id TEXT REFERENCES actions(id), source_observation_id TEXT NOT NULL REFERENCES observations(id), sources_json TEXT NOT NULL, UNIQUE(invoice_id,step)"
SCHEMA_V2["events"] = SCHEMA["events"] + ", payload_json TEXT NOT NULL DEFAULT '{}'"
SCHEMA_V2["outcomes"] = SCHEMA["outcomes"] + ", measurement_status TEXT NOT NULL"
SCHEMA_V2.update({
    "observations": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, invoice_id TEXT NOT NULL REFERENCES invoices(id), event_id TEXT NOT NULL UNIQUE REFERENCES events(id), occurred_at TEXT NOT NULL, available_at TEXT NOT NULL, event_type TEXT NOT NULL, applied INTEGER NOT NULL, payload_json TEXT NOT NULL",
    "action_results": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE REFERENCES actions(id), result TEXT NOT NULL, reason TEXT, recorded_at TEXT NOT NULL, processing_cost INTEGER NOT NULL DEFAULT 0, communication_cost INTEGER NOT NULL DEFAULT 0, method_id TEXT REFERENCES payment_methods(id)",
    "step_oracle": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, action_id TEXT NOT NULL REFERENCES actions(id), window_end TEXT NOT NULL, alternative TEXT NOT NULL, probability REAL NOT NULL, potential_success INTEGER NOT NULL, UNIQUE(action_id,alternative)",
})
