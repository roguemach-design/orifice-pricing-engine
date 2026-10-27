"""Real Chromium + actual customer routes; only isolated loopback OTP/API fixtures.

No production credentials, provider traffic, Stripe sessions, or deployment.
"""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect, sync_playwright
from browser_smoke import CONFIG

ROOT = Path(__file__).resolve().parents[1]


def jwt(exp=None):
    value = json.dumps({"exp": exp or time.time() + 3600, "sub": "synthetic-customer"})
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + base64.urlsafe_b64encode(value.encode()).decode().rstrip("=") + ".c3ludGhldGlj"


@pytest.fixture
def customer_app(tmp_path):
    state = dict(sends=0, rotations=0, revoked=False, refresh="synthetic-refresh-0", protected=[])
    user = dict(id="synthetic-customer", aud="authenticated", role="authenticated", email="buyer@example.test",
                created_at="2026-01-01T00:00:00Z", app_metadata={}, user_metadata={})

    class API(BaseHTTPRequestHandler):
        def reply(self, data, status=200, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write((json.dumps(data) if content_type == "application/json" else data).encode())

        def session(self):
            state["rotations"] += 1
            state["refresh"] = "synthetic-refresh-" + str(state["rotations"])
            self.reply(dict(access_token=jwt(), refresh_token=state["refresh"], token_type="bearer",
                            expires_in=3600, user=user))

        def do_GET(self):
            if self.path == "/landing":
                self.reply('<iframe id="plate-configurator" style="width:100%;height:1800px" src="'
                           + state["ui"] + '/Quote?embed=true&integrated=1"></iframe>', content_type="text/html")
            elif self.path == "/config/active":
                self.reply(CONFIG)
            elif self.path.startswith("/auth/v1/user"):
                self.reply(user if not state["revoked"] else {"msg": "revoked"}, 401 if state["revoked"] else 200)
            elif self.path == "/checkout/availability":
                self.reply({"available": False, "mode": None})
            elif self.path.startswith("/internal/"):
                self.reply({"allowed": False})
            elif self.path.startswith("/me/"):
                state["protected"].append(self.headers.get("Authorization"))
                self.reply([], 401 if state["revoked"] or not self.headers.get("Authorization") else 200)
            elif self.path.startswith("/orders/by-session/"):
                self.reply(dict(status="completed", payment_mode="OWNER TEST", order_number_display="TEST-FIXTURE",
                                amount_total_usd=100, shipping_service="ups_ground"))
            else:
                self.reply({}, 404)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            if self.path == "/auth/v1/otp":
                state["sends"] += 1
                self.reply({})
            elif self.path == "/auth/v1/verify":
                state["revoked"] = False
                self.session()
            elif self.path.startswith("/auth/v1/token"):
                if state["revoked"] or data.get("refresh_token") != state["refresh"]:
                    self.reply({"code": "refresh_token_not_found", "msg": "synthetic revoked session"}, 400)
                else:
                    self.session()
            elif self.path.startswith("/auth/v1/logout"):
                state["revoked"] = True
                self.reply({})
            elif self.path == "/quote":
                self.reply(dict(unit_price=100, total_price=100, configuration_id="fixture", pricing_config_version="fixture"))
            elif self.path == "/me/frozen-plates/inspect":
                state["protected"].append(self.headers.get("Authorization"))
                self.reply(dict(state="approved", historical=False, context=dict(test_order=True)))
            else:
                self.reply({}, 404)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), API)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    state["ui"] = f"http://127.0.0.1:{port}"
    api = f"http://127.0.0.1:{server.server_port}"
    env = {key: os.environ[key] for key in ("PATH", "PYTHONPATH", "LANG") if key in os.environ}
    env.update(API_BASE=api, SUPABASE_URL=api, SUPABASE_ANON_KEY="synthetic-public", API_KEY="synthetic-ui")
    log = (tmp_path / "app.log").open("w+")
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.address=127.0.0.1",
        f"--server.port={port}", "--server.headless=true", "--browser.gatherUsageStats=false", "--global.developmentMode=false"],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                with urlopen(state["ui"] + "/_stcore/health", timeout=1):
                    break
            except OSError:
                time.sleep(.2)
        yield state, api
    finally:
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()
        server.server_close()
        log.close()


def sign_in(scope):
    scope.get_by_role("button", name="Sign in", exact=True).click()
    scope.get_by_role("textbox", name="Email", exact=True).fill("buyer@example.test")
    scope.get_by_role("button", name="Send code", exact=True).click()
    expect(scope.get_by_text("Check your email for the sign-in code.", exact=True)).to_be_visible()
    scope.get_by_role("textbox", name="OTP code", exact=True).fill("123456")
    scope.get_by_role("button", name="Verify code", exact=True).click()
    expect(scope.get_by_text("Signed in as:", exact=False)).to_be_visible(timeout=20000)


@pytest.mark.parametrize("embedded", [False, True])
def test_one_otp_survives_customer_routes_and_returns(customer_app, embedded):
    state, api = customer_app
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith((api + "/", state["ui"] + "/")) else route.abort())
        try:
            page.goto(api + "/landing" if embedded else state["ui"] + "/Quote")
            scope = page.frame_locator("#plate-configurator") if embedded else page
            scope.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True).fill("4")
            scope.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True).press("Tab")
            sign_in(scope)
            expect(scope.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True)).to_have_value("4.000")
            scope.get_by_role("button", name="Add another plate", exact=True).click()
            expect(scope.get_by_role("heading", name="Line items (1)", exact=True)).to_be_visible()
            scope.get_by_role("link", name="My Orders", exact=True).click()
            expect(scope.get_by_text("Signed in as:", exact=False)).to_be_visible()
            scope.get_by_role("link", name="Quote Cart", exact=True).click()
            expect(scope.get_by_role("heading", name="Line items (1)", exact=True)).to_be_visible()
            # New document/Streamlit websocket, matching a Stripe return.
            page.goto(state["ui"] + "/Success?session_id=cs_test_synthetic")
            expect(page.get_by_text("Signed in as:", exact=False)).to_be_visible(timeout=20000)
            page.goto(state["ui"] + "/My_Orders")
            expect(page.get_by_text("Signed in as:", exact=False)).to_be_visible(timeout=20000)
            page.reload()
            expect(page.get_by_text("Signed in as:", exact=False)).to_be_visible(timeout=20000)
            page.goto(state["ui"] + "/Drawing_Approval?token=synthetic-confirmation")
            expect(page.get_by_text("TEST DRAWING APPROVED — NOT A REAL SALE", exact=True)).to_be_visible(timeout=20000)
            assert state["sends"] == 1
            assert state["protected"] and all(state["protected"])
            page.get_by_role("button", name="Log out", exact=True).click()
            expect(page.get_by_role("button", name="Send code", exact=True)).to_be_visible(timeout=20000)
            page.reload()
            expect(page.get_by_role("button", name="Send code", exact=True)).to_be_visible(timeout=20000)
            assert state["revoked"]
        finally:
            browser.close()
