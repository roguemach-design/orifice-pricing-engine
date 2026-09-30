from dataclasses import replace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from frozen_plate import api
from frozen_plate.repository import Repository, WorkflowError
from frozen_plate.staging import (
    PrivateStorage,
    StagingRepository,
    Connection,
    API_ORIGIN,
)
from prototype_manufacturing import sample_spec


def test_storage_rejects_paths_and_hides_error_bodies(monkeypatch):
    monkeypatch.setattr("frozen_plate.staging.httpx.Client", Mock())
    store = PrivateStorage(
        "https://ixhnanttetuhpzvrnvdc.supabase.co",
        "server-secret",
        "frozen-plate-staging",
    )
    for path in ("../secret", "/absolute", "a/../b"):
        with pytest.raises(WorkflowError):
            store.get(path)
    store.client = Mock()
    store.client.request.return_value.is_success = False
    store.client.request.return_value.text = "server-secret"
    with pytest.raises(WorkflowError, match="^private storage operation failed$"):
        store.get("plate/revision/file.pdf")


def test_production_configuration_rejected_before_connecting():
    with pytest.raises(ValueError, match="dedicated staging"):
        StagingRepository({"APP_ENV": "production"})


def test_sql_adapter_keeps_sourcing_idempotent():
    raw = Mock()
    Connection(raw).execute(
        "INSERT OR IGNORE INTO frozen_plate_sourcing VALUES (?)", ("x",)
    )
    sql, args = raw.cursor.return_value.execute.call_args.args
    assert "ON CONFLICT (revision_id,route) DO NOTHING" in sql
    assert args == ("x",)


def test_authenticated_api_no_scanner_approval_or_customer_dxf(tmp_path, monkeypatch):
    repo = Repository(tmp_path, "local-test-key" * 6)
    pid = repo.create_plate(
        order_id="order1",
        line_id="line-1",
        configuration_id="config1",
        customer_id="customer1",
        actor="admin",
    )
    spec = replace(sample_spec(), part_identifier="PHASE5-TEST")
    rev = repo.create_revision(
        pid,
        spec,
        expected_current=None,
        reason="test",
        actor="admin",
        source_snapshot={"test": True},
    )
    delivery = repo.create_delivery(rev["id"])
    monkeypatch.setattr(api, "repository", lambda: repo)

    def customer():
        return "customer1"

    def admin():
        raise HTTPException(401)

    app = FastAPI()
    app.include_router(api.router(customer, admin, lambda _: None))
    client = TestClient(app)
    payload = {"token": delivery["token"]}
    for method in ("get", "head"):
        assert getattr(client, method)("/me/frozen-plates/approve").status_code == 405
    assert repo.plate(pid)["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION"
    assert client.post("/me/frozen-plates/pdf", json=payload).content.startswith(
        b"%PDF"
    )
    assert (
        client.get("/admin/frozen-plates/revisions/" + rev["id"] + "/dxf").status_code
        == 401
    )
    approved = client.post("/me/frozen-plates/approve", json=payload)
    assert approved.status_code == 200
    assert "YOUR ORDER IS IN PRODUCTION" in approved.json()["success_html"]
    for route in ("SENDCUTSEND", "ALRO", "ROGUE_INTERNAL"):
        assert repo.select_source(rev["id"], route, actor="admin")["released"] is False
    r2 = repo.create_revision(
        pid,
        spec,
        expected_current=rev["id"],
        reason="R2",
        actor="admin",
        source_snapshot={"test": True},
    )
    assert r2["number"] == 2
    assert repo.inspect_token(delivery["token"], "customer1")["historical"] is True
    with pytest.raises(WorkflowError):
        repo.select_source(rev["id"], "ALRO", actor="admin")
    app.dependency_overrides[customer] = lambda: "different-customer"
    assert client.post("/me/frozen-plates/pdf", json=payload).status_code == 409


def test_staging_signatures_cannot_use_local_tokens(tmp_path):
    env = {
        "APP_ENV": "staging",
        "FROZEN_PLATE_DATABASE_URL": "postgresql://frozen_plate_staging_api.ixhnanttetuhpzvrnvdc:unused@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require",
        "FROZEN_PLATE_SIGNING_KEY": "test-key" * 12,
    }
    repo = StagingRepository(env, storage=Mock())
    local = Repository(tmp_path, "test-key" * 12)
    token = repo.signer.dumps({"nonce": "test"})
    assert repo.signer.loads(token) == {"nonce": "test"}
    from itsdangerous import BadSignature

    with pytest.raises(BadSignature):
        local.signer.loads(token)
