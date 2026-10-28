"""Bounded private transport resources. No credentials or workflow state in logs."""

from collections import OrderedDict
from contextlib import contextmanager
from hashlib import sha256
from threading import Lock, BoundedSemaphore
import time
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from .repository import WorkflowError


class ProviderUnavailable(WorkflowError):
    def __init__(self, status=None, *, message="private dependency unavailable"):
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        super().__init__(message)


class RepositoryPool:
    def __init__(self, url, options, *, maximum=4, factory=ThreadedConnectionPool):
        self.url, self.options, self.maximum, self.factory = (
            url,
            options,
            maximum,
            factory,
        )
        self.pool = None
        self.lock = Lock()
        self.slots = BoundedSemaphore(maximum)

    @contextmanager
    def connection(self):
        if not self.slots.acquire(timeout=5):
            raise ProviderUnavailable()
        raw = None
        try:
            with self.lock:
                if self.pool is None:
                    self.pool = self.factory(
                        1,
                        self.maximum,
                        self.url,
                        connect_timeout=15,
                        options=self.options,
                    )
            raw = self.pool.getconn()
            raw.autocommit = True
            yield raw
        except psycopg2.Error:
            raise ProviderUnavailable() from None
        finally:
            try:
                if raw is not None:
                    broken = bool(raw.closed)
                    if not broken:
                        try:
                            raw.rollback()  # End even manually opened read transactions.
                        except psycopg2.Error:
                            broken = True
                    self.pool.putconn(raw, close=broken)
            finally:
                self.slots.release()


class VerifiedArtifactCache:
    def __init__(
        self,
        *,
        maximum_bytes=32 * 1024 * 1024,
        maximum_entries=256,
        ttl=300,
        clock=time.monotonic
    ):
        self.maximum_bytes, self.maximum_entries, self.ttl = (
            maximum_bytes,
            maximum_entries,
            ttl,
        )
        self.clock = clock
        self.entries = OrderedDict()
        self.size = 0
        self.lock = Lock()

    def read(self, key, expected_hash, expected_size, loader):
        identity = (key, expected_hash, expected_size)
        with self.lock:
            hit = self.entries.pop(identity, None)
            if hit:
                self.size -= len(hit[1])
                if self.clock() - hit[0] < self.ttl:
                    self.entries[identity] = hit
                    self.size += len(hit[1])
                    data = hit[1]
                else:
                    data = None
            else:
                data = None
        if data is not None:
            if len(data) != expected_size or sha256(data).hexdigest() != expected_hash:
                raise WorkflowError("artifact integrity failure")
            return data
        data = loader(key)
        if len(data) != expected_size or sha256(data).hexdigest() != expected_hash:
            raise WorkflowError("artifact integrity failure")
        if len(data) <= self.maximum_bytes:
            with self.lock:
                old = self.entries.pop(identity, None)
                if old:
                    self.size -= len(old[1])
                self.entries[identity] = (self.clock(), data)
                self.size += len(data)
                while (
                    self.size > self.maximum_bytes
                    or len(self.entries) > self.maximum_entries
                ):
                    _, (_, value) = self.entries.popitem(last=False)
                    self.size -= len(value)
        return data
