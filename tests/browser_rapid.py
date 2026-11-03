"""Ordered network barriers reproduce edits made before an older rerun arrives.

Only synthetic loopback endpoints are reachable. No click sleeps or retries.
"""
import json
import time

import pytest
from playwright.sync_api import expect, sync_playwright
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from browser_auth import customer_app, sign_in, await_quote


class RerunBarrier:
    """Delay an older response, then hold the next request until it is checked."""
    def __init__(self):
        self.armed = False
        self.responses = []
        self.requests = []
        self.trace = []
        self.old_lead = None
        self.new_lead = None

    def route(self, client):
        server = client.connect_to_server()
        self.client, self.server = client, server

        def request(data):
            msg = BackMsg.FromString(data)
            if msg.WhichOneof("type") == "rerun_script":
                widgets = {w.id: list(w.string_array_value.data)
                           for w in msg.rerun_script.widget_states.widgets
                           if w.id.endswith(("quote_field_chamfer", "quote_field_ships_in_days"))}
                self.trace.append(dict(event="request", time=time.monotonic(), widgets=widgets))
                lead = next((v for k, v in widgets.items() if k.endswith("quote_field_ships_in_days")), [])
                if self.armed and lead == [f"{self.new_lead} calendar days"]:
                    self.requests.append(data)
                    return
            server.send(data)

        def response(data):
            msg = ForwardMsg.FromString(data)
            if msg.WhichOneof("type") == "delta" and msg.delta.WhichOneof("type") == "new_element":
                element = msg.delta.new_element
                if element.WhichOneof("type") == "button_group":
                    control = element.button_group
                    if control.id.endswith(("quote_field_chamfer", "quote_field_ships_in_days")):
                        self.trace.append(dict(event="control", time=time.monotonic(), id=control.id,
                            path=list(msg.metadata.delta_path), set_value=control.set_value,
                            raw_values=list(control.raw_values)))
            if self.armed:
                self.responses.append(data)
            else:
                client.send(data)
        client.on_message(request)
        server.on_message(response)

    def arm(self, old, new):
        self.responses.clear()
        self.requests.clear()
        self.old_lead, self.new_lead = old, new
        self.armed = True
        self.trace.append(dict(event="arm", old=old, new=new, time=time.monotonic()))

    def old_response_ready(self):
        return any(ForwardMsg.FromString(data).WhichOneof("type") == "script_finished"
                   for data in self.responses)

    def release_responses(self):
        for data in self.responses:
            self.client.send(data)
        self.responses.clear()

    def release_requests(self):
        self.armed = False
        for data in self.requests:
            self.server.send(data)
        self.requests.clear()


def until(page, condition):
    deadline = time.monotonic() + 15
    while not condition() and time.monotonic() < deadline:
        # Service protocol callbacks while waiting for an explicit event barrier.
        page.wait_for_timeout(10)
    assert condition(), "Expected rerun protocol event did not arrive"


@pytest.mark.parametrize("embedded", [False, True], ids=["standalone-desktop", "embedded-mobile"])
def test_rapid_conditional_edits(customer_app, embedded, tmp_path):
    state, api = customer_app
    barrier = RerunBarrier()
    dom = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=dict(width=390, height=844) if embedded else dict(width=1440, height=1000))
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith((api + "/", state["ui"] + "/")) else route.abort())
        page.route_web_socket("**/_stcore/stream", barrier.route)
        page.expose_function("recordControlEvent", lambda event: dom.append(dict(time=time.monotonic(), **event)))
        page.add_init_script("""for (const kind of ['pointerdown','pointerup','click']) {
          document.addEventListener(kind, e => {
            const button = e.target.closest('button');
            if (button?.getAttribute('role') === 'radio') window.recordControlEvent({kind, label:button.innerText, checked:button.getAttribute('aria-checked')});
          }, true);
        }
        const observe = nodes => [...nodes].flatMap(n => n.nodeType === 1 ? [n, ...n.querySelectorAll('button[role=radio]')] : []).filter(n => n.matches?.('button[role=radio]'));
        new MutationObserver(changes => { for (const c of changes) {
          for (const [kind,nodes] of [['mount',c.addedNodes],['unmount',c.removedNodes]])
            for (const b of observe(nodes)) window.recordControlEvent({kind,label:b.innerText,checked:b.getAttribute('aria-checked')});
        }}).observe(document, {childList:true,subtree:true});""")
        try:
            page.goto(api + "/landing" if embedded else state["ui"] + "/Quote")
            scope = page.frame_locator("#plate-configurator") if embedded else page
            no = scope.get_by_role("radio", name="NO CHAMFER Square bore edge.", exact=True)
            yes = scope.get_by_role("radio", name="CHAMFERED BORE Add a chamfer to the bore edge.", exact=True)
            leads = {n: scope.get_by_role("radio", name=f"{n} calendar days", exact=True) for n in (14,21)}
            width = scope.get_by_role("spinbutton", name="Chamfer Width (in.)", exact=True)
            app = scope.get_by_test_id("stApp")
            expect(no).to_be_checked()
            for phase in ("before-auth", "after-otp", "after-routes"):
                if phase == "after-otp":
                    sign_in(scope)
                if phase == "after-routes":
                    for route, heading in (("My Orders", "My Orders"), ("Quote Cart", "Quote Cart")):
                        scope.get_by_role("link", name=route, exact=True).click()
                        expect(scope.get_by_role("heading", name=heading, exact=True)).to_be_visible()
                    scope.get_by_role("link", name="Configure your plate", exact=True).click()
                yes.press("Space")
                expect(width).to_be_visible()
                expect(leads[14]).to_be_checked()
                await_quote(state, dict(chamfer=True, ships_in_days=14))
                expect(app).to_have_attribute("data-test-script-state", "notRunning")
                for cycle in range(4):
                    for chamfer, old, new in ((False,14,21), (True,21,14)):
                        before = len(state["quotes"])
                        barrier.arm(old, new)
                        (yes if chamfer else no).focus()
                        (yes if chamfer else no).click()
                        until(page, barrier.old_response_ready)
                        # The old render is buffered, so both controls remain on
                        # screen. A genuine pointer click selects the new value.
                        leads[new].focus()
                        leads[new].click()
                        until(page, lambda: bool(barrier.requests))
                        expect(leads[new]).to_be_checked()
                        barrier.release_responses()
                        expect(app).to_have_attribute("data-test-script-state", "notRunning")
                        expect(leads[new]).to_have_count(1)
                        # This is the critical assertion: an older server delta
                        # must not replace an accepted, newer customer edit.
                        expect(leads[new]).to_be_checked()
                        expect(yes if chamfer else no).to_be_checked()
                        barrier.release_requests()
                        until(page, lambda: len(state["quotes"]) > before)
                        until(page, lambda: len(state["quotes"]) > before and state["quotes"][-1].get("chamfer") is chamfer and state["quotes"][-1].get("ships_in_days") == new)
                        expect(app).to_have_attribute("data-test-script-state", "notRunning")
                        expect(leads[new]).to_be_checked()
                        expect(width).to_have_count(1 if chamfer else 0)
                        expect(scope.get_by_test_id("stMetric")).to_have_count(2)
                        expect(scope.get_by_test_id("stException")).to_have_count(0)
            assert state["sends"] == 1
        finally:
            barrier.release_requests()
            (tmp_path / "rapid-trace.json").write_text(json.dumps(barrier.trace, indent=2))
            (tmp_path / "dom-events.json").write_text(json.dumps(dom, indent=2))
            (tmp_path / "quote-payloads.json").write_text(json.dumps(state["quotes"], indent=2))
            page.screenshot(path=str(tmp_path / "rapid.png"), full_page=True)
            browser.close()
