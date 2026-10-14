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
    app.include_router(api.router(lambda: "customer", admin, lambda _: None))
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
    from types import SimpleNamespace
    import requests
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('API_BASE','http://orifice-pricing-api:10000')
    monkeypatch.setenv('RENDER_SERVICE_ID','srv-d530k8re5dus73ahqr0g')
    monkeypatch.setenv('FROZEN_PLATE_ENABLED','true')
    contents = {'pdf':b'%PDF-exact-fixture','json':b'{"spec":"fixture"}'}
    artifacts = {k:dict(filename='R1.'+k,size=len(v),sha256=sha256(v).hexdigest()) for k,v in contents.items()}
    artifacts['dxf'] = dict(filename='R1.dxf',size=10,sha256='d'*64)
    rev = dict(id='r1',number=1,plate_id='p1',spec_sha256='a'*64,artifacts=artifacts)
    plate = dict(id='p1',order_id='o1',line_id='line-1',lifecycle='READY_FOR_CUSTOMER_CONFIRMATION',current_revision='r1')
    def get(url,headers,**kwargs):
        if headers['x-api-key'] != 'fixture-owner':
            return SimpleNamespace(status_code=401)
        path=url.split(':10000')[-1]
        data={
            '/admin/orders':[dict(id='o1',status='completed',order_number_display='OP-TEST',created_at='fixture')],
            '/admin/orders/o1':dict(id='o1',quote_payload={'lines':[{'configuration_id':'cfg'}]}),
            '/admin/frozen-plates':[plate],
            '/admin/frozen-plates/p1/revisions':[rev],
            '/admin/frozen-plates/p1':dict(plate=plate,revision=rev,approvals=[],deliveries=[],sourcing=[]),
            '/admin/frozen-plates/revisions/r1/email-status':dict(state='NOT_ATTEMPTED')}
        if '/artifact/' in path:
            return SimpleNamespace(status_code=200,content=contents[path.rsplit('/',1)[1]])
        assert path in data, path
        return SimpleNamespace(status_code=200,json=lambda:data[path])
    monkeypatch.setattr(requests,'get',get)
    monkeypatch.setattr(requests,'post',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('owner page write')))
    app=customer_page_test('pages/6_Internal_Sourcing.py').run()
    app.text_input[0].set_value('customer-key').run()
    assert not app.selectbox and app.error
    app.text_input[0].set_value('fixture-owner').run()
    assert not app.exception
    assert len(app.selectbox)==2
    assert len(app.get('download_button'))==2
    assert any('not approved' in i.value for i in app.info)
    assert not any('Record sourcing' in b.label or 'revised' in b.label for b in app.button)
