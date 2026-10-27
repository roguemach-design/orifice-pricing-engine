"""No real credentials/provider writes: exercise auth lifecycle and write barriers."""
import base64
import json
import time
from types import SimpleNamespace
import httpx
import pytest
import auth
from test_auth_security import AttrDict


def token(exp=None):
    data = json.dumps({"exp": exp or time.time() + 3600, "sub": "synthetic-customer"})
    return "synthetic." + base64.urlsafe_b64encode(data.encode()).decode().rstrip("=") + ".signature"


class Paused(BaseException):
    pass


@pytest.fixture
def page(monkeypatch):
    state = AttrDict(auth={"access_token": token(), "refresh_token": "synthetic-refresh",
                          "email": "buyer@example.test", "user": None},
                     cart=[{"quantity": 2}], configuration={"paddle_dia": 3})
    def stop():
        raise Paused()
    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=state, context=SimpleNamespace(cookies={}),
        stop=stop, info=lambda *a: None, warning=lambda *a: None, button=lambda *a, **k: False))
    return state


def test_disposable_sdk_cannot_rotate_in_background(monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://synthetic.invalid")
    monkeypatch.setattr(auth, "SUPABASE_ANON_KEY", "synthetic-public")
    monkeypatch.setattr(auth, "create_client", lambda *a, **kw: calls.append(kw))
    auth.sb()
    options = calls[0]["options"]
    assert options.auto_refresh_token is False and options.persist_session is False


def test_browser_ack_and_readback_are_required_before_continuation(page, monkeypatch):
    payload = dict(page.auth)
    monkeypatch.setattr(auth, "_cookie_component", lambda **kw: None)
    with pytest.raises(Paused):
        auth._cookie_set(payload)
    operation = page["_auth_cookie_pending"]["id"]
    # A set acknowledgment alone is insufficient when the browser rejected it.
    monkeypatch.setattr(auth, "_cookie_component", lambda **kw: True if kw["method"] == "set" else {})
    with pytest.raises(Paused):
        auth._restore_auth_from_cookie_if_needed()
    assert page["_auth_cookie_pending"]["id"] == operation
    monkeypatch.setattr(auth, "_cookie_component", lambda **kw: True if kw["method"] == "set" else {auth.COOKIE_NAME: payload})
    auth._restore_auth_from_cookie_if_needed()
    assert "_auth_cookie_pending" not in page
    assert page.cart == [{"quantity": 2}] and page.configuration == {"paddle_dia": 3}


def test_cross_site_return_restores_browser_cookie_and_checks_provider(page, monkeypatch):
    saved = dict(page.auth)
    page.auth = {}
    monkeypatch.setattr(auth, "_cookie_component", lambda **kw: {auth.COOKIE_NAME: saved})
    monkeypatch.setattr(auth, "_cookie_set", lambda value: None)
    calls = []
    def refresh(value):
        calls.append(value)
        return {"session": {"access_token": token(), "refresh_token": "rotated"}}
    monkeypatch.setattr(auth, "sb", lambda: SimpleNamespace(auth=SimpleNamespace(refresh_session=refresh)))
    assert auth.is_logged_in()
    assert calls == [saved["refresh_token"]]
    assert page.auth["refresh_token"] == "rotated"


def test_revoked_restored_session_is_inaccessible_even_before_jwt_expiry(page, monkeypatch):
    page["_auth_restore_check"] = True
    def revoked(value):
        raise SimpleAuthError(400)
    monkeypatch.setattr(auth, "sb", lambda: SimpleNamespace(auth=SimpleNamespace(refresh_session=revoked)))
    monkeypatch.setattr(auth, "_cookie_clear", lambda: None)
    assert not auth.is_logged_in()
    assert auth.auth_headers() == {}
    assert page.cart and page.configuration


class SimpleAuthError(Exception):
    def __init__(self, status):
        self.status = status


@pytest.mark.parametrize("error", [httpx.ReadTimeout("synthetic outage"), SimpleAuthError(429), SimpleAuthError(503)])
def test_transient_refresh_retains_retry_but_never_uses_expired_jwt(page, monkeypatch, error):
    page.auth["access_token"] = token(time.time() - 1)
    def unavailable(value):
        raise error
    monkeypatch.setattr(auth, "sb", lambda: SimpleNamespace(auth=SimpleNamespace(refresh_session=unavailable)))
    assert not auth.is_logged_in()
    assert auth.auth_headers() == {}
    assert page.auth["refresh_token"] == "synthetic-refresh"
    assert page.cart and page.configuration


def test_logout_revokes_current_provider_session_and_confirms_browser_removal(page, monkeypatch):
    calls = []
    client = SimpleNamespace(auth=SimpleNamespace(set_session=lambda *a: calls.append("bind"),
        sign_out=lambda opts: calls.append(opts)))
    monkeypatch.setattr(auth, "sb", lambda: client)
    monkeypatch.setattr(auth, "_cookie_component", lambda **kw: True if kw["method"] == "delete" else {})
    monkeypatch.setattr(auth.st, "rerun", lambda: None, raising=False)
    auth.logout()
    assert calls == ["bind", {"scope": "local"}]
    assert auth.auth_headers() == {} and not page.auth["refresh_token"]
    assert page.cart and page.configuration
