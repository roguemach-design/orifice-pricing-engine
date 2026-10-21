"""Real PostgreSQL gate. Isolated CI database only, never production credentials."""

import os
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.exc import DBAPIError
from journey.provision import provision, verify_access, ROLE
from journey.store import Store, sessions, events, links, reaches, daily
from journey.schema import Event


def test_restricted_postgres_persistence_retention_and_rollback():
    url = os.environ.get("JOURNEY_CI_POSTGRES_URL")
    if not url:
        pytest.skip("Isolated CI PostgreSQL binding not supplied")
    admin = create_engine(url)
    # The CI job owns a fresh disposable database. Never run with production URLs.
    assert admin.url.database == "journey_ci"
    with admin.begin() as db:
        db.execute(text("CREATE TABLE journey_ci_business_sentinel (id integer PRIMARY KEY, evidence text)"))
        db.execute(text("INSERT INTO journey_ci_business_sentinel VALUES (1, 'immutable-ci-evidence')"))
    restricted = create_engine(provision(admin, "synthetic-ci-only-password-32-characters"))
    with admin.connect() as db:
        verify_access(db)
    with restricted.connect() as db:
        assert db.scalar(text("SELECT current_user")) == ROLE
        for statement in (
            "SELECT * FROM journey_ci_business_sentinel",
            "UPDATE journey_ci_business_sentinel SET evidence='wrong'",
            "CREATE TABLE public.not_allowed (id integer)",
            "TRUNCATE journey_events_v1",
        ):
            with pytest.raises(DBAPIError):
                db.execute(text(statement))
            db.rollback()
    now = datetime.now(timezone.utc)
    def event():
        return Event(version=1, event_id=uuid4(), timestamp=now, step="quote",
                     outcome="success", category="none", source="direct")
    store = Store(restricted, "ci-only-signing-secret", initialize=False)
    token = store.start(internal=True)
    assert store.add(token, event())
    restricted.dispose()
    # A new engine/store proves persistence across process-connection lifetimes.
    engine = create_engine(restricted.url)
    store = Store(engine, "ci-only-signing-secret", initialize=False)
    assert store.report(24, True)["funnel"]["quote"] == 1
    assert store.report(24)["funnel"]["quote"] == 0
    store.revoke(token)
    assert not store.report(24, True)["sessions"]
    old = now - timedelta(days=8)
    old_token = store.start(internal=True, now=old)
    store.add(old_token, event(), now=old)
    store.prune()
    with engine.connect() as db:
        for table in (events, links, reaches):
            assert db.scalar(select(func.count()).select_from(table)) == 0
    assert store.report(2160, True)["funnel"]["quote"] == 1
    store.prune(now=now + timedelta(days=91))
    # Rollback compatibility: old application sees unchanged business evidence;
    # analytics is isolated and can be left idle without reversing business state.
    with admin.connect() as db:
        assert db.scalar(text("SELECT evidence FROM journey_ci_business_sentinel")) == "immutable-ci-evidence"
        assert db.scalar(select(func.count()).select_from(daily)) == 0
        assert db.scalar(select(func.count()).select_from(sessions)) == 0
