from test_checkout_workflow import quote_inputs
"""Database mode authority through the existing payment/drawing routes."""
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import text
import api_app
from checkout_control import status, apply
from test_checkout_workflow import database, checkout_client, checkout_body
from test_owner_sandbox_checkout import sandbox, headers, event_payload, sign

OWNER = {'x-api-key': 'admin-synthetic'}


def change(sandbox, mode, version=1, confirmation=None):
    return sandbox.client.put('/admin/checkout-control', headers=OWNER, json={
        'requested_mode': mode, 'expected_version': version,
        'confirmation': confirmation if confirmation is not None else 'APPLY ' + mode})


@pytest.mark.parametrize('cart', [False, True])
@pytest.mark.parametrize('client_mode', [None, 'owner_test', 'live', 'test'])
def test_closed_blocks_all_creation_regardless_of_header(sandbox, database, cart, client_mode):
    assert change(sandbox, 'CLOSED').json()['effective_mode'] == 'CLOSED'
    auth = headers(mode=False)
    if client_mode:
        auth['x-oplates-checkout-mode'] = client_mode
    body = {'items': [checkout_body()['inputs']]} if cart else checkout_body()
    response = sandbox.client.post('/checkout/cart/create' if cart else '/checkout/create', json=body, headers=auth)
    assert response.status_code == 503
    assert not sandbox.calls
    with database() as db:
        assert db.query(api_app.Order).count() == 0


@pytest.mark.parametrize('auth', [{}, {'x-api-key':'test-ui-key'}, headers('customer')])
def test_customer_cannot_read_or_change_control(sandbox, auth):
    assert sandbox.client.get('/admin/checkout-control', headers=auth).status_code == 401
    assert sandbox.client.put('/admin/checkout-control', headers=auth, json={
        'requested_mode':'TEST','expected_version':1,'confirmation':'APPLY TEST'}).status_code == 401


def test_confirmation_version_audit_persistence_and_live_rejection(sandbox, database):
    assert change(sandbox, 'CLOSED', confirmation='').status_code == 422
    closed = change(sandbox, 'CLOSED').json()
    assert closed['version'] == 2
    assert change(sandbox, 'TEST').status_code == 409  # stale/replay
    enabled = change(sandbox, 'TEST', version=2).json()
    assert enabled['effective_mode'] == 'TEST' and enabled['version'] == 3
    assert sandbox.client.get('/admin/checkout-control', headers=OWNER).json()['effective_mode'] == 'TEST'
    assert change(sandbox, 'LIVE', version=3).status_code == 403
    assert sandbox.client.get('/checkout/availability', headers=headers()).json()['mode'] == 'owner_test'
    with api_app.engine.connect() as conn:
        audit = conn.execute(text('SELECT version,previous_mode,requested_mode FROM mode_audit ORDER BY version')).all()
    assert [tuple(row) for row in audit] == [(1,'TEST','TEST'),(2,'TEST','CLOSED'),(3,'CLOSED','TEST')]
    assert 'rk_test_separate' not in json.dumps(enabled)


def test_missing_binding_or_dependency_remains_closed(sandbox):
    with api_app.engine.begin() as conn:
        conn.execute(text('UPDATE mode_state SET test_binding_verified_at=NULL'))
    response = change(sandbox, 'TEST')
    assert response.status_code == 409
    state = sandbox.client.get('/admin/checkout-control', headers=OWNER).json()
    assert state['effective_mode'] == 'CLOSED'
    assert any('binding evidence' in b for b in state['test_blockers'])


def test_database_failure_cannot_fall_back_to_env_or_header(sandbox, monkeypatch):
    monkeypatch.setattr(api_app, 'checkout_mode_engine', None)
    assert sandbox.client.post('/checkout/create', json=checkout_body(), headers=headers()).status_code == 503
    assert sandbox.client.get('/checkout/availability', headers=headers()).json()['available'] is False
    assert not sandbox.calls


def test_close_between_pricing_and_provider_call_is_rechecked(sandbox, monkeypatch):
    original = api_app._calculate_quote_with_db_knobs
    def calculate(inputs):
        result = original(inputs)
        assert change(sandbox, 'CLOSED').status_code == 200
        return result
    monkeypatch.setattr(api_app, '_calculate_quote_with_db_knobs', calculate)
    assert sandbox.client.post('/checkout/create', json=checkout_body(), headers=headers()).status_code == 503
    assert not sandbox.calls


@pytest.mark.parametrize('cart',[False,True])
def test_paid_test_after_close_exact_drawing_approval_and_no_production(sandbox, database, cart):
    values = quote_inputs(chamfer=False, chamfer_width=None)
    body = {'items':[values,{**values,'quantity':2}]} if cart else checkout_body(inputs=values)
    response = sandbox.client.post('/checkout/cart/create' if cart else '/checkout/create', json=body, headers=headers(mode=False))
    assert response.status_code == 200, response.text
    sid = response.json()['session_id']
    assert sid.startswith('cs_test_')
    assert sandbox.calls[0]['customer_email'] == 'owner@example.test'
    assert all('TEST / NOT A REAL SALE' in item['price_data']['product_data']['name'] for item in sandbox.calls[0]['line_items'])
    sandbox.sessions[sid]['customer_details']['email'] = 'unauthorized@example.test'
    assert change(sandbox,'CLOSED').status_code == 200
    payload = event_payload(sandbox.sessions[sid])
    for expected in ['completed','already_completed']:
        response = sandbox.client.post('/stripe/test/webhook',content=payload,headers=sign(payload,'whsec_test_separate'))
        assert response.status_code == 200, response.text
        assert response.json()['status'] == expected
    with database() as db:
        order = db.query(api_app.Order).one()
        assert order.customer_email == 'owner@example.test'
        assert order.status == 'completed' and api_app._is_owner_test_order(order)
    assert len(sandbox.deliveries[0][1]) == (2 if cart else 1)
    for capture in sandbox.captures:
        result = sandbox.repo.approve(capture['token'],'owner')
        assert result['context']['test_order'] is True
        from frozen_plate.presentation import success_html
        html = success_html(result['context'],result['approval']['approved_at'])
        assert 'NOT A REAL SALE' in html and 'YOUR ORDER IS IN PRODUCTION' not in html
        from frozen_plate.repository import WorkflowError
        with pytest.raises(WorkflowError, match='sourcing is prohibited'):
            sandbox.repo.select_source(result['approval']['revision_id'],'ROGUE_INTERNAL',actor='owner')
    from frozen_plate.control_data import bounded_summary
    summary = bounded_summary(sandbox.client.get('/admin/orders',headers=OWNER).json(),sandbox.repo)
    assert summary['counts']['approved'] == 0
    assert sandbox.client.get('/admin/sales',headers=OWNER).json()['order_count'] == 0
    from final4.automatic import AutomaticStager
    # Metadata scan must exclude approved TEST parents before any generator runs.
    stager = object.__new__(AutomaticStager)
    stager.service = SimpleNamespace(repo=sandbox.repo)
    assert stager.parents() == []

@pytest.mark.parametrize('historical_frozen',[False,True])
def test_preselector_test_completion_and_replay_preserve_frozen_provenance(sandbox,database,monkeypatch,historical_frozen):
    values = quote_inputs(chamfer=False, chamfer_width=None)
    result = sandbox.client.post('/checkout/create',json=checkout_body(inputs=values),headers=headers())
    sid = result.json()['session_id']
    sandbox.sessions[sid]['metadata'].pop('test_recipient')
    with database() as db:
        order = db.query(api_app.Order).one()
        data = dict(order.quote_payload)
        data['_payment'] = {'mode':'owner_test','owner_id':'owner'}
        order.quote_payload = data
        if historical_frozen:
            order.status='completed'
        db.commit()
        oid = order.id
    from frozen_plate import orders
    if historical_frozen:
        original = orders.specification_from_order
        def legacy_adapter(*args,**kwargs):
            spec,source = original(*args,**kwargs)
            source.pop('_payment')
            return spec,source
        monkeypatch.setattr(orders,'specification_from_order',legacy_adapter)
        states = orders.complete_order(sandbox.repo,api_app._frozen_plate_order_snapshot(oid))
        revision_before = sandbox.repo.revision(states[0]['revision_id'])
        monkeypatch.setattr(orders,'specification_from_order',original)
    assert change(sandbox,'CLOSED').status_code == 200
    payload=event_payload(sandbox.sessions[sid])
    response=sandbox.client.post('/stripe/test/webhook',content=payload,headers=sign(payload,'whsec_test_separate'))
    assert response.status_code==200,response.text
    assert all(s['state']=='FROZEN' for s in sandbox.deliveries[-1][1])
    assert sandbox.deliveries[-1][0]['customer_email']=='owner@example.test'
    if historical_frozen:
        assert sandbox.repo.revision(revision_before['id']) == revision_before


def test_customer_api_key_cannot_gain_mode_control_even_if_owner_config_is_misbound(sandbox,monkeypatch):
    monkeypatch.setattr(api_app,'ADMIN_API_KEY','test-ui-key')
    auth={'x-api-key':'test-ui-key'}
    assert sandbox.client.get('/admin/checkout-control',headers=auth).status_code==503
    assert sandbox.client.put('/admin/checkout-control',headers=auth,json={
        'requested_mode':'TEST','expected_version':1,'confirmation':'APPLY TEST'}).status_code==503
