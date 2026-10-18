"""Explicit, versioned legal transitions for the sequential simulator."""
TRANSITIONS = {
    "invoices": {"open": {"paid", "voided", "written_off"}, "paid": {"refunded"},
                 "refunded": set(), "voided": set(), "written_off": set()},
    "subscriptions": {"active": {"paused", "cancelled", "unpaid"},
                      "paused": {"active", "cancelled"}, "unpaid": {"active", "cancelled"}, "cancelled": set()},
    "payment_methods": {"active": {"replaced", "expired", "revoked"}, "replaced": set(), "expired": set(), "revoked": set()},
    "actions": {"scheduled": {"executed", "observed", "review_only", "cancelled", "blocked", "censored"},
                "executed": set(), "observed": set(), "review_only": set(), "cancelled": set(), "blocked": set(), "censored": set()},
    "attempts": {"pending": {"succeeded", "failed", "unknown"}, "unknown": {"succeeded", "failed"},
                 "succeeded": set(), "failed": set()},
}


def require_transition(table, old, new):
    if table not in TRANSITIONS or old not in TRANSITIONS[table] or new not in TRANSITIONS[table]:
        raise ValueError(f"Unknown {table} state")
    if old != new and new not in TRANSITIONS[table][old]:
        raise ValueError(f"Illegal {table} transition: {old} -> {new}")


def install_triggers(db):
    """Also enforce transitions on direct SQL writes; no wall-clock timestamps."""
    for table, states in TRANSITIONS.items():
        column = "result" if table == "attempts" else "status"
        allowed = " OR ".join(f"(OLD.{column}='{old}' AND NEW.{column}='{new}')"
                              for old, targets in states.items() for new in sorted(targets))
        names = ",".join(f"'{name}'" for name in states)
        db.execute(f"""CREATE TRIGGER legal_{table}_update BEFORE UPDATE OF {column} ON {table}
            WHEN NEW.{column}<>OLD.{column} AND NOT ({allowed})
            BEGIN SELECT RAISE(ABORT,'illegal state transition'); END""")
        db.execute(f"""CREATE TRIGGER legal_{table}_insert BEFORE INSERT ON {table}
            WHEN NEW.{column} NOT IN ({names})
            BEGIN SELECT RAISE(ABORT,'unknown state'); END""")
