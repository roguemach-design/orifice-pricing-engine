"""Native required controls in a loopback-only probe; no auth/API/production data."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture
def required_probe(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "required_probe.py"
    script.write_text('''import json
import streamlit as st
from bore_edge_control import bore_edge_choice
from customer_controls import lead_time_choices

if "canonical" not in st.session_state:
    st.session_state.canonical = dict(chamfer=None, ships_in_days=None)
if st.button("Clear required selections"):
    st.session_state.canonical = dict(chamfer=None, ships_in_days=None)
    st.session_state.bore = None
    st.session_state.lead = None
if st.button("Disable 21 days"):
    st.session_state.only14 = True
hidden = st.checkbox("Hide bore control")
saved = st.session_state.canonical
bore = saved["chamfer"] if hidden else bore_edge_choice(key="bore", committed_value=saved["chamfer"])
if bore is True:
    st.number_input("Chamfer width", value=0.04)
lead = lead_time_choices("Lead time", [14] if st.session_state.get("only14") else [14, 21],
                         key="lead", committed_value=saved["ships_in_days"])
st.session_state.canonical = dict(chamfer=bore, ships_in_days=lead)
st.code(json.dumps(st.session_state.canonical))
st.button("Quote permitted", disabled=bore is None or lead is None)
''')
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {key: os.environ[key] for key in ("PATH", "LANG") if key in os.environ}
    env.update(HOME=str(tmp_path), PYTHONPATH=str(root))
    with (tmp_path / "probe.log").open("w+") as log:
        process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(script),
            "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=true",
            "--browser.gatherUsageStats=false", "--global.developmentMode=false"],
            cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                try:
                    with urlopen(url + "/_stcore/health", timeout=1):
                        break
                except OSError:
                    time.sleep(.2)
            yield url
        finally:
            process.terminate()
            process.wait(timeout=15)
            log.seek(0)
            print("Required-control probe:", log.read())


@pytest.mark.parametrize("embedded", [False, True])
def test_unresolved_required_choices_remount_and_availability(required_probe, embedded, tmp_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.route("**/*", lambda route: route.continue_()
                   if route.request.url.startswith(required_probe + "/") else route.abort())
        try:
            if embedded:
                page.set_content(f'<iframe id="probe" src="{required_probe}" style="width:100%;height:1800px"></iframe>')
                scope = page.frame_locator("#probe")
            else:
                page.goto(required_probe)
                scope = page
            no = scope.get_by_role("radio", name="NO CHAMFER Square bore edge.", exact=True)
            yes = scope.get_by_role("radio", name="CHAMFERED BORE Add a chamfer to the bore edge.", exact=True)
            lead14 = scope.get_by_role("radio", name="14 calendar days", exact=True)
            lead21 = scope.get_by_role("radio", name="21 calendar days", exact=True)
            quote = scope.get_by_role("button", name="Quote permitted", exact=True)
            payload = scope.get_by_test_id("stCode")
            expect(no).not_to_be_checked()
            expect(yes).not_to_be_checked()
            expect(quote).to_be_disabled()
            expect(payload).to_contain_text('"chamfer": null')
            no.click()
            lead21.click()
            expect(quote).to_be_enabled()
            expect(no).to_be_checked()
            expect(payload).to_contain_text('"chamfer": false')
            hidden = scope.get_by_role("checkbox", name="Hide bore control", exact=True)
            hidden.press("Space")
            expect(hidden).to_be_checked()
            expect(no).to_have_count(0)
            hidden.press("Space")
            expect(hidden).not_to_be_checked()
            expect(no).to_be_checked()
            expect(lead21).to_be_checked()
            yes.click()
            expect(scope.get_by_role("spinbutton", name="Chamfer width", exact=True)).to_be_visible()
            expect(payload).to_contain_text('"chamfer": true')
            no.click()
            expect(scope.get_by_role("spinbutton", name="Chamfer width", exact=True)).to_have_count(0)
            expect(no).to_be_checked()
            scope.get_by_role("button", name="Disable 21 days", exact=True).click()
            expect(lead21).to_have_count(0)
            expect(lead14).not_to_be_checked()
            expect(quote).to_be_disabled()
            expect(payload).to_contain_text('"ships_in_days": null')
            lead14.click()
            expect(quote).to_be_enabled()
            assert json.loads(payload.inner_text()) == dict(chamfer=False, ships_in_days=14)
            scope.get_by_role("button", name="Clear required selections", exact=True).click()
            expect(no).not_to_be_checked()
            expect(yes).not_to_be_checked()
            expect(lead14).not_to_be_checked()
            expect(quote).to_be_disabled()
            expect(payload).to_contain_text('"chamfer": null')
            expect(scope.get_by_test_id("stException")).to_have_count(0)
        finally:
            page.screenshot(path=str(tmp_path / "required-controls.png"), full_page=True)
            browser.close()
