"""Real owner navigation and versioned writes, isolated from production."""
import copy

import pytest
import streamlit as st

from manufacturing_control.client import OwnerClient
from test_pricing_configuration import client, OWNER, snapshot, save
from test_manufacturing_control import configure_ui
from test_checkout_control_ui import Client as CheckoutClient


@pytest.fixture
def owner_pricing(monkeypatch, client):
    api, factory = client
    app, _, _ = configure_ui(monkeypatch)
    original_read = OwnerClient.json
    checkout = CheckoutClient()
    writes = []

    def read(self, path, **kwargs):
        if path == "/admin/config/editor":
            return snapshot(api)
        if path == "/admin/checkout-control":
            return checkout.json(path)
        return original_read(self, path, **kwargs)

    def write(self, action, body):
        writes.append((action, copy.deepcopy(body)))
        response = api.request("PUT" if action == "save" else "POST",
                               "/admin/config" + ("" if action == "save" else "/" + action),
                               headers=OWNER, json=body)
        if response.status_code != 200:
            st.error(response.json()["detail"])
            return None
        return response.json()

    monkeypatch.setattr(OwnerClient, "json", read)
    monkeypatch.setattr(OwnerClient, "config_write", write)
    app.text_input[0].set_value("fixture-owner")
    next(b for b in app.button if b.label == "Unlock").click().run()
    next(r for r in app.radio if r.label == "Workspace").set_value("Pricing & Availability").run()
    assert not app.exception
    return app, api, writes, checkout


def test_seven_day_draft_navigation_discard_and_checkout_independence(owner_pricing):
    app, api, writes, checkout = owner_pricing
    before = snapshot(api)
    assert [t.label for t in app.tabs] == ["Availability", "Material prices", "Process & discounts", "Weights & limits", "Recovery"]
    for days, multiplier in {7: 2.3, 14: 1.6, 21: 1.0}.items():
        assert app.number_input(key=f"mc_price_lead_time_multipliers_{days}").value == multiplier
    assert app.number_input(key="mc_price_today_2_day_multiplier").value == 3.3
    app.checkbox(key="mc_price_lead_time_enabled_7").check().run()
    app.number_input(key="mc_price_default").set_value(21).run()
    assert not app.exception and not writes
    assert snapshot(api) == before
    assert next(b for b in app.button if b.label == "Save Changes").disabled
    next(r for r in app.radio if r.label == "Workspace").set_value("Overview").run()
    next(r for r in app.radio if r.label == "Workspace").set_value("Pricing & Availability").run()
    assert app.checkbox(key="mc_price_lead_time_enabled_7").value is True
    assert app.number_input(key="mc_price_default").value == 21
    app.radio(key="mc_pricing_workspace").set_value("Checkout Control").run()
    assert not app.exception and not writes and not checkout.writes
    app.radio(key="mc_pricing_workspace").set_value("Pricing settings").run()
    assert not app.exception
    assert app.checkbox(key="mc_price_lead_time_enabled_7").value is True
    assert next(b for b in app.button if b.label == "Reload configuration").disabled
    app.checkbox(key="mc_price_discard_ok").check().run()
    next(b for b in app.button if b.label == "Reload configuration").click().run()
    assert not app.exception and not writes
    assert app.checkbox(key="mc_price_lead_time_enabled_7").value is False
    assert app.number_input(key="mc_price_default").value == 14
    assert snapshot(api) == before


def test_seven_day_save_requires_current_review_and_version(owner_pricing):
    app, api, writes, _ = owner_pricing
    before = snapshot(api)
    app.checkbox(key="mc_price_lead_time_enabled_7").check().run()
    next(c for c in app.checkbox if c.label.startswith("I reviewed")).check().run()
    app.number_input(key="mc_price_default").set_value(7).run()
    assert next(b for b in app.button if b.label == "Save Changes").disabled
    assert not writes and snapshot(api) == before
    next(c for c in app.checkbox if c.label.startswith("I reviewed")).check().run()
    next(b for b in app.button if b.label == "Save Changes").click().run()
    assert not app.exception and len(writes) == 1
    enabled = snapshot(api)
    assert enabled["version"] != before["version"]
    assert enabled["config"]["lead_time_enabled"]["7"] is True
    assert enabled["config"]["default_lead_time_days"] == 7
    assert writes[0][1]["_version"] == before["version"]
    assert enabled["history"][0]["config"] == before["config"]
    app.number_input(key="mc_price_default").set_value(14).run()
    app.checkbox(key="mc_price_lead_time_enabled_7").uncheck().run()
    assert len(writes) == 1
    next(c for c in app.checkbox if c.label.startswith("I reviewed")).check().run()
    next(b for b in app.button if b.label == "Save Changes").click().run()
    assert not app.exception and len(writes) == 2
    disabled = snapshot(api)
    assert disabled["config"]["lead_time_enabled"]["7"] is False
    assert disabled["config"]["default_lead_time_days"] == 14
    assert disabled["config"]["lead_time_multipliers"] == before["config"]["lead_time_multipliers"]
    assert disabled["config"]["qty_discount_tiers"] == before["config"]["qty_discount_tiers"]


def test_stale_save_retains_owner_draft_and_cannot_overwrite_current_config(owner_pricing):
    app, api, writes, _ = owner_pricing
    before = snapshot(api)
    app.checkbox(key="mc_price_lead_time_enabled_7").check().run()
    assert save(api, before, mill_labor_per_hr=160).status_code == 200
    current = snapshot(api)
    next(c for c in app.checkbox if c.label.startswith("I reviewed")).check().run()
    next(b for b in app.button if b.label == "Save Changes").click().run()
    assert not app.exception and len(writes) == 1
    assert any("another session" in e.value for e in app.error)
    assert app.checkbox(key="mc_price_lead_time_enabled_7").value is True
    assert app.session_state["mc_price_dirty"] is True
    assert snapshot(api) == current
    assert current["config"]["lead_time_enabled"]["7"] is False


def send_tier_edit(app, delta):
    """AppTest has no grid setter: send the same widget JSON used by its browser.

    This updates native widget state, not the prohibited session_state assignment.
    """
    import json
    editor = next(d for d in app.dataframe if d.proto.id.endswith("-mc_price_tiers"))
    widgets = app._tree.get_widget_states()
    widgets.widgets.add(id=editor.proto.id, string_value=json.dumps(delta))
    app._run(widget_state=widgets)
    assert not app.exception


@pytest.mark.parametrize("delta,expected_count", [
    ({"edited_rows": {"1": {"multiplier": 0.96}}, "added_rows": [], "deleted_rows": []}, 5),
    ({"edited_rows": {}, "added_rows": [{"min_qty": 100, "multiplier": 0.85}], "deleted_rows": []}, 6),
    ({"edited_rows": {}, "added_rows": [], "deleted_rows": [4]}, 4),
])
def test_quantity_grid_edit_navigation_save_and_restore(owner_pricing, delta, expected_count):
    from pricing_configuration import changes
    app, api, writes, checkout = owner_pricing
    before = snapshot(api)
    send_tier_edit(app, delta)
    expected = copy.deepcopy(app.session_state["mc_price_tiers_draft"])
    assert len(expected) == expected_count
    assert app.session_state["mc_price_snapshot"]["config"] == before["config"]
    assert app.session_state["mc_price_tiers_input"] == before["config"]["qty_discount_tiers"]
    if delta["edited_rows"]:
        assert expected[1]["multiplier"] == 0.96
    # An unrelated rerun must not apply added/deleted rows twice.
    app.checkbox(key="mc_price_lead_time_enabled_7").check().run()
    assert app.session_state["mc_price_tiers_draft"] == expected
    next(r for r in app.radio if r.label == "Workspace").set_value("Overview").run()
    next(r for r in app.radio if r.label == "Workspace").set_value("Pricing & Availability").run()
    assert not app.exception and app.session_state["mc_price_tiers_draft"] == expected
    app.radio(key="mc_pricing_workspace").set_value("Checkout Control").run()
    app.radio(key="mc_pricing_workspace").set_value("Pricing settings").run()
    assert not app.exception and app.session_state["mc_price_tiers_draft"] == expected
    assert not writes and not checkout.writes and snapshot(api) == before
    next(c for c in app.checkbox if c.label.startswith("I reviewed")).check().run()
    next(b for b in app.button if b.label == "Save Changes").click().run()
    assert not app.exception and len(writes) == 1
    saved = snapshot(api)
    assert saved["config"]["qty_discount_tiers"] == expected
    assert saved["version"] != before["version"]
    field = "mc_price_recovery_restore" + saved["history"][0]["id"]
    app.text_input(key=field).set_value("RESTORE CONFIGURATION").run()
    next(b for b in app.button if b.label == "Apply recovery action").click().run()
    assert not app.exception and len(writes) == 2
    restored = snapshot(api)
    assert not changes(before["config"], restored["config"])
    assert app.session_state["mc_price_tiers_draft"] == before["config"]["qty_discount_tiers"]


def test_discard_removes_quantity_draft_without_saving(owner_pricing):
    app, api, writes, _ = owner_pricing
    before = snapshot(api)
    send_tier_edit(app, {"edited_rows": {}, "added_rows": [{"min_qty": 100, "multiplier": 0.85}], "deleted_rows": []})
    assert len(app.session_state["mc_price_tiers_draft"]) == 6
    app.checkbox(key="mc_price_discard_ok").check().run()
    next(b for b in app.button if b.label == "Reload configuration").click().run()
    assert not app.exception and not writes
    assert app.session_state["mc_price_tiers_draft"] == before["config"]["qty_discount_tiers"]
    assert snapshot(api) == before
