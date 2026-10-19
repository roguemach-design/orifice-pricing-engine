"""Fail-open bounded sidecar. Never a prerequisite for customer actions."""

import hashlib
import logging
import os
import queue
import threading
import time
from sqlalchemy import create_engine
from .schema import CONSENT_VERSION

log = logging.getLogger(__name__)
_store = None
_queue = queue.Queue(maxsize=256)
_stop = threading.Event()
_thread = None
_dropped = 0
_store_lock = threading.Lock()


def enabled():
    return (
        os.environ.get("JOURNEY_ENABLED") == "true"
        and os.environ.get("JOURNEY_DISCLOSURE_VERSION") == CONSENT_VERSION
    )


def _get_store():
    global _store
    if not enabled() and os.environ.get("JOURNEY_STORAGE_ENABLED") != "true":
        return None
    if _store is None:
        from .store import Store

        url = os.environ.get("JOURNEY_DATABASE_URL") or os.environ.get("DATABASE_URL")
        secret = os.environ.get("JOURNEY_SIGNING_KEY") or os.environ.get(
            "ADMIN_API_KEY"
        )
        if not url or not secret:
            return None
        options = {"pool_pre_ping": True}
        if url.startswith("postgres"):
            options["connect_args"] = {
                "connect_timeout": 2,
                "options": "-c statement_timeout=2000 -c lock_timeout=1000",
            }
        _store = Store(
            create_engine(url, **options),
            hashlib.sha256(("journey-v1:" + secret).encode()).hexdigest(),
            internal=os.environ.get("APP_ENV") != "production",
        )
    return _store


def get_store():
    with _store_lock:
        return _get_store()


def submit(method, *args, **kwargs):
    global _dropped
    if not enabled():
        return
    try:
        _queue.put_nowait((method, args, kwargs))
    except queue.Full:
        _dropped += 1


def worker():
    global _dropped
    next_prune = 0
    while not _stop.is_set():
        try:
            store = get_store()
            if store is not None and time.monotonic() >= next_prune:
                store.prune()
                next_prune = time.monotonic() + 3600
            method, args, kwargs = _queue.get(timeout=0.5)
        except queue.Empty:
            continue
        except Exception:
            # No token, exception body, request contents, URL or identity is logged.
            _dropped += 1
            _stop.wait(1)
            continue
        try:
            if store is not None:
                getattr(store, method)(*args, **kwargs)
            else:
                _dropped += 1
        except Exception:
            _dropped += 1
        finally:
            _queue.task_done()


def start():
    global _thread
    if (enabled() or os.environ.get("JOURNEY_STORAGE_ENABLED") == "true") and (
        _thread is None or not _thread.is_alive()
    ):
        _stop.clear()
        _thread = threading.Thread(target=worker, daemon=True, name="journey-sidecar")
        _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=1)


def coverage():
    return {
        "queue_drops_or_storage_failures": _dropped,
        "queued": _queue.qsize(),
        "notice": "Best-effort diagnostics; outages, consent refusal and blockers cause missing data.",
    }


def observe_error(token, step, category):
    if not enabled() or not isinstance(token, str) or len(token) != 108:
        return
    try:
        from .schema import ServerEvent
        from uuid import uuid4
        from datetime import datetime, timezone

        event = ServerEvent(
            version=1,
            event_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            step=step,
            outcome="blocked" if category == "system_restriction" else "error",
            category=category,
        )
        submit("add", token, event)
    except Exception:
        pass
