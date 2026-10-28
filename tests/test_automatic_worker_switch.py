"""Worker-only containment: no providers, credentials, DB or artifact mutations."""

import pytest
import final4.worker as worker
from final4.runtime import enabled


def test_disabled_worker_does_not_construct_service_or_read_artifacts(monkeypatch):
    monkeypatch.setenv("FINAL4_ENABLED", "true")
    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "false")
    calls = []
    w = worker.StagingWorker(lambda: calls.append(True))
    worker.wake_event.clear()
    w.start()
    worker.request_scan()
    assert w.thread is None and not worker.wake_event.is_set()
    assert w.sweep() == {} and calls == []
    assert w.status("synthetic")["HAAS"]["state"] == "AUTOMATIC STAGING DISABLED"
    assert enabled() is True  # Manual routes' existing enable gate is unchanged.


@pytest.mark.parametrize("value", [None, "true", "false", "TRUE", ""])
def test_default_and_deliberate_enable_are_explicit(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("FINAL4_AUTOMATIC_STAGING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", value)
    assert worker.automatic_enabled() is (value is None or value == "true")
