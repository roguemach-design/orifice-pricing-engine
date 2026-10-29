"""Actual Streamlit owner UI, real pricing API, synthetic local database/providers only."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect, sync_playwright
from test_pricing_configuration import client, snapshot
from test_checkout_control_ui import Client as CheckoutClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def owner_app(client, tmp_path):
    api, _ = client
    state = dict(writes=[], checkout=CheckoutClient(), initial=snapshot(api))

    class Handler(BaseHTTPRequestHandler):
        def reply(self, body, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            if self.headers.get("x-api-key") != "synthetic-owner":
                self.reply({}, 401)
                return
            path = urlsplit(self.path).path
            if path == "/admin/config/editor":
                response = api.get(path, headers={"x-api-key": "synthetic-owner"})
                self.reply(response.json(), response.status_code)
            elif path == "/admin/checkout-control":
                self.reply(state["checkout"].json(path))
            elif path == "/admin/orders":
                self.reply([])
            elif path == "/admin/manufacturing-summary":
                self.reply(dict(orders=[], scope="Synthetic owner fixture", partial=False,
                                snapshot_at="2026-10-29T00:00:00Z", counts=dict(
                                    awaiting_approval=0, approved=0, ready_for_release=0,
                                    sourcing_recorded=0, record_unavailable=0)))
            elif path == "/admin/sales":
                self.reply(dict(total_cents=0, order_count=0, start="2026-01-01", end="2026-10-29", points=[], basis="Synthetic fixture"))
            else:
                self.reply({}, 404)

        def do_PUT(self):
            self.write_request()

        def do_POST(self):
            self.write_request()

        def write_request(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.headers.get("x-api-key") != "synthetic-owner":
                self.reply({}, 401)
            elif self.path == "/admin/checkout-control":
                self.reply(state["checkout"].checkout_mode_write(body))
            elif self.path.startswith("/admin/config"):
                state["writes"].append((self.command, self.path, body))
                response = api.request(self.command, self.path, headers={"x-api-key": "synthetic-owner"}, json=body)
                self.reply(response.json(), response.status_code)
            else:
                self.reply({}, 404)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    state["ui"] = f"http://127.0.0.1:{port}"
    local_api = f"http://127.0.0.1:{server.server_port}"
    staging = "https://oplates-pricing-api-staging.onrender.com"
    (tmp_path / "sitecustomize.py").write_text(
        "import requests\noriginal=requests.sessions.Session.request\n"
        "def isolated(self,method,url,*args,**kwargs):\n"
        f"    if url.startswith({staging!r} + '/'): url={local_api!r}+url[len({staging!r}):]\n"
        "    return original(self,method,url,*args,**kwargs)\n"
        "requests.sessions.Session.request=isolated\n"
    )
    env = {key: os.environ[key] for key in ("PATH", "LANG") if key in os.environ}
    env.update(HOME=str(tmp_path), PYTHONPATH=str(tmp_path), APP_ENV="staging", API_BASE=staging)
    log = (tmp_path / "owner.log").open("w+")
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "owner_app/main.py",
                               "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=true",
                               "--browser.gatherUsageStats=false", "--global.developmentMode=false"],
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
        print("Synthetic owner log:", log.read())
        log.close()


def pricing(page):
    page.get_by_role("radio", name="Pricing & Availability", exact=True).press("Space")
    expect(page.get_by_role("tab", name="Availability", exact=True)).to_be_visible()


def clean(page):
    expect(page.get_by_test_id("stException")).to_have_count(0)


def test_owner_pricing_rerun_drafts_save_and_recovery(owner_app, tmp_path):
    state, api = owner_app
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(state["ui"] + "/") else route.abort())
        try:
            page.goto(state["ui"])
            page.get_by_role("textbox", name="Internal admin credential", exact=True).fill("synthetic-owner")
            page.get_by_role("button", name="Unlock", exact=True).click()
            pricing(page)
            seven = page.get_by_role("checkbox", name="7", exact=True)
            seven.press("Space")
            expect(page.get_by_text("Unsaved changes. Keep this session open", exact=False)).to_be_visible()
            clean(page)
            assert not state["writes"] and snapshot(api) == state["initial"]
            seven.press("Space")
            expect(page.get_by_text("Unsaved changes. Keep this session open", exact=False)).to_have_count(0)
            clean(page)
            for tab in ("Material prices", "Process & discounts", "Weights & limits", "Recovery", "Availability"):
                page.get_by_role("tab", name=tab, exact=True).click()
                clean(page)
            seven.press("Space")
            expect(page.get_by_text("Unsaved changes. Keep this session open", exact=False)).to_be_visible()
            page.get_by_role("tab", name="Process & discounts", exact=True).click()
            editor = page.locator('.st-key-mc_price_tiers')
            expect(editor.get_by_test_id("glide-cell-2-1")).to_have_text("0.97")
            page.get_by_role("radio", name="Overview", exact=True).press("Space")
            expect(page.get_by_role("heading", name="Rogue Command Center", exact=True)).to_be_visible()
            pricing(page)
            expect(seven).to_be_checked()
            assert not state["writes"] and snapshot(api) == state["initial"]
            page.get_by_role("radio", name="Checkout Control", exact=True).press("Space")
            expect(page.get_by_role("heading", name="Checkout Control", exact=True)).to_be_visible()
            clean(page)
            page.get_by_role("combobox", name="Requested checkout mode", exact=True).click()
            page.get_by_role("option", name="TEST", exact=True).click()
            page.get_by_role("textbox", name="Type APPLY TEST to confirm", exact=True).fill("APPLY TEST")
            page.get_by_role("textbox", name="Type APPLY TEST to confirm", exact=True).press("Tab")
            page.get_by_role("button", name="Save / Apply", exact=True).click()
            expect(page.get_by_test_id("stMetricValue")).to_have_text("TEST")
            assert len(state["checkout"].writes) == 1 and not state["writes"]
            assert snapshot(api) == state["initial"]
            page.get_by_role("radio", name="Pricing settings", exact=True).press("Space")
            expect(seven).to_be_checked()
            page.get_by_role("tab", name="Process & discounts", exact=True).click()
            expect(editor.get_by_test_id("glide-cell-2-1")).to_have_text("0.97")
            page.get_by_role("checkbox", name="I reviewed these changes", exact=False).press("Space")
            page.get_by_role("button", name="Save Changes", exact=True).click()
            expect(page.get_by_text("Changes saved. The prior configuration is available in Recovery.", exact=True)).to_be_visible()
            clean(page)
            saved = snapshot(api)
            assert len(state["writes"]) == 1
            assert saved["config"]["qty_discount_tiers"] == state["initial"]["config"]["qty_discount_tiers"]
            assert saved["config"]["lead_time_enabled"]["7"] is True
            assert saved["version"] != state["initial"]["version"]
            page.get_by_role("tab", name="Recovery", exact=True).click()
            page.get_by_role("textbox", name="Type RESTORE CONFIGURATION to confirm", exact=True).fill("RESTORE CONFIGURATION")
            page.get_by_role("textbox", name="Type RESTORE CONFIGURATION to confirm", exact=True).press("Tab")
            page.get_by_role("button", name="Apply recovery action", exact=True).click()
            expect(page.get_by_text("Recovery completed. The previous configuration was preserved.", exact=True)).to_be_visible()
            clean(page)
            assert len(state["writes"]) == 2 and state["writes"][-1][1] == "/admin/config/restore"
            restored = snapshot(api)
            from pricing_configuration import changes
            assert not changes(state["initial"]["config"], restored["config"])
            assert len(restored["history"]) == 2
            page.screenshot(path=str(tmp_path / "owner-pricing.png"), full_page=True)
            clean(page)
        finally:
            print("Owner page:", page.locator("body").inner_text(timeout=2000))
            browser.close()
