from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from frozen_plate import api
from frozen_plate.repository import Repository
from frozen_plate.control_data import bounded_summary, SCOPE
from frozen_plate.download_names import dxf_delivery_name
from manufacturing_control.client import OwnerClient, PortalError, clear_owner_session
from prototype_manufacturing import sample_spec
from ui_harness import customer_page_test


@pytest.mark.parametrize(
    "material,thickness,expected",
    [
        ("304", 0.125, "304-.125"),
        ("316", 0.25, "316-.250"),
        ("Carbon Steel", 0.375, "CS-.375"),
        ("304 stainless steel", 0.5, "304-.500"),
        ("316 Stainless Steel", 0.1875, "316-.1875"),
        ("CS", 0.1254, "CS-.1254"),
        ("304", 1, "304-1.000"),
        ("304", 1.125, "304-1.125"),
    ],
)
def test_names_preserve_canonical_precision(material, thickness, expected):
    assert (
        dxf_delivery_name(
            {"material": material, "thickness": thickness}, "OP-10001", "line-103", 24
        )
        == f"OP-{expected}-OP10001-L103-R24.dxf"
    )


@pytest.mark.parametrize(
    "spec,order,line,revision",
    [
        ({"material": "unobtainium", "thickness": 0.125}, "OP-0014", "line-1", 1),
        ({"material": "304", "thickness": float("nan")}, "OP-0014", "line-1", 1),
        ({"material": "304", "thickness": float("inf")}, "OP-0014", "line-1", 1),
        ({"material": "304", "thickness": 0}, "OP-0014", "line-1", 1),
        ({"material": "304", "thickness": 0.125}, "OP-0014\r\nx: bad", "line-1", 1),
        ({"material": "304", "thickness": 0.125}, "OP-0014", "../line-1", 1),
        ({"material": "304", "thickness": 0.125}, "OP-0014", "line-0", 1),
        ({"material": "304", "thickness": 0.125}, None, "line-1", 1),
        ({"material": "304", "thickness": 0.125}, "OP-0014", "line-1", True),
    ],
)
def test_unsafe_or_unknown_names_fail_closed(spec, order, line, revision):
    with pytest.raises(ValueError):
        dxf_delivery_name(spec, order, line, revision)


@pytest.mark.parametrize(
    "session,payload,expected",
    [
        (None, {}, "UNKNOWN"),
        ("", {}, "UNKNOWN"),
        ("broken", {}, "UNKNOWN"),
        ("cs_live_", {}, "UNKNOWN"),
        ("cs_live_x\n", {}, "UNKNOWN"),
        (7, {}, "UNKNOWN"),
        ("cs_test_abc", {}, "TEST"),
        ("cs_live_abc", {}, "LIVE"),
        ("cs_test_abc", [], "TEST"),
        (
            "cs_test_abc",
            {"_payment": {"mode": "owner_test", "owner_id": "c"}},
            "OWNER TEST",
        ),
    ],
)
def test_payment_mode(session, payload, expected):
    from api_app import _admin_payment_mode

    assert (
        _admin_payment_mode(
            SimpleNamespace(
                stripe_session_id=session, quote_payload=payload, customer_id="c"
            )
        )
        == expected
    )


def make_plate(repo, order="o", line="line-1"):
    pid = repo.create_plate(
        order_id=order,
        line_id=line,
        configuration_id="cfg-" + line,
        customer_id="c",
        actor="fixture",
    )
    rev = repo.create_revision(
        pid,
        sample_spec(),
        expected_current=None,
        reason="fixture",
        actor="fixture",
        source_snapshot={},
    )
    return pid, rev


def test_snapshot_scope_no_artifact_reads_or_mutation(tmp_path, monkeypatch):
    repo = Repository(tmp_path, "test-" * 20)
    pid, r1 = make_plate(repo)
    _, r2 = make_plate(repo, line="line-2")
    repo.approve(repo.create_delivery(r1["id"])["token"], "c")
    make_plate(repo, order="outside")
    with repo.connect() as db:
        before = "\n".join(db.iterdump())
    monkeypatch.setattr(
        repo,
        "_verified",
        lambda *_: (_ for _ in ()).throw(AssertionError("metadata read fetched bytes")),
    )
    summary = bounded_summary(
        [
            {"id": "o", "status": "completed"},
            {"id": "missing", "status": "completed"},
            {"id": "pending", "status": "pending"},
        ],
        repo,
    )
    assert (
        summary["partial"] is True
        and summary["scope"] == SCOPE + " · Active"
        and summary["snapshot_at"]
    )
    assert summary["counts"]["approved"] == 1
    assert summary["counts"]["awaiting_approval"] == 1
    assert summary["counts"]["record_unavailable"] == 1
    assert (
        summary["counts"]["hold"] is None
        and summary["counts"]["email_reconciliation"] is None
    )
    assert len(summary["orders"]) == 2 and len(summary["orders"][0]["lines"]) == 2
    with repo.connect() as db:
        assert "\n".join(db.iterdump()) == before


def test_delivery_alias_exact_bytes_gate_and_immutable_records(tmp_path, monkeypatch):
    repo = Repository(tmp_path, "test-" * 20)
    pid, rev = make_plate(repo)
    monkeypatch.setattr(api, "repository", lambda: repo)

    def auth(x_api_key: str | None = Header(None)):
        if x_api_key != "owner":
            raise HTTPException(401)

    app = FastAPI()
    app.include_router(
        api.router(lambda: "c", auth, lambda _: {"order_number_display": "OP-0014"})
    )
    client = TestClient(app)
    headers = {"x-api-key": "owner"}
    path = f"/admin/frozen-plates/revisions/{rev['id']}/dxf"
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"authorization": "Bearer customer"}).status_code
        == 401
    )
    assert client.get(path, headers=headers).status_code == 409
    repo.approve(repo.create_delivery(rev["id"])["token"], "c")
    original = repo.revision(rev["id"])
    with repo.connect() as db:
        before = "\n".join(db.iterdump())
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="OP-304-.125-OP0014-L01-R1.dxf"'
    )
    assert sha256(response.content).hexdigest() == rev["artifacts"]["dxf"]["sha256"]
    assert len(response.content) == rev["artifacts"]["dxf"]["size"]
    assert repo.revision(rev["id"]) == original
    with repo.connect() as db:
        assert "\n".join(db.iterdump()) == before
    r2 = repo.create_revision(
        pid,
        replace(sample_spec(), thickness=0.25),
        expected_current=rev["id"],
        reason="fixture",
        actor="fixture",
        source_snapshot={},
    )
    assert client.get(path, headers=headers).status_code == 409
    assert (
        dxf_delivery_name(json.loads(r2["spec_json"]), "OP-0014", "line-1", 2)
        != "OP-304-.125-OP0014-L01-R1.dxf"
    )
    assert (
        dxf_delivery_name(json.loads(rev["spec_json"]), "OP-0014", "line-2", 1)
        == "OP-304-.125-OP0014-L02-R1.dxf"
    )


def test_client_integrity_and_redirects(monkeypatch):
    import requests

    rev = {
        "id": "r",
        "artifacts": {"pdf": {"sha256": sha256(b"exact").hexdigest(), "size": 5}},
    }
    get = Mock(return_value=SimpleNamespace(status_code=200, content=b"bad"))
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(PortalError, match="integrity"):
        OwnerClient("https://fixture", "owner").artifact(rev, "pdf", "r.pdf")
    assert get.call_args.kwargs["allow_redirects"] is False
    for status, category in [
        (401, "authorization"),
        (404, "missing"),
        (409, "conflict"),
        (429, "rate"),
        (503, "service"),
        (302, "service"),
    ]:
        get.return_value = SimpleNamespace(status_code=status)
        with pytest.raises(PortalError, match=category):
            OwnerClient("https://fixture", "owner").get("/admin/orders")
    get.reset_mock()
    with pytest.raises(PortalError):
        OwnerClient("https://fixture", "").get("/admin/orders")
    get.assert_not_called()


def configure_ui(monkeypatch):
    import requests

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("API_BASE", "https://oplates-pricing-api-staging.onrender.com")
    content = b"%PDF-exact-fixture"
    rev = {
        "id": "r1",
        "number": 1,
        "plate_id": "p1",
        "spec_sha256": "a" * 64,
        "spec_json": json.dumps({"material": "304", "thickness": 0.125, "quantity": 2}),
        "artifacts": {
            "pdf": {
                "filename": "stored.pdf",
                "size": len(content),
                "sha256": sha256(content).hexdigest(),
            }
        },
    }
    plate = dict(
        id="p1",
        order_id="o1",
        line_id="line-1",
        lifecycle="READY_FOR_CUSTOMER_CONFIRMATION",
        current_revision="r1",
    )
    order = dict(
        id="o1",
        status="completed",
        order_number_display="OP-0014",
        created_at="2026-10-14T12:00:00Z",
        payment_mode="OWNER TEST",
    )
    summary = {
        "orders": [dict(order, lines=[])],
        "scope": SCOPE,
        "partial": True,
        "snapshot_at": "2026-10-14T12:00:00Z",
        "counts": dict(
            awaiting_approval=0,
            approved=0,
            ready_for_release=0,
            sourcing_recorded=0,
            record_unavailable=1,
        ),
    }
    calls = []

    def get(url, headers, **kwargs):
        calls.append(url)
        if headers["x-api-key"] != "fixture-owner":
            return SimpleNamespace(status_code=401)
        path = url.split(".com")[-1]
        data = {
            "/admin/orders": [order],
            "/admin/sales": {"total_cents": 0, "order_count": 0, "start": "2025-11-01", "end": "2026-10-17", "points": [{"date": "2026-10-01", "amount_cents": 0, "order_count": 0}], "basis": "Recorded paid timestamp (UTC). Not net revenue."},
            "/admin/manufacturing-summary": summary,
            "/admin/orders/o1": order,
            "/admin/frozen-plates": [plate],
            "/admin/frozen-plates/p1/revisions": [rev],
            "/admin/frozen-plates/p1": dict(
                plate=plate, revision=rev, approvals=[], deliveries=[], sourcing=[]
            ),
        }
        if path.endswith("/artifact/pdf"):
            return SimpleNamespace(status_code=200, content=content)
        assert path in data, path
        return SimpleNamespace(status_code=200, json=lambda: data[path])

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("write"))
    )
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(Path(__file__).resolve().parents[1] / "owner_app/main.py", default_timeout=20).run(), calls, rev


def test_session_unlock_lock_no_lazy_reads_and_selected_context(monkeypatch):
    app, calls, rev = configure_ui(monkeypatch)
    assert not calls
    app.text_input[0].set_value("fixture-owner")
    next(b for b in app.button if b.label == "Unlock").click().run()
    assert not app.exception
    # TEST records remain reviewable but cannot inflate production attention.
    overview = next(e.value for e in app.markdown if '<div class="mc-grid">' in e.value)
    assert 'Owner attention</div><div class="mc-number">0</div>' in overview
    assert "owner_admin_credential" not in app.session_state
    next(b for b in app.button if b.label == "OP-0014").click().run()
    assert not app.exception and app.session_state["mc_order"] == "o1"
    assert any("OWNER TEST" in e.value for e in app.markdown)
    assert not any("/artifact/" in url or url.endswith("/dxf") for url in calls)
    import requests

    monkeypatch.setattr(
        requests, "get", lambda *a, **k: SimpleNamespace(status_code=429)
    )
    next(b for b in app.button if b.label == "Refresh").click().run()
    assert app.error and app.session_state["mc_order"] == "o1"
    next(b for b in app.button if b.label == "Lock").click().run()
    assert not app.exception
    assert app.text_input[0].value == "" and not app.get("download_button")
    assert "mc_key" not in app.session_state and "mc_snapshot" not in app.session_state


def test_clear_session_only_owner_data():
    state = {
        "mc_key": "secret",
        "mc_order": "o",
        "mc_snapshot": {"private": True},
        "owner_admin_credential": "secret",
        "customer": "preserve",
    }
    clear_owner_session(state)
    assert state == {"customer": "preserve"}


def test_summary_route_requires_owner(monkeypatch):
    import api_app

    monkeypatch.setattr(api_app, "ADMIN_API_KEY", "owner")
    client = TestClient(api_app.app)
    assert client.get("/admin/manufacturing-summary").status_code == 401
    assert (
        client.get(
            "/admin/manufacturing-summary", headers={"authorization": "Bearer customer"}
        ).status_code
        == 401
    )
