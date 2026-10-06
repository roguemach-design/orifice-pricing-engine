from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import BadSignature
import pytest
import requests

from frozen_plate import api
from frozen_plate.delivery import (
    deliver_completed_order,
    send_confirmation,
    delivery_status,
)
from frozen_plate.production import ProductionRepository, ProductionStorage
from frozen_plate.repository import Repository, WorkflowError, digest
from frozen_plate.runtime import enabled, ui_enabled, PRODUCTION_API, PRODUCTION_UI
from frozen_plate.staging import StagingRepository
from prototype_manufacturing import sample_spec


def production_env():
    # Synthetic credentials only; these cannot connect to a live service.
    return {
        "APP_ENV": "production",
        "FROZEN_PLATE_ENABLED": "true",
        "RENDER_SERVICE_ID": "srv-d51l6ch5pdvs73ealnh0",
        "FROZEN_PLATE_DATABASE_URL": "postgresql://frozen_plate_production_api.kboaovlhilonlymcuqcr:synthetic@aws-0-us-west-2.pooler.supabase.com:5432/postgres?sslmode=require",
        "FROZEN_PLATE_SIGNING_KEY": "synthetic-signing-key" * 5,
        "FROZEN_PLATE_EMAIL_MODE": "send",
        "SENDGRID_API_KEY": "synthetic-provider-key",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("APP_ENV", "staging"),
        ("FROZEN_PLATE_ENABLED", "false"),
        ("RENDER_SERVICE_ID", "srv-d9ritcijobas73didpbg"),
        (
            "FROZEN_PLATE_DATABASE_URL",
            "postgresql://postgres:synthetic@db.kboaovlhilonlymcuqcr.supabase.co:5432/postgres?sslmode=require",
        ),
        (
            "FROZEN_PLATE_DATABASE_URL",
            "postgresql://frozen_plate_staging_api.ixhnanttetuhpzvrnvdc:synthetic@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require",
        ),
        (
            "FROZEN_PLATE_DATABASE_URL",
            "postgresql://frozen_plate_production_api.kboaovlhilonlymcuqcr:synthetic@aws-0-us-west-2.pooler.supabase.com:5432/postgres?sslmode=disable",
        ),
        ("FROZEN_PLATE_SIGNING_KEY", "short"),
    ],
)
def test_production_rejects_cross_environment_or_privileged_bindings(field, value):
    env = production_env()
    env[field] = value
    with pytest.raises(ValueError):
        ProductionRepository(env, storage=Mock())


def test_staging_guard_unchanged_and_signatures_isolated(tmp_path):
    env = production_env()
    production = ProductionRepository(env, storage=Mock())
    with pytest.raises(ValueError):
        StagingRepository(env)
    local = Repository(tmp_path, env["FROZEN_PLATE_SIGNING_KEY"])
    with pytest.raises(BadSignature):
        local.signer.loads(production.signer.dumps({"nonce": "synthetic"}))


@pytest.mark.parametrize(
    "url,key,bucket",
    [
        (
            "https://ixhnanttetuhpzvrnvdc.supabase.co",
            "sb_secret_synthetic",
            "frozen-plate-production",
        ),
        (
            "https://kboaovlhilonlymcuqcr.supabase.co",
            "legacy-synthetic",
            "frozen-plate-production",
        ),
        (
            "https://kboaovlhilonlymcuqcr.supabase.co",
            "sb_secret_synthetic",
            "frozen-plate-staging",
        ),
    ],
)
def test_production_storage_requires_modern_private_production_binding(
    url, key, bucket
):
    with pytest.raises(ValueError):
        ProductionStorage(url, key, bucket)


def test_production_activation_is_explicit_and_ui_keeps_known_origins():
    env = production_env()
    assert enabled(env)
    assert not enabled({**env, "FROZEN_PLATE_ENABLED": "false"})
    assert not enabled({**env, "FROZEN_PLATE_DATABASE_URL": ""})
    assert ui_enabled({**env, "API_BASE": PRODUCTION_API})
    assert not ui_enabled({**env, "API_BASE": "https://attacker.example.test"})
    assert not ui_enabled({"API_BASE": PRODUCTION_API})
    assert not ui_enabled(
        {**env, "API_BASE": "https://oplates-pricing-api-staging.onrender.com"}
    )


def test_production_landing_passive_requests_never_approve(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        api, "repository", lambda: pytest.fail("passive landing consulted repository")
    )
    app = FastAPI()
    app.include_router(api.router(lambda: "owner", lambda: None, lambda _: None))
    client = TestClient(app)
    for method in ("get", "head"):
        response = getattr(client, method)("/approve/synthetic-token")
        assert response.status_code == 200
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "<script" not in response.text and 'method="post"' not in response.text
    assert (
        PRODUCTION_UI + "/Drawing_Approval?token=synthetic-token"
        in client.get("/approve/synthetic-token").text
    )


@pytest.fixture
def delivery_case(tmp_path):
    class Storage:
        def __init__(self):
            self.objects = {}

        def get(self, key):
            if key not in self.objects:
                raise WorkflowError("missing private object")
            return self.objects[key]

        def put(self, key, value):
            if key in self.objects:
                raise WorkflowError("immutable object exists")
            self.objects[key] = value

    class SyntheticProductionRepository(ProductionRepository):
        connect = Repository.connect
        transaction = Repository.transaction

        def __init__(self):
            Repository.__init__(self, tmp_path, "synthetic-signing-key" * 5)

    repo = SyntheticProductionRepository()
    repo.delivery_origin = PRODUCTION_API
    repo.storage = Storage()
    plate = repo.create_plate(
        order_id="order1",
        line_id="line-1",
        configuration_id="config1",
        customer_id="owner",
        actor="test",
    )
    revision = repo.create_revision(
        plate,
        replace(sample_spec(), part_identifier="PRD-TEST"),
        expected_current=None,
        reason="synthetic",
        actor="test",
        source_snapshot={"synthetic": True},
    )
    delivery = repo.create_delivery(revision["id"], base_url=PRODUCTION_API)
    snapshot = {
        "id": "order1",
        "customer_id": "owner",
        "customer_email": "owner@example.test",
    }
    return repo, snapshot, revision, delivery, production_env()


def test_exact_pdf_send_once_replay_and_concurrency(delivery_case):
    repo, snapshot, revision, delivery, env = delivery_case
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=202)

    def run(_):
        return send_confirmation(repo, snapshot, revision["id"], environ=env, post=post)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run, range(3)))
    assert len(calls) == 1
    assert all(r["state"] == "PROVIDER_ACCEPTED" for r in results)
    import base64

    payload = calls[0]["json"]
    assert payload["personalizations"] == [{"to": [{"email": "owner@example.test"}]}]
    assert len(payload["attachments"]) == 1
    assert (
        digest(base64.b64decode(payload["attachments"][0]["content"]))
        == revision["artifacts"]["pdf"]["sha256"]
    )
    assert payload["tracking_settings"]["click_tracking"]["enable"] is False
    assert "STAGING" not in payload["subject"]
    assert delivery_status(repo, revision["id"])["state"] == "PROVIDER_ACCEPTED"


@pytest.mark.parametrize("outcome", ["timeout", "reject", "accepted_journal_failure"])
def test_unknown_provider_outcome_never_blindly_retries(delivery_case, outcome):
    repo, snapshot, revision, delivery, env = delivery_case
    calls = []
    original_put = repo.storage.put

    def put(key, value):
        if key.endswith("accepted.json") and outcome == "accepted_journal_failure":
            raise WorkflowError("private storage unavailable")
        original_put(key, value)

    repo.storage.put = put

    def post(*a, **k):
        calls.append(True)
        if outcome == "timeout":
            raise requests.Timeout("sensitive request details")
        return SimpleNamespace(status_code=401 if outcome == "reject" else 202)

    for _ in range(2):
        assert (
            send_confirmation(repo, snapshot, revision["id"], environ=env, post=post)[
                "state"
            ]
            == "RECONCILIATION_REQUIRED"
        )
    assert len(calls) == 1
    assert delivery_status(repo, revision["id"])["state"] == "RECONCILIATION_REQUIRED"


@pytest.mark.parametrize(
    "defect",
    [
        "capture_tamper",
        "different_owner",
        "different_order",
        "superseded",
        "staging",
        "capture_mode",
    ],
)
def test_no_send_when_binding_or_environment_invalid(delivery_case, defect):
    repo, snapshot, revision, delivery, env = delivery_case
    if defect == "capture_tamper":
        repo.storage.objects["confirmation/" + delivery["id"] + ".eml"] += b"tamper"
    elif defect == "different_owner":
        snapshot["customer_id"] = "other"
    elif defect == "different_order":
        snapshot["id"] = "other"
    elif defect == "staging":
        env["APP_ENV"] = "staging"
    elif defect == "capture_mode":
        env["FROZEN_PLATE_EMAIL_MODE"] = "capture"
    elif defect == "superseded":
        repo.create_revision(
            revision["plate_id"],
            replace(sample_spec(), part_identifier="PRD-TEST"),
            expected_current=revision["id"],
            reason="R2",
            actor="test",
            source_snapshot={"synthetic": True},
        )
    with pytest.raises(WorkflowError):
        send_confirmation(
            repo,
            snapshot,
            revision["id"],
            environ=env,
            post=lambda *a, **k: pytest.fail("invalid confirmation sent"),
        )


def test_partially_held_order_sends_no_partial_confirmation(delivery_case):
    repo, snapshot, revision, delivery, env = delivery_case
    assert deliver_completed_order(
        repo,
        snapshot,
        [{"state": "FROZEN", "revision_id": revision["id"]}, {"state": "HOLD"}],
    ) == [{"state": "HOLD"}]
    assert not any(k.startswith("email-delivery/") for k in repo.storage.objects)


def test_journal_read_failure_is_not_mistaken_for_no_send(delivery_case):
    repo, snapshot, revision, delivery, env = delivery_case

    def unavailable(key):
        raise WorkflowError("private storage unavailable")

    repo.storage.get_optional = unavailable
    with pytest.raises(WorkflowError):
        send_confirmation(
            repo,
            snapshot,
            revision["id"],
            environ=env,
            post=lambda *a, **k: pytest.fail(
                "provider called without journal visibility"
            ),
        )
    with pytest.raises(WorkflowError):
        delivery_status(repo, revision["id"])
