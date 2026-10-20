"""Real Chromium gate for the customer configurator (run explicitly in CI).

Run: python -m pytest -q tests/browser_smoke.py
Requires the CI-only Playwright dependency and its Chromium installation.
Only loopback services are used; no production credentials or writes are available.
"""

import io
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

from PIL import Image
from playwright.sync_api import expect, sync_playwright
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = dict(
    materials=["304", "316", "Carbon Steel"],
    thicknesses_by_material={m: [.125, .25, .375, .5] for m in ["304", "316", "Carbon Steel"]},
    lead_times_days=[14, 21], default_lead_time_days=14,
    tolerance_options_in=[.001, .002, .005], max_paddle_dia_in=48,
    max_bore_dia_in=19, max_handle_label_chars=40,
)


@pytest.fixture(scope="module")
def configurator(tmp_path_factory):
    requests_seen = []

    class SyntheticAPI(BaseHTTPRequestHandler):
        def reply(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self):
            requests_seen.append(("GET", self.path))
            self.reply(CONFIG if self.path == "/config/active" else {},
                       200 if self.path == "/config/active" else 405)

        def do_POST(self):
            requests_seen.append(("POST", self.path))
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            # Rendering needs a price response, not an order or a real API.
            self.reply({"unit_price": 100, "total_price": 100,
                        "configuration_id": "SYNTHETIC-SVG-SMOKE"},
                       200 if self.path == "/quote" else 405)

        def log_message(self, *args):
            pass

    api = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticAPI)
    thread = threading.Thread(target=api.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    temp = tmp_path_factory.mktemp("configurator-browser")
    # Do not inherit application credentials or production service settings.
    env = {key: os.environ[key] for key in ("PATH", "PYTHONPATH", "LANG") if key in os.environ}
    env.update(HOME=str(temp), API_BASE=f"http://127.0.0.1:{api.server_port}")
    log = (temp / "streamlit.log").open("w+")
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.address=127.0.0.1", f"--server.port={port}",
         "--server.headless=true", "--browser.gatherUsageStats=false"],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                with urlopen(url + "/_stcore/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.2)
        else:
            log.seek(0)
            pytest.fail("Customer app did not start: " + log.read())
        yield url
    finally:
        process.terminate()
        process.wait(timeout=15)
        api.shutdown()
        api.server_close()
        log.close()
    assert requests_seen
    assert set(requests_seen) <= {("GET", "/config/active"), ("POST", "/quote")}


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "mobile"])
@pytest.mark.parametrize("route", ["/Quote", "/Quote?integrated=1"], ids=["direct", "landing-embed"])
def test_customer_configurator_paints_svg(configurator, width, route, tmp_path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000})
        # The browser may only reach this synthetic customer app.
        page.route("**/*", lambda request: request.continue_()
                   if request.request.url.startswith(configurator + "/") else request.abort())
        try:
            page.goto(configurator + route)
            expect(page.get_by_text("Configuration preview only.", exact=False)).to_be_visible(timeout=30000)
            svg = page.get_by_role("img", name="Handled orifice plate configuration drawing", exact=True)
            expect(svg).to_be_visible(timeout=15000)
            svg.scroll_into_view_if_needed()
            metrics = svg.evaluate("""svg => {
                const rect = svg.getBoundingClientRect();
                const box = svg.viewBox.baseVal;
                return {width:rect.width, height:rect.height, ratio:box.width/box.height,
                    profile:svg.dataset.profile,
                    shapes:[...svg.querySelectorAll('path,circle,line')].filter(el => {
                        const r=el.getBoundingClientRect(), s=getComputedStyle(el);
                        return (r.width>0 || r.height>0) && s.stroke==='rgb(0, 0, 0)'
                            && s.visibility==='visible' && s.display!=='none';
                    }).length};
            }""")
            assert metrics["profile"] == "web"
            assert metrics["width"] > 200 and metrics["height"] > 100
            assert abs(metrics["width"] / metrics["height"] - metrics["ratio"]) < .02
            assert metrics["shapes"] > 20
            # A rendered screenshot must contain dark drawing ink, not a blank box.
            pixels = Image.open(io.BytesIO(svg.screenshot())).convert("RGB")
            assert sum(max(pixel) < 100 for pixel in pixels.getdata()) > 500
            assert page.get_by_test_id("stException").count() == 0
        finally:
            page.screenshot(path=str(tmp_path / f"configurator-{width}.png"), full_page=True)
            browser.close()
