"""Production-only private adapter. Staging credentials cannot satisfy its guard."""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import os
import re
import shutil
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import psycopg2
from itsdangerous import URLSafeSerializer

from .repository import Repository, WorkflowError
from .runtime import PRODUCTION_API, PRODUCTION_PROJECT
from .staging import Connection, PrivateStorage, StagingRepository

PROJECT_URL = "https://" + PRODUCTION_PROJECT + ".supabase.co"
SCHEMA = "frozen_plate_production"
ROLE = "frozen_plate_production_api"
BUCKET = "frozen-plate-production"


class ProductionStorage(PrivateStorage):
    def __init__(self, url, key, bucket):
        if (
            url != PROJECT_URL
            or bucket != BUCKET
            or not key
            or not key.startswith("sb_secret_")
        ):
            raise ValueError("modern production private storage configuration required")
        self.bucket = bucket
        self.client = httpx.Client(
            base_url=url + "/storage/v1",
            headers={"apikey": key},
            timeout=30,
            follow_redirects=False,
        )


class ProductionRepository(Repository):
    # Shared immutable artifact/transaction mechanics; staging guards stay intact.
    transaction = StagingRepository.transaction
    _publish_objects = StagingRepository._publish_objects
    _remove_uncommitted_objects = StagingRepository._remove_uncommitted_objects
    _read_object = StagingRepository._read_object
    part_prefix = "PRD-"
    order_actor = "completed-order"
    admin_actor = "production-admin"

    def __init__(self, environ=None, *, clock=time.time, storage=None):
        env = os.environ if environ is None else environ
        url = env.get("FROZEN_PLATE_DATABASE_URL", "")
        parsed = urlsplit(url)
        direct = (
            parsed.hostname == "db." + PRODUCTION_PROJECT + ".supabase.co"
            and parsed.username == ROLE
        )
        pooled = (
            bool(
                re.fullmatch(
                    r"aws-\d+-us-west-2\.pooler\.supabase\.com", parsed.hostname or ""
                )
            )
            and parsed.username == ROLE + "." + PRODUCTION_PROJECT
        )
        if (
            env.get("APP_ENV") != "production"
            or env.get("FROZEN_PLATE_ENABLED") != "true"
            or env.get("RENDER_SERVICE_ID") != "srv-d51l6ch5pdvs73ealnh0"
            or not (direct or pooled)
            or parsed.path != "/postgres"
            or parsed.port != 5432
            or parse_qs(parsed.query).get("sslmode") != ["require"]
            or not parsed.password
        ):
            raise ValueError("dedicated production database configuration required")
        key = env.get("FROZEN_PLATE_SIGNING_KEY", "")
        if len(key) < 64:
            raise ValueError("dedicated strong production signing key required")
        self._database_url = url
        self.clock, self.ttl_seconds = clock, 30 * 86400
        self.delivery_origin = PRODUCTION_API
        self.signer = URLSafeSerializer(
            key,
            salt="frozen-plate-production-" + PRODUCTION_PROJECT + "-v1",
            signer_kwargs={"digest_method": sha256},
        )
        self.root = Path(tempfile.mkdtemp(prefix="frozen-plate-production-"))
        self.objects = self.root / "objects"
        self.objects.mkdir(mode=0o700)
        self.storage = storage or ProductionStorage(
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
                options="-c search_path=" + SCHEMA + ",pg_catalog",
            )
        except psycopg2.Error:
            raise WorkflowError("production database unavailable") from None
        raw.autocommit = True
        try:
            yield Connection(raw)
        finally:
            raw.close()

    def create_delivery(self, revision_id, *, base_url=PRODUCTION_API):
        delivery = Repository.create_delivery(self, revision_id, base_url=base_url)
        object_key = "confirmation/" + delivery["id"] + ".eml"
        try:
            self.storage.put(object_key, delivery["mime"])
            if self.storage.get(object_key) != delivery["mime"]:
                raise WorkflowError("captured confirmation bytes differ")
        except Exception:
            self.storage.remove([object_key])
            raise WorkflowError("confirmation capture unavailable") from None
        return delivery

    def create_revision(self, *args, **kwargs):
        result = Repository.create_revision(self, *args, **kwargs)
        shutil.rmtree(self.objects / result["plate_id"] / result["id"])
        return result
