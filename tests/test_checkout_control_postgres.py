"""Actual PostgreSQL serialization/RLS/column grants on disposable loopback CI."""
import os
from pathlib import Path
from threading import Event
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from checkout_control import status, apply, locked, tester as authorized_tester


def test_real_postgres_migration_authority_concurrency_and_restarts():
    url = os.environ.get('JOURNEY_CI_POSTGRES_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL CI database not configured')
    assert make_url(url).host in {'localhost','127.0.0.1'}
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text('CREATE ROLE frozen_plate_production_api NOLOGIN NOBYPASSRLS'))
        conn.execute(text(Path('migrations/checkout_control.sql').read_text().replace('BEGIN;','').replace('COMMIT;','')))
        conn.execute(text("INSERT INTO checkout_control.test_accounts VALUES ('tester','tester@example.test',true,now())"))
        conn.execute(text('UPDATE checkout_control.mode_state SET test_binding_verified_at=now()'))
    def restricted_engine(pool_size=2):
        engine = create_engine(url, pool_size=pool_size, max_overflow=0, pool_timeout=1)
        @event.listens_for(engine, 'connect')
        def role(connection, record):
            cursor = connection.cursor()
            cursor.execute('SET ROLE frozen_plate_production_api')
            connection.commit()
            cursor.close()
        return engine
    engine = restricted_engine()
    ready = {'test_blockers':[]}
    assert status(engine,ready)['effective_mode'] == 'CLOSED'
    for sql in (
        'DELETE FROM checkout_control.mode_state',
        'UPDATE checkout_control.mode_state SET test_binding_verified_at=now()',
        'UPDATE checkout_control.test_accounts SET enabled=true',
        'UPDATE checkout_control.mode_audit SET requested_mode=\'LIVE\'',
        'DELETE FROM checkout_control.mode_audit',
    ):
        with engine.connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text(sql))
    enabled = apply(engine,requested_mode='TEST',expected_version=1,confirmation='APPLY TEST',readiness=ready)
    assert enabled['effective_mode'] == 'TEST'
    single_connection = restricted_engine(pool_size=1)
    with locked(single_connection) as (connection, _):
        assert authorized_tester(single_connection, 'tester', connection=connection) == 'tester@example.test'
    single_connection.dispose()
    engine.dispose()
    engine = restricted_engine()
    assert status(engine,ready)['version'] == 2
    # Session creation owns the same row lock while it contacts Stripe. A close
    # waits for that in-flight creation, then all later creations observe CLOSED.
    started, release, closing = Event(), Event(), Event()
    def session_creation():
        with locked(engine) as (connection, state):
            assert authorized_tester(engine, "tester", connection=connection) == "tester@example.test"
            assert state['requested_mode'] == 'TEST'
            started.set()
            assert release.wait(10)
    def close():
        closing.set()
        return apply(engine,requested_mode='CLOSED',expected_version=2,confirmation='APPLY CLOSED',readiness=ready)
    with ThreadPoolExecutor(max_workers=2) as pool:
        creating = pool.submit(session_creation)
        assert started.wait(5)
        closing_result = pool.submit(close)
        assert closing.wait(5)
        assert not closing_result.done()
        release.set()
        creating.result(timeout=10)
        assert closing_result.result(timeout=10)['effective_mode'] == 'CLOSED'
    # Two owner saves with the same version cannot both apply.
    def competing_save():
        try:
            return apply(engine,requested_mode='TEST',expected_version=3,confirmation='APPLY TEST',readiness=ready)['version']
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: competing_save(),range(2))) == [4,409]
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM checkout_control.mode_audit')) == 4
    engine.dispose()
    # No drops: this disposable Actions database disappears with the CI job.
    admin.dispose()
