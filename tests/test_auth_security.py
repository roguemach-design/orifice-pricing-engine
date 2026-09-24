from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_app
import auth

ROOT = Path(__file__).resolve().parents[1]


class AttrDict(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def test_supabase_jwt_is_verified_with_key_issuer_audience_and_expiry(monkeypatch):
    calls = {}

    class FakeJwkClient:
        def get_signing_key_from_jwt(self, token):
            calls["signing_token"] = token
            return SimpleNamespace(key="public-signing-key")

    def decode(token, key, **kwargs):
        calls["decode"] = {"token": token, "key": key, **kwargs}
        return {"sub": "customer-user-a"}

    monkeypatch.setattr(api_app, "_jwk_client", FakeJwkClient())
    monkeypatch.setattr(api_app, "SUPABASE_JWT_ISSUER", "https://auth.example.test/v1")
    monkeypatch.setattr(api_app, "SUPABASE_JWT_AUD", "authenticated")
    monkeypatch.setattr(
        api_app.jwt, "get_unverified_header", lambda token: {"alg": "RS256"}
    )
    monkeypatch.setattr(api_app.jwt, "decode", decode)

    user_id = api_app._decode_supabase_user_id_from_bearer("Bearer signed-token")

    assert user_id == "customer-user-a"
    assert calls["signing_token"] == "signed-token"
    assert calls["decode"]["algorithms"] == ["RS256"]
    assert calls["decode"]["audience"] == "authenticated"
    assert calls["decode"]["issuer"] == "https://auth.example.test/v1"
    assert calls["decode"]["options"] == {"verify_exp": True}


def test_supabase_jwt_rejects_unapproved_algorithm(monkeypatch):
    monkeypatch.setattr(api_app, "_jwk_client", object())
    monkeypatch.setattr(api_app, "SUPABASE_JWT_ISSUER", "issuer")
    monkeypatch.setattr(
        api_app.jwt, "get_unverified_header", lambda token: {"alg": "HS256"}
    )

    assert api_app._decode_supabase_user_id_from_bearer("Bearer token") is None


def test_order_history_is_completed_only_and_scoped_to_authenticated_user(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    api_app.Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(api_app, "SessionLocal", factory)
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: "user-a" if authorization == "Bearer valid-a" else None,
    )

    db = factory()
    try:
        db.add_all(
            [
                api_app.Order(
                    id="completed-a",
                    stripe_session_id="cs_a",
                    customer_id="user-a",
                    status="completed",
                    order_number=1,
                ),
                api_app.Order(
                    id="pending-a",
                    stripe_session_id="cs_pending_a",
                    customer_id="user-a",
                    status="pending",
                ),
                api_app.Order(
                    id="completed-b",
                    stripe_session_id="cs_b",
                    customer_id="user-b",
                    status="completed",
                    order_number=2,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(api_app.app)
    headers = {"Authorization": "Bearer valid-a"}
    listing = client.get("/me/orders", headers=headers)
    own_detail = client.get("/me/orders/completed-a", headers=headers)
    other_detail = client.get("/me/orders/completed-b", headers=headers)
    pending_detail = client.get("/me/orders/pending-a", headers=headers)
    unauthorized = client.get("/me/orders")

    assert listing.status_code == 200
    assert [order["id"] for order in listing.json()] == ["completed-a"]
    assert own_detail.status_code == 200
    assert other_detail.status_code == 404
    assert pending_detail.status_code == 404
    assert unauthorized.status_code == 401

    api_app.Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_admin_debug_endpoint_fails_closed_without_admin_key(monkeypatch):
    monkeypatch.setattr(api_app, "ADMIN_API_KEY", "")
    monkeypatch.setattr(api_app, "API_KEY", "")

    response = TestClient(api_app.app).get("/debug/whoami")

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_admin_routes_do_not_fall_back_to_customer_ui_api_key(monkeypatch):
    monkeypatch.setattr(api_app, "ADMIN_API_KEY", "")
    monkeypatch.setattr(api_app, "API_KEY", "customer-ui-key")

    response = TestClient(api_app.app).get(
        "/debug/whoami", headers={"x-api-key": "customer-ui-key"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_admin_key_accepts_valid_key_and_rejects_invalid_key(monkeypatch):
    monkeypatch.setattr(api_app, "ADMIN_API_KEY", "admin-test-key")
    comparisons = []
    real_compare_digest = api_app.secrets.compare_digest

    def observed_compare_digest(provided, expected):
        comparisons.append((provided, expected))
        return real_compare_digest(provided, expected)

    monkeypatch.setattr(api_app.secrets, "compare_digest", observed_compare_digest)

    api_app._require_admin_key("admin-test-key")
    with pytest.raises(api_app.HTTPException) as exc_info:
        api_app._require_admin_key("wrong-key")

    assert exc_info.value.status_code == 401
    assert comparisons == [
        (b"admin-test-key", b"admin-test-key"),
        (b"wrong-key", b"admin-test-key"),
    ]


def test_authenticated_customer_identity_behavior_is_unchanged(monkeypatch):
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: (
            "verified-user" if authorization == "Bearer valid" else None
        ),
    )

    assert (
        api_app._api_key_or_customer_user_id(
            x_api_key=None,
            authorization="Bearer valid",
        )
        == "verified-user"
    )
    with pytest.raises(api_app.HTTPException) as exc_info:
        api_app._api_key_or_customer_user_id(
            x_api_key="customer-ui-key",
            authorization="Bearer invalid",
        )

    assert exc_info.value.status_code == 401


def test_admin_rate_limit_is_shared_across_all_admin_routes(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    api_app.Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(api_app, "SessionLocal", factory)
    monkeypatch.setattr(api_app, "ADMIN_API_KEY", "admin-test-key")
    monkeypatch.setattr(api_app, "ADMIN_RATE_LIMIT_REQUESTS", 2)
    api_app._RATE_LIMITER.clear()

    try:
        client = TestClient(api_app.app)
        headers = {"x-api-key": "admin-test-key"}

        invalid = client.get("/admin/config", headers={"x-api-key": "wrong-key"})
        first = client.get("/admin/config", headers=headers)
        second = client.get("/admin/orders", headers=headers)
        limited = client.get("/admin/config", headers=headers)

        assert invalid.status_code == 401
        assert first.status_code == 200
        assert second.status_code == 200
        assert limited.status_code == 429
        assert limited.headers["retry-after"]
    finally:
        api_app._RATE_LIMITER.clear()
        api_app.Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_refresh_updates_access_and_refresh_tokens_without_clearing_page_state(
    monkeypatch,
):
    page_state = AttrDict(
        auth={
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "user": None,
            "email": "buyer@example.com",
        },
        current_configuration={"paddle_dia": 3.0},
    )
    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=page_state))
    monkeypatch.setattr(auth, "_token_expires_soon", lambda token: True)
    saved_cookies = []
    monkeypatch.setattr(auth, "_cookie_set", saved_cookies.append)
    monkeypatch.setattr(
        auth,
        "sb",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                refresh_session=lambda token: {
                    "session": {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                    }
                }
            )
        ),
    )

    auth._refresh_session_if_needed()

    assert page_state.auth["access_token"] == "new-access"
    assert page_state.auth["refresh_token"] == "new-refresh"
    assert page_state.current_configuration == {"paddle_dia": 3.0}
    assert saved_cookies[0]["access_token"] == "new-access"


def test_failed_refresh_clears_an_expired_local_session(monkeypatch):
    page_state = AttrDict(
        auth={
            "access_token": "expired-access",
            "refresh_token": "expired-refresh",
            "user": None,
            "email": "buyer@example.com",
        }
    )
    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=page_state))
    monkeypatch.setattr(auth, "_token_expires_soon", lambda token: True)
    monkeypatch.setattr(auth, "_token_is_expired", lambda token: True)
    monkeypatch.setattr(auth, "_cookie_clear", lambda: None)

    def fail_refresh(token):
        raise RuntimeError("expired")

    monkeypatch.setattr(
        auth,
        "sb",
        lambda: SimpleNamespace(auth=SimpleNamespace(refresh_session=fail_refresh)),
    )

    auth._refresh_session_if_needed()

    assert page_state.auth["access_token"] is None
    assert page_state.auth["refresh_token"] is None


def test_malformed_cached_token_is_refreshed_or_cleared(monkeypatch):
    page_state = AttrDict(
        auth={
            "access_token": "not-a-jwt",
            "refresh_token": "stale-refresh",
            "user": None,
            "email": "buyer@example.com",
        }
    )
    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=page_state))
    monkeypatch.setattr(auth, "_cookie_clear", lambda: None)

    def fail_refresh(token):
        raise RuntimeError("invalid refresh token")

    monkeypatch.setattr(
        auth,
        "sb",
        lambda: SimpleNamespace(auth=SimpleNamespace(refresh_session=fail_refresh)),
    )

    auth._refresh_session_if_needed()

    assert page_state.auth["access_token"] is None
    assert page_state.auth["refresh_token"] is None


def test_malformed_token_without_refresh_is_not_treated_as_logged_in(monkeypatch):
    page_state = AttrDict(
        auth={
            "access_token": "not-a-jwt",
            "refresh_token": None,
            "user": None,
            "email": "buyer@example.com",
        }
    )
    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=page_state))
    monkeypatch.setattr(auth, "_cookie_clear", lambda: None)

    auth._refresh_session_if_needed()

    assert page_state.auth["access_token"] is None
    assert page_state.auth["refresh_token"] is None


def test_cookie_manager_is_reconstructed_at_start_of_each_streamlit_run(monkeypatch):
    created = []
    page_state = AttrDict()

    class FakeCookieManager:
        def __init__(self, *, key):
            created.append(key)

    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=page_state))
    monkeypatch.setattr(
        auth,
        "stx",
        SimpleNamespace(CookieManager=FakeCookieManager),
    )

    first = auth._start_cookie_component_run()
    second = auth._start_cookie_component_run()

    assert first is not second
    assert created == [
        "oplates_auth_cookie_reader",
        "oplates_auth_cookie_reader",
    ]


def test_cookie_manager_is_reused_within_one_streamlit_run(monkeypatch):
    created = []
    page_state = AttrDict()

    class FakeCookieManager:
        def __init__(self, *, key):
            created.append(key)

    monkeypatch.setattr(auth, "st", SimpleNamespace(session_state=page_state))
    monkeypatch.setattr(
        auth,
        "stx",
        SimpleNamespace(CookieManager=FakeCookieManager),
    )

    started = auth._start_cookie_component_run()

    assert auth._cookie_mgr() is started
    assert auth._cookie_mgr() is started
    assert created == ["oplates_auth_cookie_reader"]


def test_customer_code_contains_no_supabase_service_role_secret():
    customer_files = [
        ROOT / "auth.py",
        ROOT / "pages" / "1_Quote.py",
        ROOT / "pages" / "2_My_Orders.py",
        ROOT / "pages" / "3_Quote_Cart.py",
        ROOT / "pages" / "4_Success.py",
    ]
    source = "\n".join(path.read_text() for path in customer_files)

    assert "SERVICE_ROLE" not in source.upper()
    assert "SUPABASE_URL" not in source[source.find("def render_auth_sidebar") :]
