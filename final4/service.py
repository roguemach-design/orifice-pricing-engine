"""Append-only derived bundles, tied to exact Frozen Plate identity and verified bytes.

Schema installation is explicit and isolated; never called by the production runtime.
Object publication uses the existing private storage hooks. No original artifact mutation.
"""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import os
from uuid import uuid4
from frozen_plate.repository import WorkflowError, canonical, digest, identifier
from plate_geometry import PlateSpec, canonical_specification
from packaging_generator.generator import generate as packaging, Configuration
from haas_generator.contract import construct, ReviewedRecord
from haas_generator.engineering import engineering_bundle, Parameters

SCHEMA = """
CREATE TABLE IF NOT EXISTS manufacturing_bundles (
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES frozen_plate_revisions(id),
 family TEXT NOT NULL CHECK(family IN ('HAAS','PACKAGING')),
 parent_json TEXT NOT NULL, input_json TEXT NOT NULL, input_sha256 TEXT NOT NULL,
 generator_version TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 manifest_json TEXT NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manufacturing_bundle_files (
 bundle_id TEXT NOT NULL REFERENCES manufacturing_bundles(id), name TEXT NOT NULL,
 filename TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL, PRIMARY KEY(bundle_id,name)
);
CREATE TABLE IF NOT EXISTS manufacturing_evidence (
 id TEXT PRIMARY KEY, bundle_id TEXT NOT NULL REFERENCES manufacturing_bundles(id),
 gate TEXT NOT NULL CHECK(gate IN ('ENGINEERING_REVIEW','SIMULATION_VERIFIED')),
 bundle_manifest_sha256 TEXT NOT NULL, reference TEXT NOT NULL, actor TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(bundle_id,gate)
);
"""


class DerivedService:
    def __init__(
        self, repo, *, machine_profile, packaging_config, machining_parameters
    ):
        self.repo = repo
        self.profile = machine_profile
        self.packaging_config = packaging_config
        self.parameters = machining_parameters

    def initialize_isolated_sqlite(self):
        # An explicit installer, NOT an automatic production migration.
        if type(self.repo).__module__ != "frozen_plate.repository":
            raise WorkflowError(
                "isolated SQLite installer only; reviewed migration required"
            )
        with self.repo.connect() as db:
            db.executescript(SCHEMA)
            from .retry import SCHEMA as RETRY_SCHEMA
            db.executescript(RETRY_SCHEMA)
            for table in (
                "manufacturing_bundles",
                "manufacturing_bundle_files",
                "manufacturing_evidence",
            ):
                for op in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS immutable_{op}_{table} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable derived artifact'); END"
                    )

    def _parent(self, db, association, *, require_current):
        if set(association) != {
            "order_id",
            "line_id",
            "plate_id",
            "revision_id",
            "spec_sha256",
            "source_sha256",
        }:
            raise WorkflowError("complete exact parent association required")
        r, a, contents = self.repo._verified(db, association["revision_id"])
        if require_current and json.loads(r["source_json"]).get("_payment", {}).get("mode") == "owner_test":
            raise WorkflowError("TEST / NOT A REAL SALE: manufacturing output is prohibited")
        p = self.repo._one(
            db, "SELECT * FROM frozen_plates WHERE id=?", (r["plate_id"],)
        )
        actual = dict(
            order_id=p["order_id"],
            line_id=p["line_id"],
            plate_id=p["id"],
            revision_id=r["id"],
            spec_sha256=r["spec_sha256"],
            source_sha256=r["source_sha256"],
        )
        if actual != association:
            raise WorkflowError("parent identity/hash mismatch")
        current = p["current_revision"] == r["id"]
        row = db.execute(
            "SELECT * FROM frozen_plate_approvals WHERE revision_id=?", (r["id"],)
        ).fetchone()
        approved = bool(
            row
            and row["spec_sha256"] == r["spec_sha256"]
            and row["pdf_sha256"] == a["pdf"]["sha256"]
            and row["order_id"] == p["order_id"]
            and row["customer_id"] == p["customer_id"]
        )
        if require_current and (not current or not approved):
            raise WorkflowError("current customer-approved exact revision required")
        return r, PlateSpec(**json.loads(r["spec_json"])), current, approved

    def create(self, family, association, *, actor, reviewed_record=None):
        if family not in ("HAAS", "PACKAGING") or not actor:
            raise WorkflowError("valid family/server actor required")
        repo = self.repo
        # Lock parent/current pointer through generation+publication. Supersession cannot race.
        with repo.transaction() as db:
            r, spec, _, _ = self._parent(db, association, require_current=True)
            parent = {**association, "revision": f"R{r['number']}"}
            if family == "HAAS":
                record_data = dict(reviewed_record or {})
                setup_context = record_data.pop("setup_context", None)
                record = construct(ReviewedRecord, record_data)
                if spec.chamfer and (
                    not isinstance(setup_context, dict)
                    or setup_context.get("top_face_side") != spec.chamfer_side
                ):
                    raise WorkflowError(
                        "explicit physical top-face orientation must match chamfer side"
                    )
                expected = (
                    spec.finished_bore_diameter,
                    spec.bore_tolerance,
                    spec.thickness,
                    spec.material,
                    spec.chamfer_width if spec.chamfer else 0,
                )
                if spec.chamfer is None or (
                    spec.chamfer
                    and (
                        spec.chamfer_angle_degrees != 45
                        or spec.chamfer_width_definition != "radial-angle-from-face"
                        or spec.chamfer_side not in ("upstream", "downstream")
                    )
                ):
                    raise WorkflowError(
                        "reviewed supported chamfer orientation/geometry required"
                    )
                actual = (
                    record.finished_bore,
                    record.bore_tolerance,
                    record.thickness,
                    record.material,
                    record.top_chamfer_width,
                )
                if actual != expected or (
                    record.job_id,
                    record.part_id,
                    record.drawing_revision,
                    record.source_sha256,
                ) != (
                    association["order_id"],
                    spec.part_identifier,
                    parent["revision"],
                    association["spec_sha256"],
                ):
                    raise WorkflowError(
                        "machining record incompatible with frozen specification"
                    )
                files = {
                    k: v.encode("ascii")
                    for k, v in engineering_bundle(
                        record,
                        self.profile,
                        self.parameters,
                        parent,
                        setup_context=setup_context,
                    ).items()
                }
                inputs = {
                    "record": asdict(record),
                    "setup_context": setup_context,
                    "profile": asdict(self.profile),
                    "parameters": asdict(self.parameters),
                }
            else:
                if reviewed_record is not None:
                    raise WorkflowError("unexpected packaging machining record")
                files = packaging(spec, self.packaging_config, parent)
                inputs = {
                    "spec": canonical_specification(spec),
                    "configuration": asdict(self.packaging_config),
                }
            bundle_id = self._store(db, family, association, r, files, inputs, actor)
        return self.metadata(bundle_id)

    def _store(self, db, family, association, r, files, inputs, actor, *, staging=None):
        manifest = json.loads(files["manifest.json"])
        repo = self.repo
        parent = {**association, "revision": f"R{r['number']}"}
        if staging:
            manifest.update(staging)
            files = {
                **files,
                "manifest.json": (
                    json.dumps(manifest, sort_keys=True, indent=2) + "\n"
                ).encode("ascii"),
            }
        bundle_id = str(uuid4())
        # Unique private object namespace; stored once and never regenerated on download.
        destination = repo.objects / "derived" / bundle_id
        destination.mkdir(parents=True, mode=0o700)
        for name, data in files.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
                raise WorkflowError("unsafe artifact name")
            with (destination / name).open("xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            (destination / name).chmod(0o400)
        for directory in (destination, destination.parent, repo.objects):
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        repo._publish_objects(destination)
        # Fail closed if persisted bytes differ, including remote storage.
        file_rows = []
        slug = (
            ("HAAS-STAGED" if staging else "HAAS-REVIEW")
            if family == "HAAS"
            else "PACKAGING-PROTOTYPE"
        )
        if staging and staging.get("mode") == "OWNER_TEST_ENGINEERING":
            slug = "TEST-ENGINEERING-" + slug
        stem = f"OP-{slug}-{identifier(association['order_id'])}-{identifier(association['line_id'])}-R{r['number']}-{bundle_id[:8]}"
        for name, data in files.items():
            key = str((destination / name).relative_to(repo.objects))
            if repo._read_object(key) != data:
                raise WorkflowError("derived storage verification failure")
            filename = f"{stem}-{name}"
            file_rows.append((bundle_id, name, filename, key, len(data), digest(data)))
        db.execute(
            "INSERT INTO manufacturing_bundles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                bundle_id,
                r["id"],
                family,
                canonical(parent),
                canonical(inputs),
                digest(canonical(inputs)),
                manifest["generator_version"],
                repo.now(),
                actor,
                canonical(manifest),
                digest(canonical(manifest)),
            ),
        )
        for row in file_rows:
            db.execute(
                "INSERT INTO manufacturing_bundle_files VALUES (?,?,?,?,?,?)", row
            )
        return bundle_id

    def _bundle(self, db, bundle_id):
        b = self.repo._one(
            db, "SELECT * FROM manufacturing_bundles WHERE id=?", (bundle_id,)
        )
        if (
            digest(b["input_json"]) != b["input_sha256"]
            or digest(b["manifest_json"]) != b["manifest_sha256"]
        ):
            raise WorkflowError("derived metadata integrity failure")
        parent = json.loads(b["parent_json"])
        manifest = json.loads(b["manifest_json"])
        if parent != manifest["parent"] or parent["revision_id"] != b["revision_id"]:
            raise WorkflowError("derived parent metadata integrity failure")
        parent.pop("revision")
        r, spec, current, approved = self._parent(db, parent, require_current=False)
        if json.loads(b["parent_json"])["revision"] != f"R{r['number']}":
            raise WorkflowError("derived revision label mismatch")
        return b, current, approved

    def metadata(self, bundle_id):
        with self.repo.connect() as db:
            db.execute("BEGIN")
            b, current, approved = self._bundle(db, bundle_id)
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT name,filename,size,sha256 FROM manufacturing_bundle_files WHERE bundle_id=? ORDER BY name",
                    (bundle_id,),
                )
            ]
            events = [
                dict(r)
                for r in db.execute(
                    "SELECT gate,reference,actor,created_at FROM manufacturing_evidence WHERE bundle_id=?",
                    (bundle_id,),
                )
            ]
            gates = {e["gate"] for e in events}
            return dict(
                id=b["id"],
                family=b["family"],
                parent=json.loads(b["parent_json"]),
                generator_version=b["generator_version"],
                input_sha256=b["input_sha256"],
                manifest_sha256=b["manifest_sha256"],
                created_at=b["created_at"],
                created_by=b["created_by"],
                files=rows,
                statuses=dict(
                    file_exists=True,
                    bytes_verified="ON_DOWNLOAD",
                    parent_current=current,
                    customer_approved=approved,
                    engineering_review_completed="ENGINEERING_REVIEW" in gates,
                    simulation_verified="SIMULATION_VERIFIED" in gates,
                    physical_validation_completed=False,
                    manufacturing_release_approved=False,
                    release_eligible=False,
                ),
                state=(
                    "SIMULATION VERIFIED"
                    if "SIMULATION_VERIFIED" in gates
                    else (
                        "SETUP VERIFICATION REQUIRED"
                        if b["family"] == "HAAS"
                        and self._stored_readiness(db, b)["holds"]
                        else "ENGINEERING REVIEW"
                    )
                ),
                evidence=events,
                staging={
                    k: json.loads(b["manifest_json"]).get(k)
                    for k in (
                        "mode",
                        "profile_sha256",
                        "staging_key",
                        "machine_profile",
                        "fixture_profile",
                        "input_source",
                    )
                },
            )

    def _stored_readiness(self, db, b):
        row = self.repo._one(
            db,
            "SELECT * FROM manufacturing_bundle_files WHERE bundle_id=? AND name=?",
            (b["id"], "readiness.json"),
        )
        raw = self.repo._read_object(row["object_key"])
        if len(raw) != row["size"] or digest(raw) != row["sha256"]:
            raise WorkflowError("derived artifact integrity failure")
        return json.loads(raw)

    def list(self, association):
        with self.repo.connect() as db:
            db.execute("BEGIN")
            self._parent(db, association, require_current=False)
            ids = [
                r["id"]
                for r in db.execute(
                    "SELECT id FROM manufacturing_bundles WHERE revision_id=? ORDER BY created_at,id",
                    (association["revision_id"],),
                )
            ]
        return [self.metadata(i) for i in ids]

    def download(self, bundle_id, name, *, historical=False):
        with self.repo.connect() as db:
            db.execute("BEGIN")
            self._bundle(
                db, bundle_id
            )  # Historical downloads allowed; release remains false.
            a = self.repo._one(
                db,
                "SELECT * FROM manufacturing_bundle_files WHERE bundle_id=? AND name=?",
                (bundle_id, name),
            )
            b, current, approved = self._bundle(db, bundle_id)
            manifest = json.loads(b["manifest_json"])
            if (
                manifest.get("mode") in ("AUTOMATIC", "OWNER_TEST_ENGINEERING")
                and name in ("program.NC", "packaging.dxf")
                and (not approved or (not current and not historical))
            ):
                raise WorkflowError(
                    "current approved derivative required; historical audit must be explicit"
                )
            raw = self.repo._read_object(a["object_key"])
            manifest = json.loads(b["manifest_json"])
            if name != "manifest.json" and manifest["files"].get(name) != {
                "size": a["size"],
                "sha256": a["sha256"],
            }:
                raise WorkflowError("derived file metadata mismatch")
            if (
                name == "manifest.json"
                and canonical(json.loads(raw)) != b["manifest_json"]
            ):
                raise WorkflowError("derived manifest content mismatch")
            if len(raw) != a["size"] or digest(raw) != a["sha256"]:
                raise WorkflowError("derived artifact integrity failure")
            return a["filename"], a["sha256"], raw

    def record_evidence(self, bundle_id, *, gate, reference, actor, manifest_sha256):
        # Trusted adapter method. No physical verification/release endpoint exists.
        if (
            gate not in ("ENGINEERING_REVIEW", "SIMULATION_VERIFIED")
            or not reference.strip()
            or not actor
        ):
            raise WorkflowError("documented allowed verification gate required")
        with self.repo.transaction() as db:
            b, current, approved = self._bundle(db, bundle_id)
            if (
                not current
                or not approved
                or b["created_by"] == actor
                or manifest_sha256 != b["manifest_sha256"]
            ):
                raise WorkflowError("independent exact-bundle verification required")
            if gate == "SIMULATION_VERIFIED":
                if not db.execute(
                    "SELECT 1 FROM manufacturing_evidence WHERE bundle_id=? AND gate='ENGINEERING_REVIEW'",
                    (bundle_id,),
                ).fetchone():
                    raise WorkflowError(
                        "engineering review required before independent simulation evidence"
                    )
                if b["family"] == "HAAS" and self._stored_readiness(db, b)["holds"]:
                    raise WorkflowError(
                        "verified setup profile required before simulation acceptance"
                    )
            db.execute(
                "INSERT INTO manufacturing_evidence VALUES (?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    bundle_id,
                    gate,
                    manifest_sha256,
                    reference,
                    actor,
                    self.repo.now(),
                ),
            )
        return self.metadata(bundle_id)
