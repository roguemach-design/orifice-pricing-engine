"""Approval wake-up plus periodic restart recovery; no owner-view mutations.

No new queue/database/state machine: approved parents and immutable bundle keys
are the durable work source. The existing repository transaction lock serializes
replicas. Failures stay pending and retry independently of customer approval.
"""

from threading import Event, Lock, Thread
import logging
import os

wake_event = Event()
logger = logging.getLogger(__name__)


def automatic_enabled():
    # Worker-only switch. FINAL4_ENABLED still owns the manual engineering routes.
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

    def sweep(self):
        if not automatic_enabled():
            return self.states
        stager = self.factory()
        states = {}
        for parent in stager.parents():
            for family in ("HAAS", "PACKAGING"):
                try:
                    bid = stager.ensure(family, parent)
                    result = dict(state="STAGED", bundle_id=bid)
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
                except ValueError as error:
                    known = {
                        "historical packaging requires explicit owner generation; automatic upgrade disabled": "Historical approval retained. New packaging geometry requires explicit owner generation of a new derived bundle.",
                        "nest clearance collapses canonical neck radius; require clearance below 0.03125 inch": "Packaging clearance must be below the canonical 0.03125 inch neck radius to preserve tangent arcs.",
                        "handle cannot safely accommodate two side finger reliefs with corner, transition and cardboard bridges": "Handle cannot safely fit two side finger reliefs with the required corner, transition and cardboard bridges.",
                        "material has no approved profile cutting parameters": "No controlled machining profile matches this material. A compatible material/tooling profile is required.",
                        "bore/tool sweep lacks radial fixture opening clearance": "The frozen bore exceeds the controlled fixture opening. A compatible fixture profile is required.",
                        "supported exact chamfer geometry required": "The Frozen Plate lacks the supported explicit chamfer geometry/orientation.",
                    }
                    result = dict(
                        state="SETUP / PROFILE VERIFICATION REQUIRED",
                        detail=known.get(
                            str(error),
                            "Frozen dimensions exceed the controlled machine/tool/probe envelope. Engineering profile verification is required.",
                        ),
                    )
                    logger.warning(
                        "Internal derivative staging blocked by profile limits (%s)",
                        family,
                    )
                except Exception:
                    # No record payloads, exception messages, credentials or object keys.
                    result = dict(
                        state="SETUP / PROFILE VERIFICATION REQUIRED",
                        detail="Automatic staging is blocked by incompatible inputs, profile limits or storage verification. The service retries automatically; approval is unchanged.",
                    )
                    logger.warning("Internal derivative staging blocked (%s)", family)
                states.setdefault(parent["revision_id"], {})[family] = result
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
