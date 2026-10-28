"""Approval wake-up plus periodic restart recovery; no owner-view mutations.

Approved parents and immutable bundle keys remain the work source. A separate
private control table records keyed failure suppression and bounded provider
retries. Existing workflow records and customer approvals are never changed.
"""

from threading import Event, Lock, Thread
import os
import time
from .retry import (
    RetryLedger,
    ProfileBlocked,
    ProviderUnavailable,
    CIRCUIT_KEY,
    job_key,
    delay,
)
import logging

wake_event = Event()
logger = logging.getLogger(__name__)


def automatic_enabled():
    # Independent of FINAL4_ENABLED: manual owner routes remain available.
    return os.environ.get("FINAL4_AUTOMATIC_STAGING_ENABLED", "true") == "true"


def request_scan():
    if automatic_enabled():
        wake_event.set()


class StagingWorker:
    def __init__(self, stager_factory, *, interval=30):
        self.factory, self.interval = stager_factory, interval
        self.stop_event, self.lock = Event(), Lock()
        self.states = {}
        self.thread = None
        self.scan_attempts = 0
        self.scan_retry_at = 0
        self.provider_retry_at = 0
        self.provider_retry_deadline = 0

    def sweep(self):
        if not automatic_enabled() or time.monotonic() < self.scan_retry_at:
            return self.states
        try:
            return self._sweep()
        except Exception:
            self.scan_attempts += 1
            self.scan_retry_at = time.monotonic() + delay(self.scan_attempts)
            if self.scan_attempts == 1:
                logger.warning(
                    "Automatic derivative scan unavailable; bounded retry scheduled"
                )
            return self.states

    def _sweep(self):
        stager = self.factory()
        repo = stager.service.repo
        ledger = RetryLedger(repo)
        now = repo.clock()
        circuit = ledger.get(CIRCUIT_KEY)
        if circuit and circuit["state"] == "CIRCUIT" and circuit["retry_at"] > now:
            self.provider_retry_at = circuit["retry_at"]
            self.provider_retry_deadline = time.monotonic() + circuit["retry_at"] - now
            return self.states
        states = {}
        profiles = stager.profiles()
        outage = False
        for parent in stager.parents():
            for family in ("HAAS", "PACKAGING"):
                key = job_key(family, parent, profiles[family])
                previous = ledger.get(key)
                if previous and (
                    previous["state"] == "PERMANENT"
                    or previous["state"] == "RETRY"
                    and previous["retry_at"] > now
                ):
                    states.setdefault(parent["revision_id"], {})[family] = previous[
                        "result"
                    ]
                    continue
                try:
                    bid = stager.ensure(family, parent)
                    result = dict(state="STAGED", bundle_id=bid)
                    if previous and previous["state"] != "READY":
                        ledger.put(key, "READY", 0, 0, result, now)
                    if (
                        self.status(parent["revision_id"])
                        .get(family, {})
                        .get("bundle_id")
                        != bid
                    ):
                        logger.info(
                            "Automatic %s artifact available for an approved current revision",
                            family,
                        )
                except ProfileBlocked:
                    result = dict(
                        state="SETUP / PROFILE VERIFICATION REQUIRED",
                        detail="Unchanged engineering profile rejection; retry requires a new revision or controlled profile.",
                        retry_state="PERMANENT",
                        failure_code="PROFILE_BLOCKED",
                    )
                    ledger.put(key, "PERMANENT", 0, 0, result, now)
                    logger.warning(
                        "Automatic %s profile rejection recorded; unchanged retries suppressed",
                        family,
                    )
                except Exception as error:
                    attempts = (previous or {}).get("attempts", 0) + 1
                    status = (
                        error.status if isinstance(error, ProviderUnavailable) else None
                    )
                    retry_at = now + delay(attempts, status)
                    result = dict(
                        state="DEPENDENCY UNAVAILABLE",
                        failure_code=(
                            "PROVIDER_RESTRICTED"
                            if status == 402
                            else "DEPENDENCY_UNAVAILABLE"
                        ),
                        detail="Bounded retry scheduled; approval and original artifacts are unchanged.",
                        retry_at=retry_at,
                    )
                    ledger.put(key, "RETRY", attempts, retry_at, result, now)
                    if not previous or previous["state"] != "RETRY":
                        logger.warning(
                            "Automatic %s dependency unavailable; bounded retry scheduled",
                            family,
                        )
                    if isinstance(error, ProviderUnavailable):
                        attempts = (circuit or {}).get("attempts", 0) + 1
                        ledger.put(
                            CIRCUIT_KEY,
                            "CIRCUIT",
                            attempts,
                            now + delay(attempts, status),
                            result,
                            now,
                        )
                        self.provider_retry_at = now + delay(attempts, status)
                        self.provider_retry_deadline = time.monotonic() + delay(
                            attempts, status
                        )
                        outage = True
                states.setdefault(parent["revision_id"], {})[family] = result
                if outage:
                    break
            if outage:
                break
        if not outage:
            self.provider_retry_at = self.provider_retry_deadline = 0
            if circuit and circuit["state"] == "CIRCUIT":
                ledger.put(CIRCUIT_KEY, "READY", 0, 0, {}, now)
        self.scan_attempts, self.scan_retry_at = 0, 0
        with self.lock:
            self.states = states
        return states

    def status(self, revision_id):
        if not automatic_enabled():
            return {
                family: dict(
                    state="AUTOMATIC STAGING DISABLED",
                    detail="Owner containment: manual engineering routes remain independently authorized.",
                )
                for family in ("HAAS", "PACKAGING")
            }
        if max(self.scan_retry_at, self.provider_retry_deadline) > time.monotonic():
            return {
                family: dict(
                    state="DEPENDENCY UNAVAILABLE",
                    detail="Automatic engineering is cooling down; manual routes remain independently authorized.",
                    retry_at=self.provider_retry_at or None,
                )
                for family in ("HAAS", "PACKAGING")
            }
        with self.lock:
            return self.states.get(revision_id, {})

    def run(self):
        while not self.stop_event.is_set():
            wake_event.clear()
            try:
                self.sweep()
            except Exception:
                logger.warning("Automatic derivative scan unavailable; retry scheduled")
            wake_event.wait(self.interval)

    def start(self):
        if not automatic_enabled():
            return
        if self.thread is None:
            self.thread = Thread(
                target=self.run, name="manufacturing-stager", daemon=True
            )
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        wake_event.set()
        if self.thread:
            self.thread.join(timeout=2)


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    runner = getattr(app.state, "manufacturing_stager", None)
    if runner is not None:
        runner.start()
    try:
        yield
    finally:
        if runner is not None:
            runner.stop()
