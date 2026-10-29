from datetime import datetime, timezone, timedelta
from uuid import uuid4
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from fastapi import FastAPI, HTTPException, Header
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, func, update
from sqlalchemy.pool import StaticPool
from journey.schema import Event, CONSENT_VERSION
from journey.store import Store, sessions, events, daily, links
from journey import runtime
from journey.api import install, budget

NOW = lambda: datetime.now(timezone.utc)


def event(step="quote", outcome="success", category="none", **kw):
    return Event(
        version=1,
        event_id=uuid4(),
        timestamp=NOW(),
        step=step,
        outcome=outcome,
        category=category,
        source="direct",
        **kw
    )


@pytest.fixture
def store():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    return Store(engine, "synthetic-analytics-key")


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JOURNEY_ENABLED", "true")
    monkeypatch.setenv("JOURNEY_DISCLOSURE_VERSION", CONSENT_VERSION)
    monkeypatch.setattr(runtime, "_store", store)
    budget.rows.clear()
    app = FastAPI()

    def owner(x_api_key: str = Header(default="")):
        if x_api_key != "synthetic-owner":
            raise HTTPException(401, "Unauthorized")

    install(app, owner)
    return TestClient(app, raise_server_exceptions=False)


ORIGIN = {"Origin": "https://quote.o-plates.com"}


def start(client, internal=False):
    r = client.post(
        "/journey/session",
        headers=ORIGIN,
        json={"consent_version": CONSENT_VERSION, "internal": internal},
    )
    assert r.status_code == 200, r.text
    return r.json()["session"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "private@example.com"),
        ("inputs", {"bore": 1}),
        ("drawing", "private"),
        ("approval_token", "secret"),
        ("url", "https://private.invalid"),
    ],
)
def test_schema_rejects_sensitive_fields(field, value):
    data = json.loads(event().model_dump_json())
    data[field] = value
    with pytest.raises(ValidationError):
        Event.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"step": "paid_order"},
        {"source": "backend"},
        {"timestamp": NOW() + timedelta(days=1)},
        {"outcome": "success", "category": "api_failure"},
        {"outcome": "error", "category": "none"},
    ],
)
def test_schema_cannot_claim_payment_or_unsafe_combination(change):
    data = event().model_dump()
    data.update(change)
    with pytest.raises(ValidationError):
        Event.model_validate(data)


def test_schema_rejects_naive_and_old_timestamps():
    for value in (datetime.now(), NOW() - timedelta(minutes=6)):
        data = event().model_dump()
        data["timestamp"] = value
        with pytest.raises(ValidationError):
            Event.model_validate(data)


def test_event_idempotency_and_no_client_proof(store):
    token = store.start()
    e = event()
    assert store.add(token, e)
    assert not store.add(token, e)
    store.add(token, event("checkout", "attempted"))
    report = store.report(24)
    assert report["funnel"]["quote"] == 1
    assert report["funnel"]["checkout"] == 1
    assert report["funnel"]["paid_order"] == 0
    assert len(report["sessions"][0]["timeline"]) == 2


def test_internal_promotion_corrects_existing_aggregates(store):
    token = store.start()
    store.add(token, event())
    store.mark_internal(token)
    assert store.report(24)["funnel"]["quote"] == 0
    assert store.report(720)["funnel"]["quote"] == 0
    assert store.report(24, True)["funnel"]["quote"] == 1
    assert store.report(720, True)["funnel"]["quote"] == 1


def test_only_bound_committed_server_observations_complete_funnel(store):
    token = store.start()
    store.add(token, event())
    store.paid("unlinked-order-reference", live=True)
    assert store.report(24)["funnel"]["paid_order"] == 0
    store.bind(token, "synthetic-checkout-session")
    store.paid("synthetic-checkout-session", live=True)
    store.paid("synthetic-checkout-session", live=True)
    report = store.report(24)
    assert report["funnel"]["paid_order"] == 1
    assert report["sessions"][0]["classification"] == "paid"
    with store.engine.connect() as db:
        assert db.scalar(select(links.c.reference)) != "synthetic-checkout-session"
    assert "synthetic-checkout-session" not in json.dumps(report)


def test_test_payment_excluded_from_customer_conversion(store):
    token = store.start()
    store.add(token, event())
    store.bind(token, "test-checkout")
    store.paid("test-checkout", live=False)
    assert store.report(24)["funnel"]["quote"] == 0
    assert store.report(24)["funnel"]["paid_order"] == 0
    assert store.report(24, True)["funnel"]["paid_order"] == 1


def test_restriction_and_resolved_input_are_distinct(store):
    token = store.start()
    store.add(token, event("configuration", "error", "invalid_input"))
    store.add(token, event("configuration", "success"))
    store.add(token, event())
    assert store.report(24)["sessions"][0]["classification"] == "active"
    store.add(token, event("checkout", "blocked", "system_restriction"))
    report = store.report(24)
    assert report["sessions"][0]["classification"] == "system_restriction"
    assert report["sessions"][0]["last_successful_step"] == "quote"
    assert report["errors"][0]["sessions"] == 1


def test_possible_abandonment_is_labeled_as_inference(store):
    token = store.start()
    store.add(token, event(), now=NOW() - timedelta(hours=1))
    assert store.report(24)["sessions"][0]["classification"] == "possible_abandonment"


def test_expired_tampered_and_unknown_session_rejected(store):
    token = store.start(now=NOW() - timedelta(days=2))
    for value in (token, token[:-1] + "z", "anything"):
        with pytest.raises(ValueError):
            store.add(value, event())


def test_session_event_budget_is_bounded(store):
    token = store.start()
    for _ in range(100):
        assert store.add(token, event())
    assert not store.add(token, event())
    assert len(store.report(24)["sessions"][0]["timeline"]) == 100


def test_revoke_deletes_session_diagnostics_and_corrects_totals(store):
    token = store.start()
    store.add(token, event())
    store.bind(token, "synthetic")
    store.revoke(token)
    assert not store.report(24)["sessions"]
    assert store.report(720)["funnel"]["quote"] == 0
    with store.engine.connect() as db:
        for table in (events, links):
            assert db.scalar(select(func.count()).select_from(table)) == 0
    with pytest.raises(ValueError):
        store.add(token, event())


def test_prune_preserves_only_anonymous_daily_totals(store):
    old = NOW() - timedelta(days=8)
    token = store.start(now=old)
    store.add(token, event(), now=old)
    store.prune()
    assert not store.report(2160)["sessions"]
    assert store.report(2160)["funnel"]["quote"] == 1
    with store.engine.connect() as db:
        for table in (sessions, events, links):
            assert db.scalar(select(func.count()).select_from(table)) == 0
    store.prune(now=NOW() + timedelta(days=91))
    assert store.report(2160)["funnel"]["quote"] == 0


@pytest.mark.parametrize("hours", [24, 168, 720, 2160])
def test_owner_only_reporting_and_filters(client, hours):
    assert client.get("/admin/journey", params={"hours": hours}).status_code == 401
    r = client.get(
        "/admin/journey",
        headers={"x-api-key": "synthetic-owner"},
        params={"hours": hours},
    )
    assert r.status_code == 200 and r.json()["window_hours"] == hours
    assert r.headers["cache-control"] == "no-store"


def test_invalid_filter(client):
    assert (
        client.get(
            "/admin/journey?hours=100", headers={"x-api-key": "synthetic-owner"}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "https://evil.invalid",
        "http://quote.o-plates.com",
        "https://quote.o-plates.com.evil.invalid",
    ],
)
def test_unverified_origin_rejected(client, origin):
    headers = {"Origin": origin} if origin else {}
    assert (
        client.post(
            "/journey/session",
            headers=headers,
            json={"consent_version": CONSENT_VERSION},
        ).status_code
        == 403
    )


def test_origin_specific_preflight_and_credential_free_cors(client):
    r = client.options(
        "/journey/event", headers={**ORIGIN, "Access-Control-Request-Method": "POST"}
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == ORIGIN["Origin"]
    assert "access-control-allow-credentials" not in r.headers


def test_consent_version_and_payload_cap(client):
    assert (
        client.post(
            "/journey/session", headers=ORIGIN, json={"consent_version": "old"}
        ).status_code
        == 400
    )
    assert (
        client.post("/journey/event", headers=ORIGIN, content="x" * 2049).status_code
        == 413
    )


def test_disabled_or_unpublished_disclosures_never_create_identifiers(
    client, monkeypatch, store
):
    monkeypatch.setenv("JOURNEY_DISCLOSURE_VERSION", "not-published")
    assert (
        client.post(
            "/journey/session",
            headers=ORIGIN,
            json={"consent_version": CONSENT_VERSION},
        ).status_code
        == 204
    )
    with store.engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(sessions)) == 0


def test_public_ingest_and_session_rate_limit(client):
    token = start(client)
    headers = {**ORIGIN, "X-Journey-Session": token}
    for _ in range(30):
        assert (
            client.post(
                "/journey/event", headers=headers, content=event().model_dump_json()
            ).status_code
            == 204
        )
    assert (
        client.post(
            "/journey/event", headers=headers, content=event().model_dump_json()
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/journey/event",
            headers={**ORIGIN, "X-Journey-Session": "forged"},
            content=event().model_dump_json(),
        ).status_code
        == 410
    )


def test_withdrawal_endpoint_and_immutable_internal_exclusion(client, store):
    token = start(client)
    headers = {**ORIGIN, "X-Journey-Session": token}
    assert (
        client.post(
            "/journey/event", headers=headers, content=event().model_dump_json()
        ).status_code
        == 204
    )
    assert client.post("/journey/internal", headers=headers, json={}).status_code == 204
    assert store.report(24)["funnel"]["quote"] == 0
    assert client.delete("/journey/session", headers=headers).status_code == 204
    assert not store.report(24, True)["sessions"]


def test_storage_outage_does_not_expose_details(client, monkeypatch):
    def fail():
        raise RuntimeError("private database password")

    monkeypatch.setattr(runtime, "get_store", fail)
    r = client.post(
        "/journey/session", headers=ORIGIN, json={"consent_version": CONSENT_VERSION}
    )
    assert r.status_code == 503 and "private" not in r.text


def test_disabled_server_observer_does_no_work(monkeypatch):
    monkeypatch.delenv("JOURNEY_ENABLED", raising=False)
    size = runtime._queue.qsize()
    runtime.submit("paid", "sensitive-reference", live=True)
    assert runtime._queue.qsize() == size


def test_flooded_sidecar_does_not_block_quoting(monkeypatch):
    import queue

    monkeypatch.setenv("JOURNEY_ENABLED", "true")
    monkeypatch.setenv("JOURNEY_DISCLOSURE_VERSION", CONSENT_VERSION)
    q = queue.Queue(maxsize=1)
    q.put("full")
    monkeypatch.setattr(runtime, "_queue", q)
    runtime.submit("paid", "synthetic", live=True)
    assert runtime.coverage()["queue_drops_or_storage_failures"] >= 1


def test_production_static_collection_off_and_identical_client():
    root = Path(__file__).resolve().parents[1]
    assert (root / "journey/frontend/journey.js").read_bytes() == (
        root / "o-plates landing/journey.js"
    ).read_bytes()
    assert "enabled:false" in (root / "o-plates landing/journey-config.js").read_text()
    assert (
        "Optional customer journey diagnostics"
        in (root / "o-plates landing/privacy.html").read_text()
    )


def test_browser_consent_and_origin_protocol():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "tests/journey_browser.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_owner_workspace_filters_and_lock(monkeypatch, store):
    from test_command_center import unlocked
    from manufacturing_control.client import OwnerClient

    app, calls, _ = unlocked(monkeypatch)
    original = OwnerClient.json

    def read(self, path, **kwargs):
        if path == "/admin/journey":
            calls.append(path)
            params = kwargs["params"]
            return {
                "enabled": True,
                **store.report(params["hours"], params["internal"] == "true"),
                "coverage": {"queue_drops_or_storage_failures": 0},
            }
        return original(self, path, **kwargs)

    monkeypatch.setattr(OwnerClient, "json", read)
    next(r for r in app.radio if r.label == "Workspace").set_value(
        "Customer Journey"
    ).run()
    assert not app.exception
    selector = next(s for s in app.selectbox if s.label == "Date range")
    assert selector.options == ["24 hours", "7 days", "30 days", "90 days"]
    for value in selector.options:
        next(s for s in app.selectbox if s.label == "Date range").set_value(value).run()
        assert not app.exception
    next(b for b in app.button if b.label == "Lock").click().run()
    assert "mc_key" not in app.session_state
    assert not any(s.label == "Date range" for s in app.selectbox)


def test_retention_remains_available_when_collection_disabled(monkeypatch, store):
    monkeypatch.setenv("JOURNEY_ENABLED", "false")
    monkeypatch.setenv("JOURNEY_STORAGE_ENABLED", "true")
    monkeypatch.setattr(runtime, "_store", store)
    assert runtime.get_store() is store
    assert not runtime.enabled()


def test_withdrawal_still_deletes_when_collection_is_paused(client, monkeypatch, store):
    token = start(client, internal=True)
    store.add(token, event())
    monkeypatch.setenv("JOURNEY_ENABLED", "false")
    monkeypatch.setenv("JOURNEY_STORAGE_ENABLED", "true")
    assert client.delete(
        "/journey/session", headers={**ORIGIN, "X-Journey-Session": token}
    ).status_code == 204
    assert not store.report(24, True)["sessions"]
    assert store.report(720, True)["funnel"]["quote"] == 0


def test_production_never_falls_back_to_business_credentials(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JOURNEY_STORAGE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://business-owner.invalid/business")
    monkeypatch.setenv("JOURNEY_SIGNING_KEY", "synthetic-only")
    monkeypatch.delenv("JOURNEY_DATABASE_URL", raising=False)
    monkeypatch.setattr(runtime, "_store", None)
    assert runtime.get_store() is None
    monkeypatch.setenv("JOURNEY_DATABASE_URL", "sqlite:///temporary.db")
    assert runtime.get_store() is None


def test_production_pool_is_bounded_and_runtime_cannot_create_tables(monkeypatch):
    import journey.store

    options = {}
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JOURNEY_STORAGE_ENABLED", "true")
    monkeypatch.setenv("JOURNEY_SIGNING_KEY", "synthetic-only")
    monkeypatch.setenv("JOURNEY_DATABASE_URL", "postgresql://journey-role.invalid/analytics")
    monkeypatch.setattr(runtime, "_store", None)

    def engine(url, **kwargs):
        options.update(kwargs)
        return "synthetic-engine"

    def store(engine, secret, **kwargs):
        options.update(kwargs)
        return "synthetic-store"

    monkeypatch.setattr(runtime, "create_engine", engine)
    monkeypatch.setattr(journey.store, "Store", store)
    assert runtime.get_store() == "synthetic-store"
    assert options["pool_size"] == 2 and options["max_overflow"] == 0
    assert options["initialize"] is False and options["internal"] is False


def test_session_expiration_removes_late_children_without_erasing_daily_counts(store):
    old = NOW() - timedelta(days=8)
    token = store.start(now=old)
    store.add(token, event(), now=old)
    with store.engine.begin() as db:
        db.execute(update(events).values(received=NOW()))
    assert not store.report(24)["sessions"]
    store.prune()
    with store.engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(events)) == 0
    assert store.report(2160)["funnel"]["quote"] == 1


def test_browser_ack_retry_and_privacy_cancellation():
    import subprocess

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "tests/journey_retry_browser.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
