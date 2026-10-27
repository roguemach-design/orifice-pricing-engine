"""Navigation and selected immutable context regressions, using isolated fixtures."""

from copy import deepcopy
from test_manufacturing_control import configure_ui
from manufacturing_control.client import OwnerClient


def unlocked(monkeypatch):
    app, calls, rev = configure_ui(monkeypatch)
    app.text_input[0].set_value("fixture-owner")
    next(b for b in app.button if b.label == "Unlock").click().run()
    return app, calls, rev


def test_plate_workspace_independent_and_refresh_retains_selection(monkeypatch):
    app, calls, _ = unlocked(monkeypatch)
    next(b for b in app.button if b.label == "Frozen Plates").click().run()
    next(b for b in app.button if b.label == "line-1").click().run()
    assert not app.exception
    assert app.session_state["mc_nav"] == "Frozen Plates"
    assert app.session_state["mc_plate"] == "p1"
    assert app.query_params["plate"] == ["p1"]
    assert any(b.label == "View Associated Order" for b in app.button)
    next(b for b in app.button if b.label == "Refresh").click().run()
    assert app.session_state["mc_plate"] == "p1"
    assert app.session_state["mc_nav"] == "Frozen Plates"
    next(r for r in app.radio if r.label == "Workspace").set_value("Overview").run()
    next(b for b in app.button if b.label == "Frozen Plates").click().run()
    assert app.session_state["mc_plate"] == "p1"
    next(b for b in app.button if b.label == "View Associated Order").click().run()
    assert app.session_state["mc_nav"] == "Orders"
    assert app.session_state["mc_order"] == "o1"
    assert not any("/artifact/" in path for path in calls)
    next(b for b in app.button if b.label == "Lock").click().run()
    assert not app.query_params and "mc_plate" not in app.session_state


def test_multiple_lines_render_only_selected_revision(monkeypatch):
    app, calls, rev = unlocked(monkeypatch)
    original_json = OwnerClient.json
    plate2 = dict(id="p2", order_id="o1", line_id="line-2", current_revision="r2")
    rev2 = deepcopy(rev)
    rev2.update(id="r2", plate_id="p2", number=2)
    rev2["artifacts"]["pdf"]["filename"] = "line2.pdf"

    def read(self, path, **kwargs):
        if path == "/admin/frozen-plates":
            return original_json(self, path, **kwargs) + [plate2]
        if path == "/admin/frozen-plates/p2/revisions":
            return [rev2]
        if path == "/admin/frozen-plates/p2":
            return dict(
                plate=plate2, revision=rev2, approvals=[], sourcing=[], deliveries=[]
            )
        return original_json(self, path, **kwargs)

    monkeypatch.setattr(OwnerClient, "json", read)
    next(b for b in app.button if b.label == "OP-0014").click().run()
    assert not app.exception
    assert len(app.get("download_button")) == 1
    next(s for s in app.selectbox if s.label == "Plate / line").set_value("p2").run()
    assert not app.exception
    assert any(s.label == "Revision · line-2" for s in app.selectbox)
    assert not any(s.label == "Revision · line-1" for s in app.selectbox)
    assert len(app.get("download_button")) == 1
    assert any(b.label == "Download NC" and b.disabled for b in app.button)
    assert any(b.label == "Download Packaging DXF" and b.disabled for b in app.button)
    assert not any("/artifact/" in path for path in calls)


def test_reloaded_plate_link_still_requires_owner(monkeypatch):
    app, calls, _ = configure_ui(monkeypatch)
    app.query_params["plate"] = "p1"
    app.run()
    assert not calls
    assert any(b.label == "Unlock" for b in app.button)
    app.text_input[0].set_value("fixture-owner")
    next(b for b in app.button if b.label == "Unlock").click().run()
    assert not app.exception
    assert app.session_state["mc_nav"] == "Frozen Plates"
    assert app.session_state["mc_plate"] == "p1"


def test_invalid_login_never_creates_owner_session(monkeypatch):
    app, calls, _ = configure_ui(monkeypatch)
    app.text_input[0].set_value('invalid')
    next(b for b in app.button if b.label == 'Unlock').click().run()
    assert not app.exception
    assert 'mc_key' not in app.session_state
    assert 'mc_snapshot' not in app.session_state
    assert not app.get('download_button')
    assert len(calls) == 1 and calls[0].endswith('/admin/orders')
    assert any(b.label == 'Unlock' for b in app.button)


def test_overview_cards_ranges_five_recent_and_navigation(monkeypatch):
    app, calls, _ = unlocked(monkeypatch)
    snapshot = app.session_state['mc_snapshot']
    snapshot['orders'] = [dict(snapshot['orders'][0], id=f'o{i}', order_number_display=f'OP-{i:04d}') for i in range(8)]
    app.run()
    assert not app.exception
    assert len([b for b in app.button if b.label.startswith('OP-')]) == 5
    metrics = ''.join(m.value for m in app.markdown)
    assert metrics.count('class="mc-metric"') == 4
    for label in ['1 Year', '6 Months', '3 Months', '1 Month']:
        next(r for r in app.radio if r.label == 'Sales period').set_value(label).run()
        assert not app.exception
        assert any('LIVE paid order total · $0.00' in m.value for m in app.markdown)
    assert next(r for r in app.radio if r.label == 'Workspace').options == ['Overview','Orders','Checkout Control','Pricing & Availability','Customer Journey']
    next(b for b in app.button if b.label == 'View All Orders').click().run()
    assert app.session_state['mc_nav'] == 'Orders'


def test_dedicated_entry_point_is_locked_and_has_no_customer_routes(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    configure_ui(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'owner_app/main.py')).run()
    assert not app.exception
    assert any(b.label == 'Unlock' for b in app.button)
    assert not app.get('download_button')
    from streamlit.runtime.pages_manager import PagesManager
    # Entry point uses exactly one explicit callable page, never the customer page directory.
    source = (Path(__file__).resolve().parents[1] / 'owner_app/main.py').read_text()
    assert 'st.Page(run,' in source and 'pages/' not in source


def test_lead_time_comes_from_selected_frozen_source():
    from manufacturing_control.app import frozen_lead_days
    assert frozen_lead_days({'source_json': '{"configuration":{"ships_in_days":21}}'}) == 21
    assert frozen_lead_days({'source_json': '{"configuration":{"ships_in_days":7}}'}) == 7
    for source in ({}, {'source_json':'invalid'}, {'source_json':'[]'}):
        assert frozen_lead_days(source) is None
