"""Explicit disposable database setup. Never imported by application code."""
from sqlalchemy import text


def install_control(engine, mode='TEST', accepted=True):
    with engine.begin() as conn:
        for statement in (
            "CREATE TABLE mode_state (id INTEGER PRIMARY KEY, requested_mode TEXT NOT NULL, version INTEGER NOT NULL, changed_at TEXT NOT NULL, test_binding_verified_at TEXT)",
            "CREATE TABLE mode_audit (id TEXT PRIMARY KEY, version INTEGER UNIQUE, previous_mode TEXT, requested_mode TEXT, changed_at TEXT, actor TEXT)",
            "CREATE TABLE test_accounts (customer_id TEXT PRIMARY KEY, email TEXT UNIQUE, enabled BOOLEAN, verified_at TEXT)",
        ):
            conn.execute(text(statement))
        conn.execute(text('INSERT INTO mode_state VALUES (1,:mode,1,:at,:accepted)'),
                     {'mode': mode, 'at': '2026-10-27T12:00:00+00:00', 'accepted': '2026-10-27' if accepted else None})
        conn.execute(text("INSERT INTO mode_audit VALUES ('initial',1,:mode,:mode,'2026-10-27','fixture')"), {'mode':mode})
        for uid in ('owner','signed-customer','owner-test','verified-user','verified-owner','owner-user','customer-a','customer-b','synthetic-owner'):
            conn.execute(text('INSERT INTO test_accounts VALUES (:uid,:email,true,:at)'),
                         {'uid':uid,'email':uid+'@example.test','at':'2026-10-27'})
