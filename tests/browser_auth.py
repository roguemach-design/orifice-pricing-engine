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
    value = json.dumps({"exp": int(exp or time.time() + 3600), "sub": "synthetic-customer"})
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + base64.urlsafe_b64encode(value.encode()).decode().rstrip("=") + ".c3ludGhldGlj"


@pytest.fixture
def customer_app(tmp_path):
    state = dict(sends=0, rotations=0, revoked=False, refresh="synthetic-refresh-0", protected=[], quotes=[])
    user = dict(id="synthetic-customer", aud="authenticated", role="authenticated", email="buyer@example.test",
                created_at="2026-01-01T00:00:00Z", app_metadata={}, user_metadata={})

    class API(BaseHTTPRequestHandler):
        def reply(self, data, status=200, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            payload = json.dumps(data).encode() if content_type == 'application/json' else data if isinstance(data, bytes) else data.encode()
            self.wfile.write(payload)

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
                if state["revoked"] or not self.headers.get("Authorization"):
                    self.reply({}, 401)
                elif self.path.startswith('/me/order-history/'):
                    self.reply(state.get('order_detail', {}))
                elif self.path.startswith('/me/order-history'):
                    self.reply(state.get('order_history', {'orders':[], 'total':0}))
                elif self.path.endswith('/drawing-archive'):
                    self.reply(state.get('drawing_archive', []))
                elif self.path.endswith('/pdf'):
                    content=state['drawing_pdf']
                    self.send_response(200)
                    self.send_header('Content-Type','application/pdf')
                    self.send_header('X-Artifact-SHA256',state['drawing_hash'])
                    self.send_header('X-Frozen-Revision','revision-1')
                    self.end_headers();self.wfile.write(content)
                else:
                    self.reply([])
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
                state["quotes"].append(data)
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
    # Use the real staging UI gate while redirecting all server API traffic
    # to loopback before Streamlit starts. No production feature gate changes.
    staging = "https://oplates-pricing-api-staging.onrender.com"
    (tmp_path / "sitecustomize.py").write_text(
        "import requests\n"
        "original = requests.sessions.Session.request\n"
        "def isolated(self, method, url, *args, **kwargs):\n"
        f"    if url.startswith({staging!r} + '/'): url = {api!r} + url[len({staging!r}):]\n"
        "    return original(self, method, url, *args, **kwargs)\n"
        "requests.sessions.Session.request = isolated\n"
    )
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    env.update(API_BASE=staging, SUPABASE_URL=api, SUPABASE_ANON_KEY="synthetic-public", API_KEY="synthetic-ui")
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
        log.seek(0)
        print("Synthetic app log:", log.read())
        log.close()


def await_quote(state, expected, timeout=10):
    """Wait for the actual server request, not an earlier still-visible metric."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state["quotes"] and all(state["quotes"][-1].get(k) == v for k, v in expected.items()):
            return
        time.sleep(.05)
    assert state["quotes"] and all(state["quotes"][-1].get(k) == v for k, v in expected.items()), state["quotes"][-1:]


def sign_in(scope):
    scope.get_by_role("button", name="Sign in", exact=True).click()
    scope.get_by_role("textbox", name="Email", exact=True).fill("buyer@example.test")
    scope.get_by_role("button", name="Send code", exact=True).click()
    expect(scope.get_by_text("Check your email for the sign-in code.", exact=True)).to_be_visible()
    scope.get_by_role("textbox", name="OTP code", exact=True).fill("123456")
    scope.get_by_role("button", name="Verify code", exact=True).click()
    expect(scope.get_by_text("Signed in as:", exact=False)).to_be_visible(timeout=20000)


@pytest.mark.parametrize("embedded", [False, True])
@pytest.mark.parametrize("chamfer", [False, True])
@pytest.mark.parametrize("lead_time", [14, 21])
def test_one_otp_survives_customer_routes_and_returns(customer_app, embedded, chamfer, lead_time, tmp_path):
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
            expect(scope.locator('[data-feature="od-dimension-label"]')).to_have_text("Ø4.000")
            expect(scope.get_by_test_id("stMetric")).to_have_count(2)
            lead = scope.get_by_role("radio", name=f"{lead_time} calendar days", exact=True)
            if lead_time != 14:
                lead.click()
            expect(lead).to_be_checked()
            bore = scope.get_by_role("radio", name=(
                "CHAMFERED BORE Add a chamfer to the bore edge." if chamfer
                else "NO CHAMFER Square bore edge."
            ), exact=True)
            if chamfer:
                scope.get_by_role("radio", name="CHAMFERED BORE Add a chamfer to the bore edge.", exact=True).press("Space")
                width = scope.get_by_role("spinbutton", name="Chamfer Width (in.)", exact=True)
                width.fill("0.04")
                width.press("Tab")
                expect(width).to_have_value("0.0400")
                expect(scope.get_by_text("Chamfer specification", exact=True)).to_have_count(0)
            # Check before authentication too: conditional form reruns must not
            # clear a required choice and make a later sign-in look responsible.
            expect(lead).to_be_checked()
            expect(bore).to_be_checked()
            expect(scope.get_by_test_id("stMetric")).to_have_count(2)
            expected = dict(chamfer=chamfer, ships_in_days=lead_time, paddle_dia=4.0)
            if chamfer:
                expected.update(chamfer_angle_degrees=45.0, chamfer_side="downstream",
                                flow_orientation="left-to-right", chamfer_width_definition="radial-angle-from-face",
                                chamfer_width=0.04)
            await_quote(state, expected)
            # Dismiss once before OTP: opening/closing the dialog must not clear
            # the native controls or replace a customer choice with a default.
            scope.get_by_role("button", name="Sign in", exact=True).click()
            dialog = scope.get_by_role("dialog")
            expect(dialog).to_be_visible()
            dialog.get_by_role("button", name="Close", exact=True).click()
            expect(dialog).to_have_count(0)
            expect(bore).to_be_checked()
            expect(lead).to_be_checked()
            sign_in(scope)
            expect(scope.get_by_role("dialog")).to_have_count(0, timeout=20000)
            expect(scope.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True)).to_have_value("4.000")
            expect(scope.get_by_test_id("stMetric")).to_have_count(2)
            expect(lead).to_be_checked()
            expect(bore).to_be_checked()
            await_quote(state, expected)
            assert state["quotes"][-1]["ships_in_days"] == lead_time
            if chamfer:
                expect(scope.get_by_role("spinbutton", name="Chamfer Width (in.)", exact=True)).to_have_value("0.0400")
                expected = dict(chamfer_angle_degrees=45.0, chamfer_side="downstream",
                                flow_orientation="left-to-right", chamfer_width_definition="radial-angle-from-face",
                                chamfer=True, chamfer_width=0.04)
                assert all(state["quotes"][-1][key] == value for key, value in expected.items())
            scope.get_by_role("button", name="Add another plate", exact=True).click()
            expect(scope.get_by_role("heading", name="Line items (1)", exact=True)).to_be_visible()
            scope.get_by_role("link", name="My Orders", exact=True).click()
            expect(scope.get_by_text("Signed in as:", exact=False)).to_be_visible()
            scope.get_by_role("link", name="Quote Cart", exact=True).click()
            expect(scope.get_by_role("heading", name="Line items (1)", exact=True)).to_be_visible()
            if chamfer:
                assert all(state["quotes"][-1][key] == value for key, value in expected.items())
            # Return to the actual configurator in the same session after its
            # widgets were removed on Cart and My Orders. Retain both canonical
            # payload values and browser-visible selections, including False.
            scope.get_by_role("link", name="Configure your plate", exact=True).click()
            expect(bore).to_be_checked()
            expect(lead).to_be_checked()
            expect(scope.get_by_test_id("stMetric")).to_have_count(2)
            await_quote(state, expected)
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
            saved_cookies = [c for c in context.cookies() if c["name"] == "oplates_auth"]
            assert len(saved_cookies) == 1
            page.get_by_role("button", name="Log out", exact=True).click()
            expect(page.get_by_text("Signed in as:", exact=False)).to_have_count(0, timeout=20000)
            expect(page.get_by_text("TEST DRAWING APPROVED — NOT A REAL SALE", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Send code", exact=True, include_hidden=True)).to_be_attached(timeout=20000)
            page.reload()
            expect(page.get_by_text("Signed in as:", exact=False)).to_have_count(0, timeout=20000)
            expect(page.get_by_text("TEST DRAWING APPROVED — NOT A REAL SALE", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Send code", exact=True, include_hidden=True)).to_be_attached(timeout=20000)
            assert state["revoked"]
            assert not any(c["name"] == "oplates_auth" for c in context.cookies())
            # A restored copy of the revoked credential cannot regain access.
            protected_before = len(state["protected"])
            context.add_cookies(saved_cookies)
            page.goto(state["ui"] + "/My_Orders")
            expect(page.get_by_role("button", name="Send code", exact=True, include_hidden=True)).to_be_attached(timeout=20000)
            expect(page.get_by_text("Signed in as:", exact=False)).to_have_count(0)
            assert len(state["protected"]) == protected_before
            assert state["sends"] == 1
        finally:
            (tmp_path / "quote-payloads.json").write_text(json.dumps(state["quotes"]))
            for frame in page.frames:
                if frame.url.startswith(state["ui"] + "/"):
                    try:
                        print("Synthetic journey page:", frame.locator("body").inner_text(timeout=2000))
                    except Exception:
                        pass
            page.screenshot(path=str(tmp_path / "auth-journey.png"), full_page=True)
            (tmp_path / "auth-journey.html").write_text(page.content())
            browser.close()
