"""Persistent checkout authority. No credentials, client mode or UI state grants access.

Tables are installed only by the reviewed migration, never on application startup.
The locked singleton also serializes Stripe session creation against owner changes.
"""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import text
from fastapi import HTTPException


def _table(engine, name):
    return ('checkout_control.' if engine.dialect.name == 'postgresql' else '') + name


@contextmanager
def locked(engine):
    if engine is None:
        raise HTTPException(503, 'Checkout mode database unavailable; checkout is CLOSED.')
    try:
        with engine.begin() as conn:
            table = _table(engine, 'mode_state')
            suffix = ' FOR UPDATE' if engine.dialect.name == 'postgresql' else ''
            row = conn.execute(text(f'SELECT * FROM {table} WHERE id=1{suffix}')).mappings().one()
            audit = conn.execute(text(f'SELECT requested_mode FROM {_table(engine, "mode_audit")} WHERE version=:v'),
                                 {'v': row['version']}).scalar_one()
            if audit != row['requested_mode']:
                raise ValueError('audit mismatch')
            if row['requested_mode'] not in ('CLOSED', 'TEST', 'LIVE'):
                raise ValueError('invalid state')
            yield conn, dict(row)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'Checkout mode could not be verified; checkout is CLOSED.') from None


def tester(engine, customer_id, *, connection=None):
    if not engine or not customer_id:
        return None
    try:
        with (nullcontext(connection) if connection is not None else engine.connect()) as conn:
            row = conn.execute(text(f'SELECT email FROM {_table(engine, "test_accounts")} '
                                    'WHERE customer_id=:uid AND enabled=true AND verified_at IS NOT NULL'),
                               {'uid': customer_id}).mappings().first()
            return row['email'] if row else None
    except Exception:
        return None


def status(engine, readiness):
    with locked(engine) as (conn, state):
        count = conn.execute(text(f'SELECT COUNT(*) FROM {_table(engine, "test_accounts")} '
                                  'WHERE enabled=true AND verified_at IS NOT NULL')).scalar_one()
        blockers = list(readiness['test_blockers'])
        if not count:
            blockers.append('No verified authorized TEST account is registered.')
        if not state['test_binding_verified_at']:
            blockers.append('Sandbox provider, webhook and downstream binding evidence has not been verified.')
        requested = state['requested_mode']
        # LIVE is deliberately unavailable in this release. No shared credential,
        # browser request or configuration flag can satisfy separate activation.
        effective = 'TEST' if requested == 'TEST' and not blockers else 'CLOSED'
        return {**readiness, **state, 'effective_mode': effective,
                'test_blockers': blockers, 'test_ready': not blockers,
                'live_activation_available': False,
                'live_blockers': ['Separate verified owner LIVE authorization and payment acceptance required.'],
                'audit_status': 'Versioned database transaction', 'authorized_test_accounts': count}


def apply(engine, *, requested_mode, expected_version, confirmation, readiness):
    if requested_mode == 'LIVE':
        raise HTTPException(403, 'LIVE activation is unavailable pending separate owner authorization and acceptance.')
    if requested_mode not in ('CLOSED', 'TEST') or confirmation != 'APPLY ' + requested_mode:
        raise HTTPException(422, 'Type APPLY followed by the requested mode to confirm.')
    current = status(engine, readiness)
    if requested_mode == 'TEST' and not current['test_ready']:
        raise HTTPException(409, {'message': 'Checkout remains CLOSED.', 'blockers': current['test_blockers']})
    with locked(engine) as (conn, state):
        if state['version'] != expected_version:
            raise HTTPException(409, 'Checkout mode changed. Refresh before applying again.')
        changed_at = datetime.now(timezone.utc).isoformat()
        version = state['version'] + 1
        conn.execute(text(f'INSERT INTO {_table(engine, "mode_audit")} '
                          '(id, version, previous_mode, requested_mode, changed_at, actor) '
                          'VALUES (:id,:version,:previous,:mode,:at,:actor)'),
                     {'id': str(uuid4()), 'version': version, 'previous': state['requested_mode'],
                      'mode': requested_mode, 'at': changed_at, 'actor': 'manufacturing-control-owner'})
        conn.execute(text(f'UPDATE {_table(engine, "mode_state")} SET requested_mode=:mode, '
                          'version=:version, changed_at=:at WHERE id=1'),
                     {'mode': requested_mode, 'version': version, 'at': changed_at})
    return status(engine, readiness)
