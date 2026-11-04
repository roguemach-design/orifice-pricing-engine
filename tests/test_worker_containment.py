"""Default-off containment using synthetic services and temporary SQLite only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest

from final4 import runtime
from final4 import worker as module
from final4.api import router as derived_router
from frozen_plate import api as frozen_api
from frozen_plate.api import router as frozen_router
from test_automatic_staging import stager
from test_final4 import system
from test_owner_test_engineering import test_parent


@pytest.fixture(autouse=True)
def isolated_switch_and_wake(monkeypatch):
    monkeypatch.delenv("FINAL4_AUTOMATIC_STAGING_ENABLED", raising=False)
    monkeypatch.setattr(module, "wake_event", Event())


@pytest.mark.parametrize("value", [None, "false", "true", "TRUE", "1", "", " true "])
def test_only_literal_true_enables_automatic_execution(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", value)
    monkeypatch.setenv("FINAL4_ENABLED", "true")
    assert module.automatic_enabled() is (value == "true")
    assert runtime.enabled() is True  # Independent manual route gate.


@pytest.mark.parametrize("value", [None, "false"])
def test_disabled_lifespan_restart_and_direct_calls_never_construct_service(
    monkeypatch, value
):
    if value is not None:
        monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", value)
    factory = Mock(side_effect=AssertionError("disabled worker reached provider"))
    thread = Mock(side_effect=AssertionError("disabled worker constructed thread"))
    monkeypatch.setattr(module, "Thread", thread)
    for _ in range(2):  # Fresh process-equivalent runner after restart.
        runner = module.StagingWorker(factory)
        app = FastAPI(lifespan=module.lifespan)
        app.state.manufacturing_stager = runner
        with TestClient(app):
            module.request_scan()
            assert not module.wake_event.is_set()
            assert runner.sweep() == {}
            runner.run()  # Direct run is also inert, without sleeping.
            assert runner.thread is None
            assert runner.status("synthetic")["HAAS"]["state"] == "AUTOMATIC STAGING DISABLED"
        assert runner.thread is None
        module.wake_event.clear()  # Shutdown wake is not an approval notification.
    factory.assert_not_called()
    thread.assert_not_called()


@pytest.mark.parametrize("notification", ["wake", "direct_sweep"])
def test_actual_customer_approval_cannot_bypass_disabled_worker(
    system, monkeypatch, notification
):
    svc, parent, _, spec = system
    parent = test_parent(svc, parent, spec, approve=False)
    token = svc.repo.create_delivery(parent["revision_id"])["token"]
    factory = Mock(side_effect=AssertionError("approval reached automatic provider"))
    runner = module.StagingWorker(factory)
    callback = module.request_scan if notification == "wake" else runner.sweep
    monkeypatch.setattr(frozen_api, "repository", lambda: svc.repo)
    app = FastAPI()
    app.include_router(frozen_router(
        lambda: "synthetic-customer", lambda: None, lambda _: None,
        approval_committed=callback,
    ))
    response = TestClient(app).post("/me/frozen-plates/approve", json={"token": token})
    assert response.status_code == 200 and response.json()["state"] == "approved"
    assert not module.wake_event.is_set()
    factory.assert_not_called()
    assert not svc.list(parent)


def test_enabled_start_is_single_and_shutdown_wakes_waiter(monkeypatch):
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "true")
    entered, release = Event(), Event()
    def factory():
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(parents=lambda: [])
    runner = module.StagingWorker(factory, interval=600)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: runner.start(), range(16)))
        assert entered.wait(5)
        original = runner.thread
        assert original.is_alive()
        runner.start()
        assert runner.thread is original
        release.set()
        runner.stop()
        assert not original.is_alive()
    finally:
        release.set()
        runner.stop()


def test_stop_prevents_next_family_and_unattended_retry(monkeypatch):
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "true")
    entered, release = Event(), Event()
    calls = []
    runner = None
    def ensure(family, parent):
        calls.append(family)
        entered.set()
        assert release.wait(5)
        raise ValueError("synthetic blocked profile")
    fake = SimpleNamespace(parents=lambda: [{"revision_id": "synthetic"}], ensure=ensure)
    runner = module.StagingWorker(lambda: fake, interval=600)
    try:
        runner.start()
        assert entered.wait(5)
        # A synchronous provider call cannot be cancelled. Mark shutdown before
        # releasing it; no second family or later sweep may execute.
        runner.stop_event.set()
        module.wake_event.set()
        release.set()
        runner.stop()
        assert not runner.thread.is_alive()
        assert calls == ["HAAS"]
        assert runner.sweep() == {}
    finally:
        release.set()
        runner.stop()


def test_cached_runner_can_restart_without_reusing_stopped_event(monkeypatch):
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "true")
    entered = Event()
    factory = Mock(side_effect=lambda: entered.set() or SimpleNamespace(parents=lambda: []))
    runner = module.StagingWorker(factory, interval=600)
    for _ in range(2):
        entered.clear()
        try:
            runner.start()
            assert entered.wait(5)
        finally:
            runner.stop()
        assert not runner.thread.is_alive()
    assert factory.call_count == 2
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "false")
    runner.start()
    assert not runner.thread.is_alive() and factory.call_count == 2


def test_timed_out_stop_keeps_live_handle_and_cannot_spawn_duplicate(monkeypatch):
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "true")
    entered, release = Event(), Event()
    def factory():
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(parents=lambda: [])
    runner = module.StagingWorker(factory, interval=600)
    try:
        runner.start()
        assert entered.wait(5)
        original = runner.thread
        runner.stop()  # The bounded join times out on this synthetic blocked I/O.
        assert original.is_alive() and runner.stop_event.is_set()
        runner.start()
        assert runner.thread is original and runner.stop_event.is_set()
    finally:
        release.set()
        runner.stop()
    assert not runner.thread.is_alive()


def test_disable_between_families_stops_work_and_hides_stale_status(monkeypatch):
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "true")
    def ensure(family, parent):
        monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "false")
        return "synthetic-bundle"
    fake = SimpleNamespace(parents=lambda: [{"revision_id": "synthetic"}], ensure=Mock(side_effect=ensure))
    runner = module.StagingWorker(lambda: fake)
    runner.sweep()
    assert fake.ensure.call_count == 1
    assert runner.status("synthetic")["HAAS"]["state"] == "AUTOMATIC STAGING DISABLED"
    module.request_scan()
    assert not module.wake_event.is_set()


@pytest.mark.parametrize("value", [None, "false"])
def test_owner_test_api_generates_both_families_while_worker_disabled(
    system, monkeypatch, value
):
    if value is not None:
        monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", value)
    monkeypatch.setenv("FINAL4_ENABLED", "true")
    svc, parent, _, spec = system
    parent = test_parent(svc, parent, spec)
    auto = stager(svc)
    monkeypatch.setattr(runtime, "automatic", lambda: auto)
    def protected_rows():
        with svc.repo.connect() as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'frozen_%'")]
            return {name: [tuple(r) for r in db.execute('SELECT * FROM "' + name + '" ORDER BY rowid')] for name in tables}
    before = protected_rows()
    def owner(x_api_key: str = Header(default="")):
        if x_api_key != "synthetic-owner":
            raise HTTPException(403)
    app = FastAPI(lifespan=module.lifespan)
    app.state.manufacturing_stager = module.StagingWorker(Mock(side_effect=AssertionError("automatic provider reached")))
    app.include_router(derived_router(owner, lambda: svc, server_actor="synthetic-owner", get_test_engineering=runtime.test_engineering))
    with TestClient(app) as client:
        for family in ("HAAS", "PACKAGING"):
            body = dict(parent=parent, family=family, confirmed=True)
            assert client.post("/admin/manufacturing/test-engineering", json=body).status_code == 403
            response = client.post("/admin/manufacturing/test-engineering", json=body, headers={"x-api-key": "synthetic-owner"})
            assert response.status_code == 200
            assert response.json()["staging"]["mode"] == "OWNER_TEST_ENGINEERING"
            assert not response.json()["statuses"]["release_eligible"]
        assert app.state.manufacturing_stager.thread is None
    assert protected_rows() == before
    assert runtime.enabled() is True


def test_configuration_reports_switch_without_changing_manual_gate(system, monkeypatch):
    svc, _, _, _ = system
    monkeypatch.setattr(runtime, "service", lambda: svc)
    monkeypatch.setattr(runtime, "automatic", lambda: stager(svc))
    monkeypatch.setattr(runtime, "verify_repository", lambda repo: "synthetic-private-schema")
    assert runtime.configuration()["automatic_staging"] is False
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "true")
    assert runtime.configuration()["automatic_staging"] is True
