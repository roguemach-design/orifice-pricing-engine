"""Explicit TEST derivatives retain isolation, exact-parent gates and safe profiles."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import StringIO
import json
import ezdxf
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from final4.test_engineering import TestEngineering, MODE
from final4.api import router
from frozen_plate.repository import WorkflowError
from test_final4 import system
from test_automatic_staging import stager, parent_for


def test_parent(svc, a, spec, *, approve=True, mode="owner_test"):
    r = svc.repo.create_revision(a["plate_id"], spec, expected_current=a["revision_id"],
                                 reason="synthetic test", actor="owner",
                                 source_snapshot={"_payment": {"mode": mode}})
    parent = parent_for(svc, a, r)
    if approve:
        delivery = svc.repo.create_delivery(r["id"])
        svc.repo.approve(delivery["token"], "synthetic-customer")
    return parent

# Helper, not a standalone pytest case.
test_parent.__test__ = False


def test_both_families_idempotent_verified_and_isolated(system):
    svc, a, _, spec = system
    a = test_parent(svc, a, spec)
    engineer = TestEngineering(stager(svc))
    before = svc.repo.revision(a["revision_id"])
    for family in ("HAAS", "PACKAGING"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: engineer.ensure(family, a, actor="owner"), range(2)))
        assert ids[0] == ids[1]
        b = svc.metadata(ids[0])
        assert b["staging"]["mode"] == MODE
        assert not b["statuses"]["release_eligible"]
        assert not b["statuses"]["manufacturing_release_approved"]
        artifacts = {f["name"]: svc.download(b["id"], f["name"]) for f in b["files"]}
        assert all("TEST-ENGINEERING" in name for name, _, _ in artifacts.values())
        if family == "HAAS":
            raw = artifacts["program.NC"][2]
            assert raw.splitlines()[0] == b"%" and raw.splitlines()[1].startswith(b"O")
            assert b"#3000=1" in raw and b"NOT MACHINE-PROVEN / REVIEW REQUIRED" in raw
        else:
            raw = artifacts["packaging.dxf"][2]
            assert b"PROTOTYPE / NOT QUALIFIED FOR SHIPPING" in raw
            doc = ezdxf.read(StringIO(raw.decode("ascii")))
            assert not doc.audit().has_errors
            assert not any(e.dxftype() in ("TEXT", "MTEXT") for e in doc.modelspace())
        again = engineer.ensure(family, a, actor="owner")
        assert svc.metadata(again) == b
        assert {f["name"]: svc.download(again, f["name"]) for f in b["files"]} == artifacts
    assert svc.repo.revision(a["revision_id"]) == before
    assert stager(svc).parents() == []
    for family in ("HAAS", "PACKAGING"):
        with pytest.raises(WorkflowError, match="manufacturing output is prohibited"):
            svc.create(family, a, actor="owner")
        with pytest.raises(WorkflowError):
            stager(svc).ensure(family, a)
    with svc.repo.connect() as db:
        assert db.execute("SELECT count(*) FROM frozen_plate_sourcing").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM manufacturing_bundles").fetchone()[0] == 2


def test_fixture_block_does_not_block_packaging(system):
    svc, a, _, spec = system
    large = replace(spec, finished_od=14.25, finished_bore_diameter=8.5,
                    handle_width=1, centerline_to_handle_end=13.125)
    a = test_parent(svc, a, large)
    engineer = TestEngineering(stager(svc))
    with pytest.raises(ValueError, match="fixture opening clearance"):
        engineer.ensure("HAAS", a, actor="owner")
    b = engineer.ensure("PACKAGING", a, actor="owner")
    assert svc.download(b, "packaging.dxf")[2]
    assert len(svc.list(a)) == 1


@pytest.mark.parametrize("condition", ["live", "unapproved", "superseded", "hash", "identity", "tamper"])
def test_parent_gates(system, condition):
    svc, a, _, spec = system
    a = test_parent(svc, a, spec, approve=condition != "unapproved",
                    mode="live" if condition == "live" else "owner_test")
    engineer = TestEngineering(stager(svc))
    if condition == "superseded":
        test_parent(svc, a, spec)
    if condition == "hash":
        a["spec_sha256"] = "0" * 64
    if condition == "identity":
        a["order_id"] = "other"
    if condition == "tamper":
        with svc.repo.connect() as db:
            row = db.execute("SELECT object_key FROM frozen_plate_artifacts WHERE revision_id=? AND kind='pdf'", (a["revision_id"],)).fetchone()
        path = svc.repo.objects / row["object_key"]
        path.chmod(0o600)
        path.write_bytes(b"tamper")
    for family in ("HAAS", "PACKAGING"):
        with pytest.raises(WorkflowError):
            engineer.ensure(family, a, actor="owner")
    with svc.repo.connect() as db:
        assert db.execute("SELECT count(*) FROM manufacturing_bundles").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM frozen_plate_sourcing").fetchone()[0] == 0


def test_api_authorization_confirmation_and_download_supersession(system):
    svc, a, _, spec = system
    a = test_parent(svc, a, spec)
    engineer = TestEngineering(stager(svc))
    def auth(x_api_key: str = Header(default="")):
        if x_api_key != "synthetic-owner":
            raise HTTPException(403)
    app = FastAPI()
    app.include_router(router(auth, lambda: svc, server_actor="server-owner",
                              get_test_engineering=lambda: engineer))
    client = TestClient(app)
    body = dict(parent=a, family="PACKAGING", confirmed=True)
    assert client.post("/admin/manufacturing/test-engineering", json=body).status_code == 403
    assert client.post("/admin/manufacturing/test-engineering", json=body, headers={"x-api-key":"customer"}).status_code == 403
    client.headers["x-api-key"] = "synthetic-owner"
    assert client.post("/admin/manufacturing/test-engineering", json={**body, "confirmed":False}).status_code == 422
    result = client.post("/admin/manufacturing/test-engineering", json=body)
    assert result.status_code == 200
    b = result.json()
    assert client.post("/admin/manufacturing/test-engineering", json=body).json() == b
    test_parent(svc, a, spec)
    assert client.post("/admin/manufacturing/test-engineering", json=body).status_code == 409
    assert client.get(f"/admin/manufacturing/bundles/{b['id']}/files/packaging.dxf").status_code == 409
    historical = client.get(f"/admin/manufacturing/bundles/{b['id']}/files/packaging.dxf?historical=true")
    assert historical.status_code == 200 and historical.headers["X-Artifact-Verified"] == "true"


def test_owner_ui_explicit_independent_actions_and_states():
    from streamlit.testing.v1 import AppTest
    source = '''
import json
import streamlit as st
from manufacturing_control.derived import show
from owner_portal_transport import PortalError
class Client:
 def json(self,path):
  return dict(staging_profiles={'HAAS':'h','PACKAGING':'p'})
 def manufacturing_post(self,path,body):
  if path.endswith('/query'): return st.session_state.get('bundles',[])
  st.session_state['attempts']=st.session_state.get('attempts',[])+[body['family']]
  if body['family']=='HAAS': raise PortalError('fixture')
  b=dict(id='pack',family='PACKAGING',created_at='now',generator_version='test',state='PROTOTYPE',staging={'mode':'OWNER_TEST_ENGINEERING','profile_sha256':'p'},files=[dict(name='packaging.dxf',filename='TEST-packaging.dxf',size=1,sha256='a'*64)])
  st.session_state['bundles']=[b]
  return b
rev=dict(id='r',number=1,spec_sha256='a'*64,source_sha256='b'*64,source_json=json.dumps({'_payment':{'mode':'owner_test'}}))
plate=dict(id='plate',order_id='order',line_id='line-1')
show(Client(),rev,plate,True,True)
'''
    app = AppTest.from_string(source).run()
    assert not app.exception and 'attempts' not in app.session_state
    assert all(b.disabled for b in app.button)
    assert not any('Automatic staging pending' in i.value for i in app.info)
    app.checkbox[0].check().run()
    next(b for b in app.button if b.label == 'Generate TEST Haas NC').click().run()
    assert not app.exception
    assert any('clearance' in w.value for w in app.warning)
    next(b for b in app.button if b.label == 'Generate TEST Packaging DXF').click().run()
    assert not app.exception
    assert app.session_state['attempts'] == ['HAAS', 'PACKAGING']
    assert any(b.proto.label == 'Download Packaging DXF' for b in app.get('download_button'))

    next(b for b in app.button if b.label == 'Generate TEST Packaging DXF').click().run()
    assert not app.exception  # idempotent generation must not duplicate audit widget keys
    assert len(app.session_state['bundles']) == 1
