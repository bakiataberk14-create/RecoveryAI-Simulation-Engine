"""Streaming relational storage; oracle tables never enter exported training views."""
import json
from pathlib import Path
import sqlite3

SCHEMA = {
    "merchants": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL UNIQUE, country TEXT NOT NULL, currency TEXT NOT NULL, industry TEXT NOT NULL, provider TEXT NOT NULL",
    "customers": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, merchant_id TEXT NOT NULL REFERENCES merchants(id), signup_at TEXT NOT NULL, consent INTEGER NOT NULL, engagement REAL NOT NULL",
    "subscriptions": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id), interval_months INTEGER NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, start_at TEXT NOT NULL, status TEXT NOT NULL",
    "payment_methods": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, customer_id TEXT NOT NULL REFERENCES customers(id), method_type TEXT NOT NULL, issuing_country TEXT NOT NULL, status TEXT NOT NULL",
    "invoices": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subscription_id TEXT NOT NULL REFERENCES subscriptions(id), currency TEXT NOT NULL, amount_due INTEGER NOT NULL CHECK(amount_due>0), amount_paid INTEGER NOT NULL DEFAULT 0, amount_remaining INTEGER NOT NULL, refund_amount INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, paid_at TEXT, status TEXT NOT NULL, CHECK(amount_paid+amount_remaining=amount_due), CHECK(refund_amount>=0 AND refund_amount<=amount_paid)",
    "attempts": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, invoice_id TEXT NOT NULL REFERENCES invoices(id), method_id TEXT NOT NULL REFERENCES payment_methods(id), occurred_at TEXT NOT NULL, number INTEGER NOT NULL, result TEXT NOT NULL, decline TEXT, action_id TEXT REFERENCES actions(id), processing_cost INTEGER NOT NULL, UNIQUE(invoice_id,number)",
    "actions": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, invoice_id TEXT NOT NULL UNIQUE REFERENCES invoices(id), customer_id TEXT NOT NULL REFERENCES customers(id), decision_at TEXT NOT NULL, features_json TEXT NOT NULL, eligible_json TEXT NOT NULL, selected TEXT NOT NULL, propensity REAL NOT NULL CHECK(propensity>0 AND propensity<=1), policy TEXT NOT NULL, policy_version TEXT NOT NULL, rule_version TEXT NOT NULL, execution_at TEXT, status TEXT NOT NULL",
    "communications": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE REFERENCES actions(id), sent_at TEXT NOT NULL, delivered INTEGER NOT NULL, opened INTEGER NOT NULL, clicked INTEGER NOT NULL, cost_minor INTEGER NOT NULL",
    "outcomes": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, invoice_id TEXT NOT NULL UNIQUE REFERENCES invoices(id), action_id TEXT NOT NULL UNIQUE REFERENCES actions(id), currency TEXT NOT NULL, recovered_at TEXT, gross_recovered INTEGER NOT NULL, processing_cost INTEGER NOT NULL, communication_cost INTEGER NOT NULL, refund_amount INTEGER NOT NULL, net_revenue INTEGER NOT NULL, recovered_7d INTEGER, recovered_14d INTEGER, recovered_30d INTEGER, retention_90d INTEGER, window_complete INTEGER NOT NULL, observed_until TEXT NOT NULL",
    "events": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, invoice_id TEXT NOT NULL REFERENCES invoices(id), occurred_at TEXT NOT NULL, event_type TEXT NOT NULL, provider_reference_type TEXT, namespace TEXT NOT NULL DEFAULT 'simulation', synthetic INTEGER NOT NULL DEFAULT 1 CHECK(synthetic=1)",
    "deliveries": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, event_id TEXT NOT NULL REFERENCES events(id), delivered_at TEXT NOT NULL",
    "oracle": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, action_id TEXT NOT NULL REFERENCES actions(id), action TEXT NOT NULL, recovery_day INTEGER, retained_90d INTEGER NOT NULL, refund_day INTEGER, reward_minor INTEGER NOT NULL, latent_reliability REAL NOT NULL, UNIQUE(action_id,action)",
    "oracle_world": "id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, merchant_effect REAL NOT NULL, reliability REAL NOT NULL, willingness REAL NOT NULL",
}
ORACLE_TABLES = {"oracle", "oracle_world", "step_oracle"}


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path: Path, schema_version="1"):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.schema = SCHEMA
        if schema_version == "2":
            from .sequential_schema import SCHEMA_V2
            self.schema = SCHEMA_V2
        for table, ddl in self.schema.items():
            self.db.execute(f"CREATE TABLE {table} ({ddl})")
        self.db.execute("CREATE INDEX events_invoice ON events(invoice_id)")
        self.db.execute("CREATE INDEX deliveries_event ON deliveries(event_id)")
        self.db.execute("CREATE INDEX methods_customer ON payment_methods(customer_id)")
        self.db.execute("""CREATE TRIGGER immutable_decision BEFORE UPDATE OF
            features_json,eligible_json,selected,propensity,policy,policy_version,rule_version,decision_at
            ON actions BEGIN SELECT RAISE(ABORT,'immutable decision snapshot'); END""")
        for table in ("events", "oracle", "oracle_world"):
            for operation in ("UPDATE", "DELETE"):
                self.db.execute(f"CREATE TRIGGER immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'append-only evidence'); END")
        if schema_version == "2":
            from .state_machine import install_triggers
            install_triggers(self.db)
            self.db.execute("CREATE INDEX observations_invoice ON observations(invoice_id,available_at)")
            self.db.execute("CREATE INDEX subscriptions_customer ON subscriptions(customer_id)")
            self.db.execute("CREATE INDEX invoices_subscription ON invoices(subscription_id)")
            self.db.execute("""CREATE TRIGGER immutable_invoice_terms BEFORE UPDATE OF
                tenant_id,subscription_id,currency,amount_due,created_at ON invoices
                BEGIN SELECT RAISE(ABORT,'immutable invoice terms'); END""")
            self.db.execute("""CREATE TRIGGER immutable_sequence BEFORE UPDATE OF tenant_id,invoice_id,customer_id,step,previous_action_id,
                source_observation_id,sources_json ON actions BEGIN SELECT RAISE(ABORT,'immutable sequence'); END""")
            for table in ("observations", "action_results", "step_oracle", "subscription_events", "renewal_slots"):
                for operation in ("UPDATE", "DELETE"):
                    self.db.execute(f"CREATE TRIGGER immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'append-only evidence'); END")

    def insert(self, table, **values):
        if table not in self.schema:
            raise ValueError("Unknown table")
        columns = ",".join(values)
        self.db.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))

    def update(self, table, record_id, **values):
        if table not in self.schema:
            raise ValueError("Unknown table")
        self.db.execute(f"UPDATE {table} SET {','.join(k+'=?' for k in values)} WHERE id=?", (*values.values(), record_id))


def export_tables(db, root: Path, parquet=False, schema=None):
    if parquet:
        import pyarrow as pa
        import pyarrow.parquet as pq
    counts = {}
    for table in (schema or SCHEMA):
        folder = root / ("oracle" if table in ORACLE_TABLES else "operational")
        folder.mkdir(parents=True, exist_ok=True)
        cursor = db.execute(f"SELECT * FROM {table} ORDER BY id")
        names = [d[0] for d in cursor.description]
        count = 0
        writer = None
        if parquet:
            types = {"TEXT": pa.string(), "INTEGER": pa.int64(), "REAL": pa.float64()}
            schema = pa.schema([(r[1], types[r[2]]) for r in db.execute(f"PRAGMA table_info({table})")])
            writer = pq.ParquetWriter(folder / f"{table}.parquet", schema, compression="zstd")
        with (folder / f"{table}.jsonl").open("w", encoding="utf-8", newline="\n") as output:
            while rows := cursor.fetchmany(2048):
                records = [dict(zip(names, row)) for row in rows]
                for record in records:
                    output.write(encode(record) + "\n")
                if writer:
                    writer.write_table(pa.Table.from_pylist(records, schema=schema))
                count += len(records)
        if writer:
            writer.close()
        counts[table] = count
    return counts
