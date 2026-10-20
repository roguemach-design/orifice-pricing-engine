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
from urllib.parse import urlsplit

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


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop-host", "mobile-host"])
def test_actual_landing_host_renders_one_visible_drawing(configurator, width, tmp_path):
    """Exercise the real landing HTML/CSS/JS and its real Streamlit bridge.

    Browser request interception substitutes only the loopback child origin;
    no public server, production requests, or preview infrastructure is used.
    """
    landing = ROOT / "o-plates landing"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000})

        def local_only(route):
            url = route.request.url
            if url.startswith(configurator + "/"):
                return route.continue_()
            if not url.startswith("https://o-plates.com/"):
                return route.abort()
            path = (landing / (urlsplit(url).path.lstrip("/") or "index.html")).resolve()
            if not path.is_relative_to(landing) or not path.is_file():
                return route.fulfill(status=404, body="")
            if path.suffix in {".html", ".js", ".css"}:
                # The production origin checks still run against the isolated child.
                body = path.read_text().replace("https://quote.o-plates.com", configurator)
                content_type = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}[path.suffix]
                return route.fulfill(body=body, content_type=content_type)
            return route.fulfill(path=path)

        page.route("**/*", local_only)
        try:
            page.goto("https://o-plates.com/")
            page.locator("#plate-configurator").scroll_into_view_if_needed()
            child = page.frame_locator("#plate-configurator")
            source = child.locator('svg[aria-label="Handled orifice plate configuration drawing"]')
            expect(source).to_be_attached(timeout=30000)
            copy = page.locator('.sticky-feedback__drawing svg')
            if width >= 901:
                expect(copy).to_be_visible(timeout=15000)
                # aria-hidden alone does not prevent painted duplicate SVGs.
                expect(source).to_have_css("visibility", "hidden")
                assert source.evaluate("el => [...el.querySelectorAll('*')].every(x => getComputedStyle(x).visibility === 'hidden')")
                visible = copy
            else:
                expect(page.locator("#configurator-feedback")).to_be_hidden()
                expect(source).to_be_visible(timeout=15000)
                expect(source).to_have_css("visibility", "visible")
                visible = source
            visible.scroll_into_view_if_needed()
            box = visible.bounding_box()
            assert box and box["width"] > 200 and box["height"] > 100
            assert visible.evaluate("el => Math.abs(el.clientWidth / el.clientHeight - el.viewBox.baseVal.width / el.viewBox.baseVal.height) < .02")
            pixels = Image.open(io.BytesIO(visible.screenshot())).convert("RGB")
            assert sum(max(pixel) < 100 for pixel in pixels.getdata()) > 500
            # The copy and source must track real customer input reruns.
            child.get_by_role("radio", name="316 SS Added corrosion resistance.", exact=True).check()
            expect(visible.locator('[data-feature="web-material"]')).to_have_text("316 STAINLESS STEEL")
            child.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True).fill("4.000")
            child.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True).press("Tab")
            expect(visible.locator('[data-feature="od-dimension-label"]')).to_have_text("Ø4.000")
            if width >= 901:
                expect(source).to_have_css("visibility", "hidden")
            assert child.get_by_test_id("stException").count() == 0
        finally:
            page.screenshot(path=str(tmp_path / f"landing-{width}.png"), full_page=True)
            browser.close()
