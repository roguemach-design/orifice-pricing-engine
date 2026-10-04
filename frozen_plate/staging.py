"""Staging-only PostgreSQL/private Storage adapter. Never logs credentials."""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path, PurePosixPath
import os
import shutil
import tempfile
import time
from urllib.parse import quote, urlsplit

import httpx
import psycopg2
from psycopg2.extras import DictCursor
from itsdangerous import URLSafeSerializer

from .repository import Repository, WorkflowError

PROJECT_URL = "https://ixhnanttetuhpzvrnvdc.supabase.co"
API_ORIGIN = "https://oplates-pricing-api-staging.onrender.com"


class Connection:
    """Small compatibility boundary for the accepted repository SQL."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, query, args=()):
        if query == "BEGIN":
            query = "BEGIN ISOLATION LEVEL REPEATABLE READ"
        if "INSERT OR IGNORE INTO" in query:
            query = query.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            query += " ON CONFLICT (revision_id,route) DO NOTHING"
        cursor = self.raw.cursor(cursor_factory=DictCursor)
        cursor.execute(query.replace("?", "%s"), args)
        return cursor

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


class PrivateStorage:
    def __init__(self, url, key, bucket):
        if url != PROJECT_URL or bucket != "frozen-plate-staging" or not key:
            raise ValueError("staging private storage configuration required")
        self.bucket = bucket
        self.client = httpx.Client(
            base_url=url + "/storage/v1",
            headers={"apikey": key},
            timeout=30,
            follow_redirects=False,
        )

    @staticmethod
    def safe_key(key):
        p = PurePosixPath(key)
        if p.is_absolute() or ".." in p.parts or str(p) != key:
            raise WorkflowError("invalid private object key")
        return quote(key, safe="/")

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise WorkflowError("private storage unavailable") from None
        if not response.is_success:
            # Never propagate response bodies, request headers or credentials.
            raise WorkflowError("private storage operation failed")
        return response

    def put(self, key, data):
        self.request(
            "POST",
            "/object/" + self.bucket + "/" + self.safe_key(key),
            content=data,
            headers={"content-type": "application/octet-stream", "x-upsert": "false"},
        )

    def get(self, key):
        return self.request(
            "GET", "/object/" + self.bucket + "/" + self.safe_key(key)
        ).content

    def remove(self, keys):
        for key in keys:
            self.safe_key(key)
        self.request("DELETE", "/object/" + self.bucket, json={"prefixes": keys})


class StagingRepository(Repository):
    def __init__(self, environ=None, *, clock=time.time, storage=None):
        env = os.environ if environ is None else environ
        url = env.get("FROZEN_PLATE_DATABASE_URL", "")
        parsed = urlsplit(url)
        if (
            env.get("APP_ENV") != "staging"
            or parsed.hostname != "aws-0-us-east-1.pooler.supabase.com"
            or parsed.username != "frozen_plate_staging_api.ixhnanttetuhpzvrnvdc"
            or parsed.path != "/postgres"
            or parsed.port != 5432
            or "sslmode=require" not in parsed.query
        ):
            raise ValueError("dedicated staging database configuration required")
        key = env.get("FROZEN_PLATE_SIGNING_KEY", "")
        if len(key) < 64:
            raise ValueError("dedicated strong staging signing key required")
        self._database_url = url
        self.clock, self.ttl_seconds = clock, 30 * 86400
        self.delivery_origin = API_ORIGIN
        self.signer = URLSafeSerializer(
            key,
            salt="frozen-plate-staging-ixhnanttetuhpzvrnvdc-v1",
            signer_kwargs={"digest_method": sha256},
        )
        self.root = Path(tempfile.mkdtemp(prefix="frozen-plate-staging-"))
        self.objects = self.root / "objects"
        self.objects.mkdir(mode=0o700)
        self.storage = storage or PrivateStorage(
            env.get("FROZEN_PLATE_SUPABASE_URL"),
            env.get("FROZEN_PLATE_STORAGE_KEY"),
            env.get("FROZEN_PLATE_BUCKET"),
        )

    @contextmanager
    def connect(self):
        try:
            raw = psycopg2.connect(
                self._database_url,
                connect_timeout=15,
                options="-c search_path=frozen_plate_prototype,pg_catalog",
            )
        except psycopg2.Error:
            raise WorkflowError("staging database unavailable") from None
        raw.autocommit = True
        try:
            yield Connection(raw)
        finally:
            raw.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            # Serialize workflow writes across replicas, matching local BEGIN IMMEDIATE.
            db.execute("SELECT pg_advisory_xact_lock(704205001)")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _publish_objects(self, destination):
        for path in destination.iterdir():
            key = str(path.relative_to(self.objects))
            data = path.read_bytes()
            self.storage.put(key, data)
            if self.storage.get(key) != data:
                raise WorkflowError("stored artifact differs from generated bytes")

    def _remove_uncommitted_objects(self, destination):
        self.storage.remove(
            [str(p.relative_to(self.objects)) for p in destination.iterdir()]
        )

    def _read_object(self, key):
        return self.storage.get(key)

    def create_revision(self, *args, **kwargs):
        result = super().create_revision(*args, **kwargs)
        shutil.rmtree(self.objects / result["plate_id"] / result["id"])
        return result

    def create_delivery(self, revision_id, *, base_url=API_ORIGIN):
        delivery = super().create_delivery(revision_id, base_url=base_url)
        object_key = "confirmation/" + delivery["id"] + ".eml"
        try:
            self.storage.put(object_key, delivery["mime"])
            if self.storage.get(object_key) != delivery["mime"]:
                raise WorkflowError("captured confirmation bytes differ")
        except Exception:
            self.storage.remove([object_key])
            raise WorkflowError("confirmation capture unavailable") from None
        return delivery
