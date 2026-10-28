"""Offline retry, transport and containment regressions; no provider credentials."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import threading
import time
from types import SimpleNamespace
import pytest
import psycopg2
from frozen_plate.repository import WorkflowError
from frozen_plate.transport import (
    VerifiedArtifactCache,
    RepositoryPool,
    ProviderUnavailable,
)
from final4.retry import RetryLedger, ProfileBlocked, CIRCUIT_KEY, job_key, delay
from final4.worker import StagingWorker
from final4.postgres import retry_migration
from test_final4 import system


class FakeStager:
    def __init__(self, svc, parent):
        self.service = svc
        self.parent = dict(parent)
        self.signatures = {"HAAS": "h1", "PACKAGING": "p1"}
        self.calls = []
        self.errors = {}

    def profiles(self):
        return dict(self.signatures)

    def parents(self):
        return [dict(self.parent)]

    def ensure(self, family, parent):
        self.calls.append(family)
        if family in self.errors:
            raise self.errors[family]
        return "synthetic-bundle-" + family


@pytest.fixture
def policy(system):
    svc, parent, _, _ = system
    now = [1000.0]
    svc.repo.clock = lambda: now[0]
    return FakeStager(svc, parent), now


def test_disabled_switch_prevents_start_factory_reads_and_wake(monkeypatch):
    import final4.worker as module

    monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", "false")
    called = []
    worker = StagingWorker(lambda: called.append(True))
    module.wake_event.clear()
    worker.start()
    module.request_scan()
    assert worker.thread is None and not module.wake_event.is_set()
    assert worker.sweep() == {} and called == []
    assert worker.status("revision")["HAAS"]["state"] == "AUTOMATIC STAGING DISABLED"


@pytest.mark.parametrize("value", [None, "true", "false", "TRUE", ""])
def test_switch_default_preserves_existing_behavior(monkeypatch, value):
    from final4.worker import automatic_enabled

    if value is None:
        monkeypatch.delenv("FINAL4_AUTOMATIC_STAGING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("FINAL4_AUTOMATIC_STAGING_ENABLED", value)
    assert automatic_enabled() is (value is None or value == "true")


def test_permanent_failure_survives_sweeps_and_process_restart(policy, caplog):
    auto, now = policy
    auto.errors["HAAS"] = ProfileBlocked("sensitive exception text")
    w = StagingWorker(lambda: auto)
    w.sweep()
    w.sweep()
    StagingWorker(lambda: auto).sweep()
    assert auto.calls.count("HAAS") == 1 and auto.calls.count("PACKAGING") == 3
    key = job_key("HAAS", auto.parent, auto.signatures["HAAS"])
    row = RetryLedger(auto.service.repo).get(key)
    assert row["state"] == "PERMANENT"
    assert "sensitive" not in json.dumps(row) and "sensitive" not in caplog.text
    assert caplog.text.count("profile rejection recorded") == 1


@pytest.mark.parametrize("change", ["revision", "profile", "spec", "source"])
def test_only_changed_revision_or_engineering_identity_retries_permanent(
    policy, change
):
    auto, now = policy
    auto.errors["HAAS"] = ProfileBlocked("profile")
    w = StagingWorker(lambda: auto)
    w.sweep()
    if change == "profile":
        auto.signatures["HAAS"] = "h2"
    else:
        auto.parent[
            {
                "revision": "revision_id",
                "spec": "spec_sha256",
                "source": "source_sha256",
            }[change]
        ] += "new"
    w.sweep()
    w.sweep()
    assert auto.calls.count("HAAS") == 2


def test_402_circuit_is_shared_persistent_and_exponential(policy, caplog):
    auto, now = policy
    auto.errors["HAAS"] = ProviderUnavailable(402)
    w = StagingWorker(lambda: auto)
    w.sweep()
    w.sweep()
    restarted = StagingWorker(lambda: auto)
    restarted.sweep()
    assert auto.calls == ["HAAS"]
    ledger = RetryLedger(auto.service.repo)
    assert ledger.get(CIRCUIT_KEY)["retry_at"] == 1300
    now[0] = 1299
    restarted.sweep()
    assert auto.calls == ["HAAS"]
    now[0] = 1300
    restarted.sweep()
    assert ledger.get(CIRCUIT_KEY)["attempts"] == 2
    assert ledger.get(CIRCUIT_KEY)["retry_at"] == 1900
    assert auto.calls == ["HAAS", "HAAS"]
    assert caplog.text.count("dependency unavailable; bounded retry scheduled") == 1
    now[0] = 1900
    auto.errors.clear()
    restarted.sweep()
    assert ledger.get(CIRCUIT_KEY)["state"] == "READY"
    assert auto.calls[-2:] == ["HAAS", "PACKAGING"]


@pytest.mark.parametrize("status", [None, 402, 429, 500, 503])
def test_backoff_is_bounded(status):
    values = [delay(n, status) for n in range(1, 40)]
    assert values == sorted(values)
    assert max(values) == (3600 if status == 402 else 900)


def test_integrity_failure_is_not_misclassified_as_permanent_profile(policy):
    auto, now = policy
    auto.errors["HAAS"] = WorkflowError("artifact integrity failure")
    w = StagingWorker(lambda: auto)
    w.sweep()
    w.sweep()
    row = RetryLedger(auto.service.repo).get(job_key("HAAS", auto.parent, "h1"))
    assert row["state"] == "RETRY" and row["retry_at"] == 1030
    assert auto.calls.count("HAAS") == 1
    assert auto.calls.count("PACKAGING") == 2
    now[0] = 1030
    w.sweep()
    assert auto.calls.count("HAAS") == 2


def test_missing_retry_migration_fails_closed_without_artifact_work(policy):
    auto, now = policy
    with auto.service.repo.connect() as db:
        db.execute("DROP TABLE manufacturing_retry_control")
    w = StagingWorker(lambda: auto)
    assert w.sweep() == {} and auto.calls == [] and w.scan_retry_at > time.monotonic()


def test_actual_profile_rejection_downloads_parent_once_even_after_restart(
    system, monkeypatch
):
    from dataclasses import replace
    from test_automatic_staging import stager, parent_for

    svc, parent, _, spec = system
    rev = svc.repo.create_revision(
        parent["plate_id"],
        replace(spec, material="316 Stainless Steel"),
        expected_current=parent["revision_id"],
        reason="synthetic rejection",
        actor="fixture",
        source_snapshot={},
    )
    svc.repo.approve(svc.repo.create_delivery(rev["id"])["token"], "synthetic-customer")
    counts = []
    original = svc.repo._read_object
    monkeypatch.setattr(
        svc.repo, "_read_object", lambda key: counts.append(key) or original(key)
    )
    w = StagingWorker(lambda: stager(svc))
    w.sweep()
    first = len(counts)
    w.sweep()
    StagingWorker(lambda: stager(svc)).sweep()
    assert len(counts) == first
    assert w.status(rev["id"])["HAAS"]["retry_state"] == "PERMANENT"
    assert w.status(rev["id"])["PACKAGING"]["state"] == "STAGED"


def test_cache_verifies_every_hit_and_evicts_expired_bytes():
    now = [0]
    cache = VerifiedArtifactCache(ttl=5, clock=lambda: now[0])
    calls = []
    data = b"verified"
    h = sha256(data).hexdigest()

    def load(key):
        calls.append(key)
        return data

    assert cache.read("key", h, len(data), load) == data
    assert cache.read("key", h, len(data), load) == data and calls == ["key"]
    now[0] = 5
    cache.read("key", h, len(data), load)
    assert len(calls) == 2
    identity = ("key", h, len(data))
    cache.entries[identity] = (5, b"corrupt!")
    with pytest.raises(WorkflowError, match="integrity"):
        cache.read("key", h, len(data), load)


def test_cache_does_not_store_unverified_bytes_and_keys_by_expected_hash():
    cache = VerifiedArtifactCache()
    h = sha256(b"good").hexdigest()
    with pytest.raises(WorkflowError):
        cache.read("key", h, 4, lambda _: b"evil")
    assert not cache.entries
    assert cache.read("key", h, 4, lambda _: b"good") == b"good"
    h2 = sha256(b"next").hexdigest()
    assert cache.read("key", h2, 4, lambda _: b"next") == b"next"


def test_cache_memory_and_entry_count_are_bounded():
    c = VerifiedArtifactCache(maximum_bytes=8, maximum_entries=2)
    for i in range(10):
        data = str(i).encode() * 4
        c.read(str(i), sha256(data).hexdigest(), len(data), lambda _, data=data: data)
    assert len(c.entries) == 2 and c.size == 8
    data = b"oversized"
    c.read("big", sha256(data).hexdigest(), len(data), lambda _: data)
    assert len(c.entries) == 2 and c.size == 8


class Raw:
    closed = False

    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class Pool:
    def __init__(self, *args, **kwargs):
        self.maximum = args[1]
        self.active = 0
        self.peak = 0
        self.created = 0
        self.idle = []
        self.lock = threading.Lock()

    def getconn(self):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.idle:
                return self.idle.pop()
            self.created += 1
            return Raw()

    def putconn(self, raw, close=False):
        with self.lock:
            self.active -= 1
            if not close:
                self.idle.append(raw)


def test_pool_bounds_parallel_connections_and_cleans_transactions():
    p = RepositoryPool("synthetic", "controlled-search-path", maximum=2, factory=Pool)

    def task(_):
        with p.connection() as raw:
            time.sleep(0.002)
            return raw

    with ThreadPoolExecutor(max_workers=8) as ex:
        raws = list(ex.map(task, range(20)))
    assert p.pool.peak <= 2 and p.pool.created <= 2 and p.pool.active == 0
    assert sum(r.rollbacks for r in p.pool.idle) == 20
    with pytest.raises(ValueError):
        with p.connection():
            raise ValueError("synthetic failure")
    assert p.pool.active == 0


def test_database_errors_are_sanitized_and_slots_are_released():
    def unavailable(*args, **kwargs):
        raise psycopg2.OperationalError("sensitive DSN")

    p = RepositoryPool("synthetic", "controlled", factory=unavailable)
    for _ in range(5):
        with pytest.raises(ProviderUnavailable, match="private dependency unavailable"):
            with p.connection():
                pass
    assert p.pool is None


def test_retry_migration_is_private_and_cannot_change_protected_tables():
    for schema in ("frozen_plate_prototype", "frozen_plate_production"):
        sql = retry_migration(schema)
        assert "ENABLE ROW LEVEL SECURITY" in sql and "FORCE ROW LEVEL SECURITY" in sql
        assert "FROM PUBLIC, anon, authenticated" in sql
        assert (
            "GRANT SELECT, INSERT, UPDATE ON TABLE manufacturing_retry_control" in sql
        )
        assert "DELETE" not in sql and "ALTER TABLE frozen_" not in sql
    with pytest.raises(ValueError):
        retry_migration("public")
