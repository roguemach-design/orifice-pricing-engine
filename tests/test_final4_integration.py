from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from final4.postgres import migration, verify_repository
from frozen_plate.repository import Repository, WorkflowError
from owner_portal_transport import OwnerClient, PortalError, DownloadAccess


def test_runtime_refuses_sqlite(tmp_path):
    with pytest.raises(WorkflowError, match="no SQLite fallback"):
        verify_repository(Repository(tmp_path, "synthetic-" * 10))


def test_deferred_derived_exact_bytes_and_lock(monkeypatch):
    data = b"exact stored prototype bytes"
    artifact = dict(
        name="packaging.dxf",
        filename="OP-PACKAGING-PROTOTYPE-fixture.dxf",
        size=len(data),
        sha256=sha256(data).hexdigest(),
    )
    response = SimpleNamespace(
        status_code=200,
        content=data,
        headers={
            "X-Artifact-SHA256": artifact["sha256"],
            "Content-Disposition": f'attachment; filename="{artifact["filename"]}"',
        },
    )
    request = Mock(return_value=response)
    monkeypatch.setattr("requests.get", request)
    client = OwnerClient("https://api.example.test", "owner")
    access = DownloadAccess(client)
    assert not request.called
    assert access.load_derived("bundle", artifact) == data
    response.content = b"tampered"
    with pytest.raises(RuntimeError, match="integrity"):
        access.load_derived("bundle", artifact)
    access.revoke()
    request.reset_mock()
    with pytest.raises(RuntimeError, match="locked"):
        access.load_derived("bundle", artifact)
    assert not request.called


def test_generation_post_is_explicit_scoped_no_redirect(monkeypatch):
    request = Mock(
        return_value=SimpleNamespace(status_code=200, json=lambda: {"id": "new"})
    )
    monkeypatch.setattr("requests.post", request)
    client = OwnerClient("https://api.example.test", "owner")
    for path in ("/admin/config", "/admin/manufacturing/release", "https://evil.test"):
        with pytest.raises(PortalError):
            client.manufacturing_post(path, {})
    assert not request.called
    assert client.manufacturing_post(
        "/admin/manufacturing/bundles", {"family": "PACKAGING"}
    ) == {"id": "new"}
    assert request.call_args.kwargs["allow_redirects"] is False


def test_download_only_view_has_no_generation_inputs_or_mutations(monkeypatch):
    from streamlit.testing.v1 import AppTest

    source = """
import streamlit as st
from manufacturing_control.derived import show
class Client:
 def json(self,path):
  return dict(packaging_configuration={'board_reference':'SYNTHETIC'},machine_profile={},machining_parameters={})
 def manufacturing_post(self,path,body):
  if path.endswith('/query'): return []
  st.session_state['generated']=body
  return {'id':'bundle'}
rev={'id':'r','number':1,'spec_sha256':'a'*64,'source_sha256':'b'*64,'spec_json':'{"part_identifier":"P","finished_bore_diameter":1.548,"bore_tolerance":0.001,"thickness":0.125,"material":"304 Stainless Steel","chamfer":false}'}
plate={'id':'p','order_id':'o','line_id':'line-1'}
show(Client(),rev,plate,True,True)
"""
    at = AppTest.from_string(source).run()
    assert not at.exception
    assert "generated" not in at.session_state
    assert all(b.disabled for b in at.button) and not at.checkbox
    assert not at.number_input and not at.text_input and not at.selectbox
    assert any(e.label == "Engineering details / audit files" for e in at.expander)
