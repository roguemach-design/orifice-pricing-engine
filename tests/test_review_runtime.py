"""Security boundary for the temporary staging-only browser review."""
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from review_runtime import AUTH_API, REVIEW_SERVICE, handler_class, review_environment


def environment():
    return dict(RENDER_SERVICE_ID=REVIEW_SERVICE, API_BASE=AUTH_API,
                API_KEY="synthetic", OPLATES_OWNER_ACCEPTANCE_MODE="true",
                OPLATES_OWNER_TEST_CHECKOUT_ENABLED="false")


@pytest.mark.parametrize("key,value", [
    ("RENDER_SERVICE_ID", "production"), ("API_BASE", "https://quote.o-plates.com"),
    ("OPLATES_OWNER_ACCEPTANCE_MODE", "false"), ("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", "true"),
    ("DATABASE_URL", "forbidden"), ("STRIPE_SECRET_KEY", "forbidden"),
    ("SENDGRID_API_KEY", "forbidden"), ("SUPABASE_SERVICE_ROLE_KEY", "forbidden"),
])
def test_review_fails_closed_outside_isolation(key, value):
    with pytest.raises(ValueError):
        review_environment({**environment(), key: value})


def test_child_keeps_auth_but_uses_loopback_synthetic_quotes():
    env = review_environment(environment())
    assert env["V71_REVIEW_AUTH_API_BASE"] == AUTH_API
    assert env["API_BASE"] == "http://127.0.0.1:8505"
    assert env["API_KEY"] != "synthetic"
    assert env["OPLATES_DRAWING_ASSISTED_ENABLED"] == "false"
    assert env["OPLATES_OWNER_TEST_CHECKOUT_ENABLED"] == "false"


def test_anonymous_browser_cannot_render_configurator(monkeypatch):
    import auth
    import drawing_intake.owner_access
    from streamlit.testing.v1 import AppTest
    for key, value in review_environment(environment()).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda **kwargs: None)
    monkeypatch.setattr(auth, "current_user_id_hint", lambda: None)
    monkeypatch.setattr(auth, "auth_headers", lambda: {})
    monkeypatch.setattr(drawing_intake.owner_access, "verified_owner_access", lambda *a, **k: False)
    app = AppTest.from_file(Path(__file__).parents[1] / "review_only/app.py").run()
    assert not app.exception
    assert any("approved staging owner" in item.value for item in app.info)
    assert not app.number_input
    assert not app.get("html")
    app.switch_page("../pages/1_Quote.py").run()
    assert not app.exception
    assert any("approved staging owner" in item.value for item in app.info)
    assert not app.number_input
    assert not app.get("html")


def test_synthetic_api_denies_all_order_payment_email_and_record_paths():
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class("review-key"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = requests.Session(); client.trust_env = False
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert client.get(base + "/config/active").status_code == 200
        for route in ("/checkout/create", "/checkout/cart", "/orders", "/email", "/frozen-plate/approve", "/internal/drawing-intake/access"):
            assert client.post(base + route, json={}).status_code == 405
            assert client.get(base + route).status_code == 404
        spec = dict(quantity=1, material="304", thickness=.125, paddle_dia=3,
                    bore_dia=1, handle_width=1.5, handle_length_from_bore=9,
                    bore_tolerance=.005, ships_in_days=14, chamfer=False, handle_label="No label")
        assert client.post(base + "/quote", json=spec).status_code == 401
        response = client.post(base + "/quote", json=spec, headers={"x-api-key": "review-key"})
        assert response.status_code == 200
        assert response.json()["configuration_id"] == "SYNTHETIC-V71-REVIEW"
        assert response.json()["unit_price"] > 0
    finally:
        server.shutdown(); server.server_close(); client.close()
