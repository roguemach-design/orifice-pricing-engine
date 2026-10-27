"""Checkout controls remain usable independently of pricing state or availability."""
from streamlit.testing.v1 import AppTest
from test_checkout_control_ui import Client

ui_client = None


def test_checkout_workspace_never_fetches_or_saves_pricing():
    global ui_client
    ui_client = Client()  # Fails any request other than checkout-control.
    app = AppTest.from_string('''
from test_checkout_relocation import ui_client
from manufacturing_control.pricing import run
import streamlit as st
st.session_state["mc_pricing_workspace"] = "Checkout Control"
st.session_state["mc_price_dirty"] = True
st.session_state["mc_price_snapshot"] = {"untouched": True}
run(ui_client)
''').run()
    assert not app.exception
    assert app.selectbox[0].options == ["CLOSED", "TEST", "LIVE"]
    app.selectbox[0].set_value("TEST").run()
    app.text_input[0].set_value("APPLY TEST").run()
    next(b for b in app.button if b.label == "Save / Apply").click().run()
    assert app.metric[0].value == "TEST"
    assert app.session_state["mc_price_dirty"]
    assert app.session_state["mc_price_snapshot"] == {"untouched": True}
    next(c for c in app.checkbox if c.label.startswith("I confirm:")).check().run()
    next(b for b in app.button if b.label == "Close New Checkout").click().run()
    assert app.metric[0].value == "CLOSED"


def test_stale_top_level_checkout_navigation_redirects_safely():
    app = AppTest.from_string('''
import streamlit as st
import manufacturing_control.app as control
control.ui_enabled = lambda: True
control.OwnerClient = lambda *args: object()
import manufacturing_control.pricing as pricing
pricing.run = lambda client: st.write("Nested checkout destination")
st.session_state["mc_key"] = "synthetic"
st.session_state["mc_nav"] = "Checkout Control"
control.run()
''').run()
    assert not app.exception
    assert app.session_state["mc_nav"] == "Pricing & Availability"
    assert app.session_state["mc_pricing_workspace"] == "Checkout Control"
    workspace = next(r for r in app.radio if r.label == "Workspace")
    assert "Checkout Control" not in workspace.options
    assert workspace.value == "Pricing & Availability"
