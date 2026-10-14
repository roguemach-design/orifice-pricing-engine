from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from frozen_plate import api
from frozen_plate.repository import Repository
from prototype_manufacturing import sample_spec
from ui_harness import customer_page_test


def test_owner_exact_history_authorization_and_approval_gates(tmp_path, monkeypatch):
    repo = Repository(tmp_path, "owner-test-signing-" * 6)
    pid = repo.create_plate(
        order_id="completed-order",
        line_id="line-1",
        configuration_id="cfg",
        customer_id="customer",
        actor="test",
    )
    r1 = repo.create_revision(
        pid,
        sample_spec(),
        expected_current=None,
        reason="initial",
        actor="test",
        source_snapshot={"order": 1},
    )
    delivery = repo.create_delivery(r1["id"])
    monkeypatch.setattr(api, "repository", lambda: repo)

    def admin(x_api_key: str | None = Header(None)):
        if x_api_key != "owner-test-credential":
            raise HTTPException(401)

    app = FastAPI()
    app.include_router(api.router(lambda: "customer", admin, lambda _: {"order_number_display":"OP-0014"}))
    client = TestClient(app)
    headers = {"x-api-key": "owner-test-credential"}
    root = "/admin/frozen-plates/"
    for path in [
        pid,
        pid + "/revisions",
        "revisions/" + r1["id"] + "/artifact/pdf",
        "revisions/" + r1["id"] + "/artifact/json",
        "revisions/" + r1["id"] + "/dxf",
    ]:
        assert client.get(root + path).status_code == 401
        assert (
            client.get(
                root + path, headers={"authorization": "Bearer customer-token"}
            ).status_code
            == 401
        )
    assert (
        client.get(root + "revisions/" + r1["id"] + "/dxf", headers=headers).status_code
        == 409
    )
    for kind in ("pdf", "json"):
        response = client.get(
            root + "revisions/" + r1["id"] + "/artifact/" + kind, headers=headers
        )
        assert response.status_code == 200
        assert sha256(response.content).hexdigest() == r1["artifacts"][kind]["sha256"]
        assert response.headers["x-spec-sha256"] == r1["spec_sha256"]
        assert response.headers["x-frozen-revision"] == r1["id"]
    assert (
        client.get(
            root + "revisions/" + r1["id"] + "/artifact/dxf", headers=headers
        ).status_code
        == 404
    )
    repo.approve(delivery["token"], "customer")
    response = client.get(root + "revisions/" + r1["id"] + "/dxf", headers=headers)
    assert sha256(response.content).hexdigest() == r1["artifacts"]["dxf"]["sha256"]
    recorded = client.post(
        root + "revisions/" + r1["id"] + "/source",
        headers=headers,
        json={"route": "ALRO"},
    ).json()
    assert recorded["released"] is False
    r2 = repo.create_revision(
        pid,
        replace(sample_spec(), thickness=0.25),
        expected_current=r1["id"],
        reason="thickness",
        actor="test",
        source_snapshot={"order": 2},
    )
    history = client.get(root + pid + "/revisions", headers=headers).json()
    assert [r["id"] for r in history] == [r2["id"], r1["id"]]
    detail = client.get(
        root + pid, headers=headers, params={"revision_id": r1["id"]}
    ).json()
    assert detail["revision"]["id"] == r1["id"] and detail["approvals"]
    assert (
        client.get(root + "revisions/" + r1["id"] + "/dxf", headers=headers).status_code
        == 409
    )
    response = client.get(
        root + "revisions/" + r1["id"] + "/artifact/pdf", headers=headers
    )
    assert sha256(response.content).hexdigest() == r1["artifacts"]["pdf"]["sha256"]
    other = repo.create_plate(
        order_id="other",
        line_id="line-1",
        configuration_id="other",
        customer_id="customer",
        actor="test",
    )
    assert (
        client.get(
            root + other, headers=headers, params={"revision_id": r1["id"]}
        ).status_code
        == 404
    )
    damaged = repo.objects / r2["artifacts"]["pdf"]["object_key"]
    damaged.chmod(0o600)
    damaged.write_bytes(b"tampered")
    assert (
        client.get(
            root + "revisions/" + r2["id"] + "/artifact/pdf", headers=headers
        ).status_code
        == 409
    )
    assert repo.revision(r1["id"])["spec_sha256"] == r1["spec_sha256"]


def test_owner_page_is_hidden_and_anonymous_has_no_data_requests(monkeypatch):
    import requests

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_BASE", "http://orifice-pricing-api:10000")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-d530k8re5dus73ahqr0g")
    monkeypatch.setenv("FROZEN_PLATE_ENABLED", "true")
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("anonymous request")),
    )
    app = customer_page_test("pages/6_Internal_Sourcing.py").run()
    assert not app.exception
    assert not app.selectbox and not app.get("download_button")
    assert app.text_input[0].label == "Internal admin credential"
    source = Path("pages/6_Internal_Sourcing.py").read_text()
    assert "requests.post" not in source and "Create revised drawing" not in source
    navigation = Path("customer_navigation.py").read_text()
    assert (
        'url_path="Internal_Sourcing",\n                visibility="hidden"'
        in navigation
    )


def test_authorized_owner_page_shows_exact_downloads_without_writes(monkeypatch):
    from test_manufacturing_control import configure_ui
    app, calls, rev = configure_ui(monkeypatch)
    app.text_input[0].set_value('customer-key')
    next(b for b in app.button if b.label == 'Unlock').click().run()
    assert app.error and not app.get('download_button')
    next(b for b in app.button if b.label == 'Lock').click().run()
    app.text_input[0].set_value('fixture-owner')
    next(b for b in app.button if b.label == 'Unlock').click().run()
    assert not app.exception
    next(b for b in app.button if b.label == 'OP-0014').click().run()
    assert not app.exception
    assert len(app.get('download_button')) == 1
    assert not any('/artifact/' in c or c.endswith('/dxf') for c in calls)
    assert not any('Prepare' in b.label for b in app.button)
    assert not any('Record sourcing' in b.label or 'revised' in b.label for b in app.button)
