from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import auth
import customer_orders_ui as ui
from ui_harness import customer_page_test


@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda **kw: None)
    monkeypatch.setattr(auth, "require_login", lambda *a: None)
    content = (Path(__file__).parent / "fixtures/legacy-v3e.pdf").read_bytes()
    revision = dict(
        id="revision-1",
        number=1,
        current=True,
        approved=True,
        approved_at="2026-10-27T12:00:00Z",
        created_at="2026-10-27T11:00:00Z",
        specifications={"material": "304"},
        pdf_sha256=sha256(content).hexdigest(),
        pdf_size=len(content),
        filename="drawing.pdf",
    )
    lines = [
        dict(
            line_id="line-1",
            specifications={"material": "304", "quantity": 1, "paddle_dia": 3},
        ),
        dict(
            line_id="line-2",
            specifications={
                "material": "316",
                "quantity": 2,
                "chamfer": True,
                "chamfer_width": 0.062,
            },
        ),
    ]
    order = dict(
        id="order-1",
        status="completed",
        order_number_display="OP-0018",
        payment_mode="OWNER TEST",
        created_at="2026-10-27T10:00:00Z",
        amount_total_usd=123.45,
        lines=lines,
        line_count=2,
    )
    plate = dict(
        id="plate-1",
        line_id="line-1",
        current_revision="revision-1",
        lifecycle="CUSTOMER_APPROVED",
        revisions=[revision],
    )
    state = dict(
        order=order,
        archive=[plate],
        content=content,
        calls=[],
        tampered=False,
        unavailable=False,
    )

    def get(path, **kwargs):
        state["calls"].append((path, kwargs))
        if state["unavailable"]:
            return SimpleNamespace(status_code=503)
        if path == "/me/order-history":
            data = {"orders": [order], "total": 1}
        elif path.endswith("/drawing-archive"):
            data = state["archive"]
        elif path.endswith("/pdf"):
            return SimpleNamespace(
                status_code=200,
                content=b"tampered" if state["tampered"] else content,
                headers={
                    "X-Artifact-SHA256": revision["pdf_sha256"],
                    "X-Frozen-Revision": revision["id"],
                },
            )
        else:
            data = order
        return SimpleNamespace(status_code=200, json=lambda: data)

    monkeypatch.setattr(ui, "api_get", get)
    return state


def test_cards_search_sort_multi_line_detail_and_real_pdf_preview(workspace):
    app = customer_page_test("pages/2_My_Orders.py").run()
    assert not app.exception and not app.selectbox(key="orders_sort").value is None
    assert all(s.label != "Select an order" for s in app.selectbox)
    app.text_input(key="orders_search").set_value("OP-0018").run()
    app.selectbox(key="orders_sort").set_value("Highest total").run()
    assert workspace["calls"][-1][1]["params"]["search"] == "OP-0018"
    assert workspace["calls"][-1][1]["params"]["sort"] == "total_high"
    app.button(key="order-open-order-1").click().run()
    assert not app.exception
    assert len([s for s in app.subheader if s.value.startswith("Plate ")]) == 2
    assert any(
        "Historical chamfer specification is incomplete" in w.value for w in app.warning
    )
    assert any("Current drawing R1 approved" in s.value for s in app.success)
    app.button(key="archive-view-revision-1").click().run()
    assert not app.exception
    assert len(app.get("image")) == 1
    assert any(d.label == "Download approved PDF" for d in app.get("download_button"))
    assert all("YOUR ORDER IS IN PRODUCTION" not in s.value for s in app.success)
    next(b for b in app.button if b.label == "← All orders").click().run()
    assert not app.exception and app.text_input(key="orders_search").value == "OP-0018"


def test_pdf_integrity_failure_never_renders_or_downloads(workspace):
    workspace["tampered"] = True
    app = customer_page_test("pages/2_My_Orders.py").run()
    app.button(key="order-open-order-1").click().run()
    app.button(key="archive-view-revision-1").click().run()
    assert not app.exception
    assert any("Drawing verification failed" in e.value for e in app.error)
    assert not app.get("download_button") and not app.get("image")


def test_service_errors_do_not_leak_provider_details_or_show_empty_history(workspace):
    workspace["unavailable"] = True
    app = customer_page_test("pages/2_My_Orders.py").run()
    assert not app.exception and app.error
    assert not any("No orders" in i.value for i in app.info)


def test_purchased_chamfer_definition_is_shown_without_substitution():
    from customer_orders_ui import purchased_details
    spec = dict(chamfer=True, chamfer_width=.062, chamfer_angle_degrees=45,
                chamfer_side='downstream', flow_orientation='left-to-right',
                chamfer_width_definition='radial-angle-from-face', internal_notes='hidden')
    shown = purchased_details(spec)
    assert shown['Chamfer angle (degrees)'] == 45
    assert shown['Chamfer face'] == 'downstream'
    assert shown['Section flow orientation'] == 'left-to-right'
    assert shown['Chamfer width definition'] == 'radial-angle-from-face'
    assert 'hidden' not in str(shown)
