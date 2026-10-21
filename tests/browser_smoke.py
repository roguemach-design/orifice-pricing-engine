"""Real Chromium gate for the customer configurator (run explicitly in CI).

Run: python -m pytest -q tests/browser_smoke.py
Requires the CI-only Playwright dependency and its Chromium installation.
Only loopback services are used; no production credentials or writes are available.
"""

import io
import json
import os
import re
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
def configurator(tmp_path_factory, request):
    requests_seen = []
    quote_leads = []
    config = {**CONFIG, "lead_times_days": [7, 14, 21] if getattr(request, "param", False) else [14, 21]}

    class SyntheticAPI(BaseHTTPRequestHandler):
        def reply(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self):
            requests_seen.append(("GET", self.path))
            self.reply(config if self.path == "/config/active" else {},
                       200 if self.path == "/config/active" else 405)

        def do_POST(self):
            requests_seen.append(("POST", self.path))
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.path == "/quote":
                quote_leads.append(payload["ships_in_days"])
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
    env.update(HOME=str(temp), API_BASE=f"http://127.0.0.1:{api.server_port}",
               JOURNEY_UI_ENABLED="true",
               JOURNEY_PUBLIC_API="https://orifice-pricing-api.onrender.com")
    log = (temp / "streamlit.log").open("w+")
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.address=127.0.0.1", f"--server.port={port}",
         "--server.headless=true", "--browser.gatherUsageStats=false",
         "--global.developmentMode=false"],
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
    assert quote_leads and set(quote_leads) <= set(config["lead_times_days"])


def assert_expedited_display(page, *, seven_enabled=False):
    soon = page.get_by_role("button", name="Today / 2-Day · Coming Soon", exact=True)
    expect(soon).to_be_visible()
    expect(soon).to_be_disabled()
    expect(soon).to_have_css("opacity", "0.45")
    if seven_enabled:
        expect(page.get_by_role("radio", name="7 Days", exact=True)).to_be_enabled()
        expect(page.get_by_role("button", name="7 Days · Currently Unavailable", exact=True)).to_have_count(0)
    else:
        seven = page.get_by_role("button", name="7 Days · Currently Unavailable", exact=True)
        expect(seven).to_be_visible()
        expect(seven).to_be_disabled()
        expect(seven).to_have_css("opacity", "0.45")
        expect(page.get_by_role("radio", name="7 Days", exact=True)).to_have_count(0)
    for days in (14, 21):
        expect(page.get_by_role("radio", name=f"{days} calendar days", exact=True)).to_be_enabled()


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
            assert_expedited_display(page)
            page.locator('.st-key-lead_time_choices').screenshot(path=str(tmp_path / f"lead-time-off-{width}.png"))
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
        # This intercepted host has no network response, but Chromium still
        # requires its local-network permission to embed the loopback fixture.
        # The disposable test context and request allowlist remain isolated.
        page.context.grant_permissions(["local-network-access"], origin="https://o-plates.com")
        diagnostics = []
        page.on("console", lambda message: diagnostics.append(f"{message.type}: {message.text}"))
        page.on("requestfailed", lambda request: diagnostics.append(f"{request.url}: {request.failure}"))

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
            assert_expedited_display(child)
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
            child.get_by_role("radio", name="316 SS Added corrosion resistance.", exact=True).press("Space")
            expect(visible.locator('[data-feature="web-material"]')).to_have_text("316 STAINLESS STEEL")
            child.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True).fill("4.000")
            child.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True).press("Tab")
            expect(visible.locator('[data-feature="od-dimension-label"]')).to_have_text("Ø4.000")
            if width >= 901:
                expect(source).to_have_css("visibility", "hidden")
            # New validation/default behavior on the actual host and mobile layout.
            child.get_by_role("radio", name=re.compile("^CHAMFERED BORE")).press("Space")
            chamfer = child.get_by_role("spinbutton", name="Chamfer Width (in.)", exact=True)
            expect(chamfer).to_have_value("0.0620")
            child.get_by_role("radio", name="HANDLE HOLE", exact=True).press("Space")
            diameter = child.get_by_role("textbox", name="Handle Hole Diameter (in.)", exact=True)
            distance = child.get_by_role("textbox", name="Handle End to Hole Center (in.)", exact=True)
            expect(diameter).to_have_value("0.375")
            expect(distance).to_have_value("0.750")
            for widget, value, drawing_text in (
                (chamfer, "0.040", ".040 X 45°"),
                (diameter, "0.5", "Ø.500 THRU"),
                (distance, "1.25", "1.25"),
            ):
                widget.fill(value)
                widget.press("Tab")
                # Empty errors can predate the rerun. Wait for the server-rendered
                # drawing to acknowledge each edit before hiding its widget.
                expect(visible.get_by_text(drawing_text, exact=True)).to_be_visible()
                expect(child.locator('[data-field-error]')).to_have_count(0)
            child.get_by_role("radio", name=re.compile("^NO CHAMFER")).press("Space")
            expect(chamfer).to_have_count(0)
            child.get_by_role("radio", name="NO HANDLE HOLE", exact=True).press("Space")
            expect(diameter).to_have_count(0)
            child.get_by_role("radio", name=re.compile("^CHAMFERED BORE")).press("Space")
            expect(chamfer).to_have_value("0.0400")
            child.get_by_role("radio", name="HANDLE HOLE", exact=True).press("Space")
            expect(diameter).to_have_value("0.5")
            expect(distance).to_have_value("1.25")
            # Incomplete and conflicting dimensions keep a labeled old drawing,
            # remove the price and disable every purchase action.
            bore = child.get_by_role("spinbutton", name="Bore diameter (in.)", exact=True)
            for invalid, affected in (("", ["bore_dia"]), ("5", ["bore_dia", "paddle_dia"])):
                bore.fill(invalid)
                bore.press("Tab")
                for field in affected:
                    expect(child.locator(f'[data-field-error="{field}"]')).to_be_visible()
                    expect(child.locator(f'.st-key-quote_field_{field}')).to_have_css("outline-color", "rgb(224, 36, 36)")
                expect(child.get_by_test_id("stMetric")).to_have_count(0)
                expect(child.get_by_role("button", name="Continue to secure checkout", exact=True)).to_be_disabled()
                expect(child.get_by_role("button", name="Add another plate", exact=True)).to_be_disabled()
                expect(visible).to_be_visible()
                expect(visible.locator('[data-feature="od-dimension-label"]')).to_have_text("Ø4.000")
                if width >= 901:
                    expect(page.locator("#configurator-feedback")).to_contain_text("Last valid configuration shown")
                    expect(page.locator("#configurator-feedback")).not_to_contain_text("$100")
                else:
                    expect(child.get_by_text("Last valid configuration shown. Correct the highlighted fields to update the drawing.", exact=True)).to_be_visible()
                page.screenshot(path=str(tmp_path / f"validation-{width}-{'empty' if not invalid else 'conflict'}.png"), full_page=True)
            bore.fill("1.000")
            bore.press("Tab")
            expect(child.locator('[data-field-error]')).to_have_count(0)
            expect(child.get_by_test_id("stMetric")).to_have_count(2)
            expect(visible).to_be_visible()
            assert child.get_by_test_id("stException").count() == 0
        finally:
            (tmp_path / "browser.log").write_text("\n".join(diagnostics))
            page.screenshot(path=str(tmp_path / f"landing-{width}.png"), full_page=True)
            browser.close()


@pytest.mark.parametrize("configurator", [True], indirect=True, ids=["seven-enabled"])
@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "mobile"])
def test_enabled_seven_remains_selectable(configurator, width, tmp_path):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000})
        page.route("**/*", lambda request: request.continue_()
                   if request.request.url.startswith(configurator + "/") else request.abort())
        try:
            page.goto(configurator + "/Quote")
            expect(page.get_by_role("radio", name="7 Days", exact=True)).to_be_visible(timeout=30000)
            assert_expedited_display(page, seven_enabled=True)
            for label in ("7 Days", "21 calendar days", "14 calendar days"):
                choice = page.get_by_role("radio", name=label, exact=True)
                choice.press("Space")
                expect(choice).to_be_checked()
                expect(page.get_by_role("img", name="Handled orifice plate configuration drawing", exact=True)).to_be_visible()
            page.locator('.st-key-lead_time_choices').screenshot(path=str(tmp_path / f"lead-time-on-{width}.png"))
            assert page.get_by_test_id("stException").count() == 0
        finally:
            browser.close()


@pytest.mark.parametrize("embedded", [False, True], ids=["direct-status", "embedded-status"])
def test_idle_status_survives_reruns_and_resize(configurator, embedded, tmp_path):
    """Observe painted frames, not just source, with declined diagnostics enabled."""
    from urllib.parse import quote

    landing = ROOT / "o-plates landing"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.context.grant_permissions(["local-network-access"], origin="https://o-plates.com")
        choice = quote(json.dumps({"version": "journey-2026-10-v1", "allow": False,
                                   "internal": True, "at": int(time.time() * 1000)}))
        page.context.add_cookies([
            {"name": "oplates_journey_choice", "value": choice, "url": configurator},
            {"name": "oplates_journey_choice", "value": choice, "url": "https://o-plates.com"},
        ])

        def isolated(route):
            url = route.request.url
            if url.startswith(configurator + "/"):
                if urlsplit(url).path.endswith("/journey.js"):
                    response = route.fetch()
                    return route.fulfill(response=response, body=response.text().replace(
                        "https://quote.o-plates.com", configurator))
                return route.continue_()
            if not url.startswith("https://o-plates.com/"):
                return route.abort()
            if urlsplit(url).path == "/journey-config.js":
                return route.fulfill(content_type="application/javascript", body=
                    "window.OPLATES_JOURNEY={enabled:true,endpoint:'https://orifice-pricing-api.onrender.com'};")
            path = (landing / (urlsplit(url).path.lstrip("/") or "index.html")).resolve()
            if not path.is_relative_to(landing) or not path.is_file():
                return route.fulfill(status=404, body="")
            if path.suffix in {".html", ".js", ".css"}:
                return route.fulfill(body=path.read_text().replace("https://quote.o-plates.com", configurator),
                                     content_type={".html": "text/html", ".js": "application/javascript", ".css": "text/css"}[path.suffix])
            return route.fulfill(path=path)

        page.route("**/*", isolated)
        # This runs only inside the disposable, network-isolated test browser.
        page.add_init_script("""(() => {
            let started=false, original=null;
            window.statusEvidence={frames:0,missing:0,replaced:0,publications:0};
            window.addEventListener('message', e => {
                if(e.data?.type==='streamlit:setComponentValue')window.statusEvidence.publications++;
            });
            function sample(){
                const current=[...document.querySelectorAll('strong')].find(
                    e=>e.textContent==='Ready to read your print.');
                if(current && !started){started=true;original=current;}
                if(started){
                    const m=window.statusEvidence;m.frames++;
                    const r=current?.getBoundingClientRect();
                    if(!current || !r.width || !r.height || getComputedStyle(current).visibility==='hidden')m.missing++;
                    if(current && current!==original){m.replaced++;original=current;}
                }
                requestAnimationFrame(sample);
            }
            requestAnimationFrame(sample);
        })();""")
        try:
            page.goto("https://o-plates.com/#configurator" if embedded else configurator + "/Quote")
            if embedded:
                page.locator("#plate-configurator").scroll_into_view_if_needed()
            child = page.frame_locator("#plate-configurator") if embedded else page
            status = child.get_by_text("Ready to read your print.", exact=True)
            expect(status).to_be_visible(timeout=30000)
            root = child.locator('.st-key-configurator_starter')
            # The component really booted; a disabled diagnostics fixture cannot pass this gate.
            expect(child.locator('iframe[title="journey.ui.oplates_journey"]')).to_be_attached()
            root.evaluate("el => new Promise(resolve => setTimeout(resolve, 1500))")
            assert root.evaluate("el => typeof el.ownerDocument.defaultView.__oplatesJourneyEmit") == "function"
            child.get_by_role("radio", name="316 SS Added corrosion resistance.", exact=True).press("Space")
            expect(child.locator('[data-feature="web-material"]')).to_have_text("316 STAINLESS STEEL")
            diameter = child.get_by_role("spinbutton", name="Plate outside diameter (in.)", exact=True)
            diameter.fill("4.000")
            diameter.press("Tab")
            expect(child.locator('[data-feature="od-dimension-label"]')).to_have_text("Ø4.000")
            child.get_by_role("radio", name="21 calendar days", exact=True).press("Space")
            expect(child.get_by_role("radio", name="21 calendar days", exact=True)).to_be_checked()
            child.get_by_role("button", name="Sign in", exact=True).click()
            expect(child.get_by_role("dialog")).to_be_visible()
            child.get_by_role("button", name="Close", exact=True).click()
            expect(child.get_by_role("dialog")).to_have_count(0)
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 1000})
                expect(status).to_be_visible()
                root.evaluate("el => new Promise(resolve => setTimeout(resolve, 500))")
            evidence = root.evaluate("el => el.ownerDocument.defaultView.statusEvidence")
            (tmp_path / "status-stability.json").write_text(json.dumps(evidence, indent=2))
            assert evidence["frames"] > 60
            assert evidence["missing"] == 0, evidence
            assert evidence["replaced"] == 0, evidence
            # Initial declined identity may publish once, observations must not republish it.
            assert evidence["publications"] == 1, evidence
            expect(child.get_by_test_id("stException")).to_have_count(0)
        finally:
            page.screenshot(path=str(tmp_path / "status-stability.png"), full_page=True)
            browser.close()
