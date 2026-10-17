"""Synthetic isolated sales records; no production or Stripe calls."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON
from sqlalchemy.orm import declarative_base, Session
from fastapi.testclient import TestClient
from owner_sales import aggregate_sales

Base = declarative_base()
class Order(Base):
    __tablename__ = 'sales_fixture'
    id = Column(String, primary_key=True)
    stripe_session_id = Column(String)
    stripe_payment_intent = Column(String)
    last_stripe_event_id = Column(String)
    status = Column(String)
    paid_at = Column(DateTime)
    created_at = Column(DateTime)
    amount_total_cents = Column(Integer)
    quote_payload = Column(JSON)

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()

def add(db, i, **changes):
    values = dict(id=str(i), stripe_session_id=f'cs_live_{i}', stripe_payment_intent=f'pi_{i}',
                  last_stripe_event_id=f'evt_{i}', status='completed', paid_at=NOW,
                  created_at=datetime(2024, 1, 1), amount_total_cents=12345, quote_payload={})
    values.update(changes)
    db.add(Order(**values)); db.flush()

@pytest.mark.parametrize('change', [
    {'stripe_session_id': 'cs_test_abc'}, {'stripe_session_id': None},
    {'stripe_session_id': 'unknown'}, {'stripe_payment_intent': None},
    {'last_stripe_event_id': None}, {'status': 'pending'}, {'status': 'failed'},
    {'paid_at': None}, {'amount_total_cents': 0},
    {'quote_payload': {'_payment': {'mode': 'owner_test'}}},
    {'quote_payload': {'_payment': {'mode': 'test'}}},
    {'quote_payload': {'_payment': {'mode': 'demo'}}},
    {'quote_payload': {'_payment': {'mode': 'unknown'}}},
])
def test_ineligible_never_contributes(db, change):
    add(db, 1, **change)
    result = aggregate_sales(db, Order, now=NOW)
    assert result['total_cents'] == result['order_count'] == 0

@pytest.mark.parametrize('period,grain', [('1y','month'),('6m','month'),('3m','week'),('1m','day')])
def test_all_periods_and_paid_timestamp(db, period, grain):
    add(db, 1)
    add(db, 2, paid_at=datetime(2024,1,1), created_at=NOW)
    result = aggregate_sales(db, Order, period, now=NOW)
    assert result['grain'] == grain
    assert result['total_cents'] == 12345 and result['order_count'] == 1
    assert result['timezone'] == 'UTC'
    assert 'customer' not in str(result)
    assert result['label'] == 'LIVE paid order total'

@pytest.mark.parametrize('field', ['stripe_payment_intent','stripe_session_id','last_stripe_event_id'])
def test_duplicate_payment_session_event_counts_once(db, field):
    add(db, 1)
    add(db, 2, **{field: {'stripe_payment_intent':'pi_1','stripe_session_id':'cs_live_1','last_stripe_event_id':'evt_1'}[field]})
    assert aggregate_sales(db, Order, now=NOW)['order_count'] == 1

def test_full_history_not_snapshot_and_exact_cents(db):
    for i in range(250):
        add(db, i, amount_total_cents=101)
    result = aggregate_sales(db, Order, now=NOW)
    assert result['order_count'] == 250 and result['total_cents'] == 25250

def test_range_boundaries_and_month_buckets(db):
    add(db, 1, paid_at=datetime(2025,11,1))
    add(db, 2, paid_at=datetime(2025,10,31,23,59,59))
    add(db, 3, paid_at=datetime(2026,10,17,12,0,1))
    result = aggregate_sales(db, Order, now=NOW)
    assert len(result['points']) == 12 and result['order_count'] == 1
    assert result['points'][0]['amount_cents'] == 12345

def test_week_starts_monday_and_sums(db):
    add(db, 1, paid_at=datetime(2026,10,11,23,59))
    add(db, 2, paid_at=datetime(2026,10,12))
    points = {p['date']:p for p in aggregate_sales(db, Order, '3m', now=NOW)['points']}
    assert points['2026-10-05']['order_count'] == points['2026-10-12']['order_count'] == 1

def test_sales_endpoint_authorization_and_validation(monkeypatch):
    import api_app
    monkeypatch.setattr(api_app, 'ADMIN_API_KEY', 'fixture-owner')
    client = TestClient(api_app.app)
    for headers in ({}, {'x-api-key':'invalid'}, {'authorization':'Bearer customer'}):
        assert client.get('/admin/sales', headers=headers).status_code == 401
    assert client.get('/admin/sales?period=invalid', headers={'x-api-key':'fixture-owner'}).status_code == 422
