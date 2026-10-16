from pathlib import Path
from unittest.mock import Mock
import pytest
import requests
from streamlit.testing.v1 import AppTest
import legacy_owner_auth as auth

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('API_BASE', 'https://api.example.test')
    monkeypatch.setenv('ADMIN_API_KEY', 'must-never-be-used')
    auth._attempts.clear()
    cfg = {'_version': 'isolated-v1', 'material_enabled': {'304': True},
           'thickness_enabled_by_material': {'304': {'0.125': True}},
           'lead_time_enabled': {'14': True}, 'default_lead_time_days': 14,
           'price_per_sq_in': {'304': {'0.125': 0.13}}}
    calls = []
    def response(status, body):
        r = Mock(status_code=status)
        r.json.return_value = body
        return r
    def login(url, **kwargs):
        calls.append(('LOGIN', url, kwargs))
        return response(200, cfg) if kwargs['headers']['x-api-key'] == 'fixture-owner' else response(401, {})
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith('/admin/config'):
            return response(200, cfg if method == 'GET' else {'ok': True})
        if url.endswith('/admin/config/reset'):
            return response(200, {'ok': True})
        return response(200, [])
    monkeypatch.setattr(auth.requests, 'get', login)
    monkeypatch.setattr(auth.requests, 'request', request)
    return calls

def app():
    return AppTest.from_file(str(ROOT / 'admin_app.py'), default_timeout=15).run()

def unlock(a, key='fixture-owner'):
    next(t for t in a.text_input if t.label == 'Owner credential').set_value(key)
    next(b for b in a.button if b.label == 'Unlock').click().run()
    return a

def test_unauthenticated_and_wrong_credential_never_load_data(setup):
    a = app()
    assert not a.exception and not setup
    assert not a.get('dataframe')
    unlock(a, 'wrong-owner')
    assert len(setup) == 1 and setup[0][0] == 'LOGIN'
    assert 'legacy_owner_session' not in a.session_state
    assert not a.get('dataframe')

def test_verified_session_reads_config_orders_and_lock_clears_everything(setup):
    a = unlock(app())
    assert not a.exception
    assert any(c[1].endswith('/admin/orders') for c in setup)
    assert all(c[2]['headers']['x-api-key'] == 'fixture-owner' for c in setup)
    assert all(c[2]['allow_redirects'] is False for c in setup)
    assert not any(c[0] in ('PUT', 'POST') for c in setup)
    assert a.session_state['legacy_config_snapshot']['_version'] == 'isolated-v1'
    next(b for b in a.button if b.label == 'Lock').click().run()
    assert not a.exception
    assert 'legacy_owner_session' not in a.session_state
    assert 'legacy_config_snapshot' not in a.session_state
    count = len(setup)
    a.run()
    assert len(setup) == count
    fresh = app()
    assert len(setup) == count and 'legacy_owner_session' not in fresh.session_state

def test_authentication_attempt_limit_survives_reruns(setup):
    a = app()
    for _ in range(7):
        unlock(a, 'wrong')
    assert len(setup) == 5
    assert any('Too many' in e.value for e in a.error)

def test_expired_session_revoked_before_request(setup):
    a = unlock(app())
    a.session_state['legacy_owner_session']['expires'] = 0
    count = len(setup)
    a.run()
    assert not a.exception and len(setup) == count
    assert 'legacy_config_snapshot' not in a.session_state

def test_save_and_reset_require_confirmation_and_send_version(setup):
    a = unlock(app())
    save = next(b for b in a.button if b.label == '💾 Save pricing knobs')
    reset = next(b for b in a.button if b.label == '♻️ Reset knobs to defaults')
    assert save.disabled and reset.disabled
    next(c for c in a.checkbox if c.label.startswith('I confirm')).check().run()
    next(b for b in a.button if b.label == '💾 Save pricing knobs').click().run()
    assert not a.exception
    write = next(c for c in setup if c[0] == 'PUT')
    assert write[2]['json']['_version'] == 'isolated-v1'
    assert write[2]['json']['_confirmation'] == 'SAVE CHANGES'
    next(t for t in a.text_input if t.label.startswith('Type RESET')).set_value('RESET DEFAULTS').run()
    next(b for b in a.button if b.label == '♻️ Reset knobs to defaults').click().run()
    assert not a.exception
    reset = next(c for c in setup if c[0] == 'POST')
    assert reset[2]['json'] == {'_version': 'isolated-v1', '_confirmation': 'RESET DEFAULTS'}

def test_api_rejection_clears_session(setup, monkeypatch):
    a = unlock(app())
    monkeypatch.setattr(auth.requests, 'request', lambda *a, **kw: Mock(status_code=401))
    a.run()
    assert not a.exception
    assert 'legacy_owner_session' not in a.session_state
    assert 'legacy_config_snapshot' not in a.session_state

def test_transport_failure_is_sanitized(setup, monkeypatch):
    def fail(*a, **kw):
        raise requests.ConnectionError('sensitive-transport-marker')
    monkeypatch.setattr(auth.requests, 'get', fail)
    a = unlock(app())
    assert not a.exception
    assert 'sensitive-transport-marker' not in str(a)
    assert 'legacy_owner_session' not in a.session_state

def test_single_route_disables_pages_directory():
    source = (ROOT / 'admin_app.py').read_text()
    assert 'st.navigation([st.Page(' in source
    assert (ROOT / 'legacy_admin_ui.py').read_text().index('require_owner()') < (ROOT / 'legacy_admin_ui.py').read_text().index('api_get("/admin/config")')

def test_unauthenticated_transport_call_is_blocked(monkeypatch):
    monkeypatch.setattr(auth.st, 'session_state', {})
    request = Mock()
    monkeypatch.setattr(auth.requests, 'request', request)
    with pytest.raises(auth.OwnerAccessError):
        auth.owner_request('GET', '/admin/orders')
    request.assert_not_called()

def test_global_attempt_limit_applies_to_fresh_sessions(monkeypatch):
    monkeypatch.setattr(auth.st, 'session_state', {})
    auth._attempts.clear()
    for _ in range(auth.GLOBAL_LIMIT):
        auth.st.session_state.clear()
        assert auth.allow_attempt()
    auth.st.session_state.clear()
    assert not auth.allow_attempt()
    auth._attempts.clear()

@pytest.mark.parametrize('base', ['http://api.example.test', 'https://user:secret@api.example.test', 'https://api.example.test?key=secret'])
def test_unsafe_api_target_rejected_before_credentials_sent(setup, monkeypatch, base):
    monkeypatch.setenv('API_BASE', base)
    a = app()
    assert not a.exception and not setup
    assert any('configuration is unavailable' in e.value for e in a.error)

def test_redirect_does_not_authenticate(setup, monkeypatch):
    monkeypatch.setattr(auth.requests, 'get', lambda *a, **kw: Mock(status_code=302))
    a = unlock(app())
    assert not a.exception and 'legacy_owner_session' not in a.session_state
