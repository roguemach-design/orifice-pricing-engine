"""Local immutable repository. All mutations serialize on BEGIN IMMEDIATE.

No network, email delivery, vendor client, production configuration or automatic
release. Object data lives outside SQL, in private revision directories.
"""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
import time
from uuid import uuid4

from itsdangerous import URLSafeSerializer, BadSignature
from manufacturing_context import DrawingState
from manufacturing_drawing import DrawingMetadata, GENERATOR_VERSION
from manufacturing_files import generate_package
from plate_geometry import PlateSpec, build_plate_geometry, GEOMETRY_VERSION
from .validation import validate_package
from .presentation import TEMPLATE_VERSION, mime_email


class WorkflowError(ValueError):
    pass


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def digest(value):
    return sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", value):
        raise WorkflowError(
            "identifier must be 1-40 letters, digits, underscores or hyphens"
        )
    return value


IMMUTABLE_TABLES = (
    "revisions",
    "artifacts",
    "tokens",
    "revocations",
    "deliveries",
    "approvals",
    "sourcing",
)
ROUTES = ("SENDCUTSEND", "ALRO", "ROGUE_INTERNAL")


class Repository:
    def __init__(self, root, signing_key, *, clock=time.time, ttl_seconds=30 * 86400):
        if len(signing_key) < 32 or ttl_seconds <= 0:
            raise ValueError("dedicated random signing key and positive TTL required")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.objects = self.root / "objects"
        self.objects.mkdir(exist_ok=True, mode=0o700)
        self.objects.chmod(0o700)
        self.db_path = self.root / "frozen-plate.sqlite3"
        self.clock, self.ttl_seconds = clock, ttl_seconds
        self.delivery_origin = "http://127.0.0.1:8765"
        self.signer = URLSafeSerializer(
            signing_key,
            salt="frozen-plate-approval-v1",
            signer_kwargs={"digest_method": sha256},
        )
        with self.connect() as db:
            db.executescript((Path(__file__).parent / "schema/sqlite.sql").read_text())
            for suffix in IMMUTABLE_TABLES:
                table = "frozen_plate_" + suffix
                for operation in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS no_{operation.lower()}_{table} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable frozen record'); END"
                    )
        self.db_path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def now(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(
            timespec="seconds"
        )

    def create_plate(self, *, order_id, line_id, configuration_id, customer_id, actor):
        for value in (order_id, line_id, configuration_id, customer_id, actor):
            identifier(value)
        plate_id = str(uuid4())
        with self.transaction() as db:
            db.execute(
                "INSERT INTO frozen_plates(id,order_id,line_id,configuration_id,customer_id,created_at,created_by) VALUES (?,?,?,?,?,?,?)",
                (
                    plate_id,
                    order_id,
                    line_id,
                    configuration_id,
                    customer_id,
                    self.now(),
                    actor,
                ),
            )
        return plate_id

    def ensure_order_plate(
        self, *, order_id, line_id, configuration_id, customer_id, actor
    ):
        """Serialize identity lookup/creation in the same transaction."""
        for value in (order_id, line_id, configuration_id, customer_id, actor):
            identifier(value)
        with self.transaction() as db:
            existing = db.execute(
                "SELECT id,customer_id FROM frozen_plates WHERE order_id=? AND line_id=?",
                (order_id, line_id),
            ).fetchone()
            if existing:
                if existing["customer_id"] != customer_id:
                    raise WorkflowError("order ownership mismatch")
                return existing["id"]
            plate_id = str(uuid4())
            db.execute(
                "INSERT INTO frozen_plates(id,order_id,line_id,configuration_id,customer_id,created_at,created_by) VALUES (?,?,?,?,?,?,?)",
                (
                    plate_id,
                    order_id,
                    line_id,
                    configuration_id,
                    customer_id,
                    self.now(),
                    actor,
                ),
            )
            return plate_id

    @staticmethod
    def _one(db, query, args):
        row = db.execute(query, args).fetchone()
        if row is None:
            raise WorkflowError("record not found")
        return dict(row)

    def plate(self, plate_id):
        with self.connect() as db:
            return self._one(db, "SELECT * FROM frozen_plates WHERE id=?", (plate_id,))

    def revision(self, revision_id):
        with self.connect() as db:
            revision = self._one(
                db, "SELECT * FROM frozen_plate_revisions WHERE id=?", (revision_id,)
            )
            revision["artifacts"] = {
                r["kind"]: dict(r)
                for r in db.execute(
                    "SELECT * FROM frozen_plate_artifacts WHERE revision_id=?",
                    (revision_id,),
                )
            }
            return revision

    def create_revision(
        self,
        plate_id,
        spec,
        *,
        expected_current,
        reason,
        actor,
        source_snapshot,
        metadata=None,
    ):
        if not isinstance(spec, PlateSpec) or not reason.strip() or not actor.strip():
            raise WorkflowError("validated PlateSpec, reason and actor required")
        geometry = build_plate_geometry(spec)
        source_json = canonical(source_snapshot)
        spec_json = canonical(asdict(spec))
        revision_id = str(uuid4())
        destination = self.objects / plate_id / revision_id
        committed = False
        try:
            with self.transaction() as db:
                plate = self._one(
                    db, "SELECT * FROM frozen_plates WHERE id=?", (plate_id,)
                )
                if plate["current_revision"] != expected_current:
                    raise WorkflowError("revision conflict: reload current revision")
                number = db.execute(
                    "SELECT COALESCE(MAX(number),0)+1 FROM frozen_plate_revisions WHERE plate_id=?",
                    (plate_id,),
                ).fetchone()[0]
                base_metadata = asdict(metadata or DrawingMetadata())
                base_metadata.update(
                    revision=f"R{number}",
                    state=DrawingState.CUSTOMER_CONFIRMATION,
                    specification_revision=f"R{number}",
                    order_line_revision=f'{plate["line_id"]}-R{number}',
                    order_identifier=plate["order_id"],
                )
                drawing = DrawingMetadata(**base_metadata)
                stem = f'OP-{identifier(spec.part_identifier)}-{plate["line_id"]}-R{number}'
                with tempfile.TemporaryDirectory(
                    prefix=".generating-", dir=self.root
                ) as staging:
                    outputs = generate_package(
                        geometry,
                        Path(staging),
                        stem,
                        include_svg=False,
                        metadata=drawing,
                    )
                    validate_package(geometry, drawing, outputs)
                    # Unique private directory is never reused or overwritten. Publish bytes
                    # before metadata commit: a crash can leave only an unreferenced orphan.
                    destination.parent.mkdir(exist_ok=True, mode=0o700)
                    os.rename(staging, destination)
                    destination.chmod(0o700)
                    for file in destination.iterdir():
                        file.chmod(0o400)
                        with file.open("rb") as f:
                            os.fsync(f.fileno())
                # Persist directory entries before publishing DB metadata.
                for directory in (destination, destination.parent, self.objects):
                    fd = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                self._publish_objects(destination)
                now = self.now()
                db.execute(
                    "INSERT INTO frozen_plate_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        revision_id,
                        plate_id,
                        number,
                        spec_json,
                        digest(spec_json),
                        source_json,
                        digest(source_json),
                        4,
                        GENERATOR_VERSION,
                        GEOMETRY_VERSION,
                        canonical(asdict(drawing)),
                        reason,
                        now,
                        actor,
                    ),
                )
                for kind, data in outputs.items():
                    filename = f"{stem}.{kind}"
                    key = str((destination / filename).relative_to(self.objects))
                    # Verify persisted bytes rather than assuming writes succeeded.
                    if (destination / filename).read_bytes() != data:
                        raise WorkflowError(
                            "stored artifact differs from generated bytes"
                        )
                    db.execute(
                        "INSERT INTO frozen_plate_artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            str(uuid4()),
                            revision_id,
                            kind,
                            key,
                            filename,
                            digest(data),
                            len(data),
                            GENERATOR_VERSION,
                            now,
                        ),
                    )
                db.execute(
                    "UPDATE frozen_plates SET current_revision=?,lifecycle='READY_FOR_CUSTOMER_CONFIRMATION' WHERE id=?",
                    (revision_id, plate_id),
                )
            committed = True
        finally:
            if not committed and destination.exists():
                # If commit succeeded immediately before an interruption, preserve
                # the objects. On an unavailable DB, also leave safe orphan data.
                with self.connect() as check:
                    exists = check.execute(
                        "SELECT 1 FROM frozen_plate_revisions WHERE id=?",
                        (revision_id,),
                    ).fetchone()
                if not exists:
                    self._remove_uncommitted_objects(destination)
                    shutil.rmtree(destination)
        return self.revision(revision_id)

    def _publish_objects(self, destination):
        """Storage hook: local bytes are already durably published."""

    def _remove_uncommitted_objects(self, destination):
        """Storage hook: only called after absence of DB metadata is confirmed."""

    def _read_object(self, key):
        path = (self.objects / key).resolve()
        if self.objects not in path.parents:
            raise WorkflowError("invalid private object key")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise WorkflowError("artifact unavailable") from exc

    def _verified(self, db, revision_id):
        revision = self._one(
            db, "SELECT * FROM frozen_plate_revisions WHERE id=?", (revision_id,)
        )
        if (
            digest(revision["spec_json"]) != revision["spec_sha256"]
            or digest(revision["source_json"]) != revision["source_sha256"]
        ):
            raise WorkflowError("frozen specification integrity failure")
        artifacts = {
            r["kind"]: dict(r)
            for r in db.execute(
                "SELECT * FROM frozen_plate_artifacts WHERE revision_id=?",
                (revision_id,),
            )
        }
        if set(artifacts) != {"pdf", "dxf", "json"}:
            raise WorkflowError("incomplete frozen artifacts")
        contents = {}
        for kind, artifact in artifacts.items():
            content = self._read_object(artifact["object_key"])
            if (
                digest(content) != artifact["sha256"]
                or len(content) != artifact["size"]
            ):
                raise WorkflowError("artifact integrity failure")
            contents[kind] = content
        return revision, artifacts, contents

    def _context(self, db, revision):
        plate = self._one(
            db, "SELECT * FROM frozen_plates WHERE id=?", (revision["plate_id"],)
        )
        spec = json.loads(revision["spec_json"])
        pdf = self._one(
            db,
            "SELECT * FROM frozen_plate_artifacts WHERE revision_id=? AND kind='pdf'",
            (revision["id"],),
        )
        return dict(
            order_id=plate["order_id"],
            line_id=plate["line_id"],
            drawing="OP-" + spec["part_identifier"],
            revision=f'R{revision["number"]}',
            quantity=spec["quantity"],
            filename=pdf["filename"],
        )

    def create_delivery(self, revision_id, *, base_url="http://127.0.0.1:8765"):
        # Only the local demonstrator origin is allowed. There is no send operation.
        if base_url != self.delivery_origin:
            raise WorkflowError("prototype delivery must remain local")
        with self.transaction() as db:
            revision, artifacts, contents = self._verified(db, revision_id)
            plate = self._one(
                db, "SELECT * FROM frozen_plates WHERE id=?", (revision["plate_id"],)
            )
            if (
                plate["current_revision"] != revision_id
                or plate["lifecycle"] != "READY_FOR_CUSTOMER_CONFIRMATION"
            ):
                raise WorkflowError("revision not eligible for confirmation")
            token = self.signer.dumps({"nonce": secrets.token_urlsafe(32)})
            fingerprint = digest(token)
            pdf = artifacts["pdf"]
            db.execute(
                "INSERT INTO frozen_plate_tokens(fingerprint,revision_id,pdf_id,pdf_sha256,spec_sha256,customer_id,order_id,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    fingerprint,
                    revision_id,
                    pdf["id"],
                    pdf["sha256"],
                    revision["spec_sha256"],
                    plate["customer_id"],
                    plate["order_id"],
                    self.now(),
                    self.clock() + self.ttl_seconds,
                ),
            )
            context = self._context(db, revision)
            mime = mime_email(context, base_url + "/approve/" + token, contents["pdf"])
            delivery_id = str(uuid4())
            db.execute(
                "INSERT INTO frozen_plate_deliveries(id,revision_id,pdf_id,token_fingerprint,recipient_id,generated_at,template_version,state,mime_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    delivery_id,
                    revision_id,
                    pdf["id"],
                    fingerprint,
                    plate["customer_id"],
                    self.now(),
                    TEMPLATE_VERSION,
                    "LOCAL_RENDERED",
                    digest(mime),
                ),
            )
        # Raw bearer material is returned only for delivery; never persisted in DB/audit.
        return dict(id=delivery_id, token=token, mime=mime, context=context)

    def _resolve(self, db, token, customer_id):
        try:
            payload = self.signer.loads(token)
            if not isinstance(payload, dict) or set(payload) != {"nonce"}:
                raise WorkflowError("invalid")
        except BadSignature as exc:
            raise WorkflowError("invalid") from exc
        row = self._one(
            db,
            "SELECT * FROM frozen_plate_tokens WHERE fingerprint=?",
            (digest(token),),
        )
        if not secrets.compare_digest(row["customer_id"], customer_id):
            raise WorkflowError("invalid")
        if (
            row["expires_at"] <= self.clock()
            or db.execute(
                "SELECT 1 FROM frozen_plate_revocations WHERE fingerprint=?",
                (row["fingerprint"],),
            ).fetchone()
        ):
            raise WorkflowError("invalid")
        revision, artifacts, contents = self._verified(db, row["revision_id"])
        plate = self._one(
            db, "SELECT * FROM frozen_plates WHERE id=?", (revision["plate_id"],)
        )
        if (
            row["pdf_id"] != artifacts["pdf"]["id"]
            or row["pdf_sha256"] != artifacts["pdf"]["sha256"]
            or row["spec_sha256"] != revision["spec_sha256"]
            or row["order_id"] != plate["order_id"]
            or row["customer_id"] != plate["customer_id"]
        ):
            raise WorkflowError("invalid")
        approval = db.execute(
            "SELECT * FROM frozen_plate_approvals WHERE revision_id=?",
            (revision["id"],),
        ).fetchone()
        return (
            row,
            revision,
            plate,
            artifacts,
            contents,
            dict(approval) if approval else None,
        )

    def inspect_token(self, token, customer_id):
        # A read transaction keeps current-revision and approval reads consistent.
        with self.connect() as db:
            db.execute("BEGIN")
            _, revision, plate, _, _, approval = self._resolve(db, token, customer_id)
            historical = plate["current_revision"] != revision["id"]
            return dict(
                state=(
                    "approved"
                    if approval
                    else ("superseded" if historical else "pending")
                ),
                context=self._context(db, revision),
                approval=approval,
                historical=historical,
            )

    def approve(self, token, customer_id):
        with self.transaction() as db:
            row, revision, plate, _, _, approval = self._resolve(db, token, customer_id)
            if not approval:
                if plate["current_revision"] != revision["id"]:
                    raise WorkflowError("superseded")
                if plate["lifecycle"] != "READY_FOR_CUSTOMER_CONFIRMATION":
                    raise WorkflowError("invalid transition")
                audit = canonical(
                    {
                        "mechanism": "authenticated-email-preview-post-v1",
                        "from": "READY_FOR_CUSTOMER_CONFIRMATION",
                        "to": "CUSTOMER_APPROVED",
                        "plate_id": plate["id"],
                        "revision_number": revision["number"],
                    }
                )
                db.execute(
                    "INSERT INTO frozen_plate_approvals VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        revision["id"],
                        row["pdf_id"],
                        row["fingerprint"],
                        row["pdf_sha256"],
                        row["spec_sha256"],
                        customer_id,
                        plate["order_id"],
                        self.now(),
                        "CUSTOMER_APPROVED",
                        audit,
                    ),
                )
                db.execute(
                    "UPDATE frozen_plates SET lifecycle='CUSTOMER_APPROVED' WHERE id=?",
                    (plate["id"],),
                )
        return self.inspect_token(token, customer_id)

    def customer_pdf(self, token, customer_id):
        with self.connect() as db:
            db.execute("BEGIN")
            _, _, _, artifacts, contents, _ = self._resolve(db, token, customer_id)
            return artifacts["pdf"]["filename"], contents["pdf"]

    def revoke(self, token, *, actor, reason):
        with self.transaction() as db:
            db.execute(
                "INSERT INTO frozen_plate_revocations VALUES (?,?,?,?)",
                (digest(token), self.now(), reason, actor),
            )

    def select_source(self, revision_id, route, *, actor):
        if route not in ROUTES or not actor.strip():
            raise WorkflowError("invalid source or actor")
        with self.transaction() as db:
            revision, artifacts, _ = self._verified(db, revision_id)
            plate = self._one(
                db, "SELECT * FROM frozen_plates WHERE id=?", (revision["plate_id"],)
            )
            if plate["current_revision"] != revision_id or plate["lifecycle"] not in (
                "CUSTOMER_APPROVED",
                "READY_FOR_RELEASE",
            ):
                raise WorkflowError("only current approved revision may be sourced")
            approval = self._one(
                db,
                "SELECT * FROM frozen_plate_approvals WHERE revision_id=?",
                (revision_id,),
            )
            if (
                approval["pdf_sha256"] != artifacts["pdf"]["sha256"]
                or approval["spec_sha256"] != revision["spec_sha256"]
            ):
                raise WorkflowError("approval integrity failure")
            db.execute(
                "INSERT OR IGNORE INTO frozen_plate_sourcing(id,revision_id,dxf_id,route,state,selected_at,selected_by) VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    revision_id,
                    artifacts["dxf"]["id"],
                    route,
                    "LOCAL_SELECTION_ONLY",
                    self.now(),
                    actor,
                ),
            )
            db.execute(
                "UPDATE frozen_plates SET lifecycle='READY_FOR_RELEASE' WHERE id=?",
                (plate["id"],),
            )
            result = self._one(
                db,
                "SELECT * FROM frozen_plate_sourcing WHERE revision_id=? AND route=?",
                (revision_id, route),
            )
            result.update(
                dxf_sha256=artifacts["dxf"]["sha256"],
                pdf_id=artifacts["pdf"]["id"],
                pdf_sha256=artifacts["pdf"]["sha256"],
                spec_sha256=revision["spec_sha256"],
                approved_at=approval["approved_at"],
                plate_id=plate["id"],
                released=False,
            )
            return result
