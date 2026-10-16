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
    next(r for r in app.radio if r.label == "Workspace").set_value(
        "Frozen Plates"
    ).run()
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
    next(r for r in app.radio if r.label == "Workspace").set_value(
        "Frozen Plates"
    ).run()
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
