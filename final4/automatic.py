"""Idempotent automatic staging in the existing immutable bundle repository."""

from dataclasses import asdict
import json
from frozen_plate.repository import canonical, digest, WorkflowError
from packaging_generator import VERSION as PACKAGING_VERSION
from packaging_generator.generator import generate as packaging
from haas_generator.staging import generate as haas, VERSION as HAAS_VERSION
from haas_generator.engineering import VERSION as ENGINEERING_VERSION, POST_VERSION
from haas_generator import VERSION as CORE_VERSION

ACTOR = "automatic-manufacturing-staging"


class AutomaticStager:
    def __init__(self, service, fixture):
        self.service, self.fixture = service, fixture

    def profiles(self):
        s = self.service
        return {
            "HAAS": digest(
                canonical(
                    dict(
                        machine=asdict(s.profile),
                        fixture=asdict(self.fixture),
                        parameters=asdict(s.parameters),
                        generator=HAAS_VERSION,
                        engineering_version=ENGINEERING_VERSION,
                        post_version=POST_VERSION,
                        core_version=CORE_VERSION,
                    )
                )
            ),
            "PACKAGING": digest(
                canonical(
                    dict(
                        configuration=asdict(s.packaging_config),
                        generator=PACKAGING_VERSION,
                    )
                )
            ),
        }

    def parents(self):
        # Metadata-only discovery. Passive owner views never request staging.
        with self.service.repo.connect() as db:
            return [
                dict(r)
                for r in db.execute("""SELECT p.order_id,p.line_id,p.id AS plate_id,
                r.id AS revision_id,r.spec_sha256,r.source_sha256
                FROM frozen_plates p JOIN frozen_plate_revisions r ON r.id=p.current_revision
                JOIN frozen_plate_approvals a ON a.revision_id=r.id
                JOIN frozen_plate_artifacts f ON f.revision_id=r.id AND f.kind='pdf'
                WHERE a.pdf_sha256=f.sha256 AND a.spec_sha256=r.spec_sha256
                AND a.order_id=p.order_id AND a.customer_id=p.customer_id
                ORDER BY p.id""")
            ]

    def ensure(self, family, association):
        if family not in ("HAAS", "PACKAGING"):
            raise WorkflowError("valid automatic artifact family required")
        s, repo = self.service, self.service.repo
        signature = self.profiles()[family]
        key = digest(canonical(dict(parent=association, profile=signature)))
        with repo.transaction() as db:
            # Lock is shared with approval/supersession and existing bundle writes.
            # Validate the exact CURRENT approved parent even on an idempotent hit.
            row = repo._one(
                db,
                """SELECT p.order_id,p.line_id,p.id AS plate_id,
                r.id AS revision_id,r.spec_sha256,r.source_sha256 FROM frozen_plates p
                JOIN frozen_plate_revisions r ON r.id=p.current_revision
                JOIN frozen_plate_approvals a ON a.revision_id=r.id
                JOIN frozen_plate_artifacts f ON f.revision_id=r.id AND f.kind='pdf'
                WHERE r.id=? AND a.pdf_sha256=f.sha256 AND a.spec_sha256=r.spec_sha256
                AND a.order_id=p.order_id AND a.customer_id=p.customer_id""",
                (association["revision_id"],),
            )
            if dict(row) != association:
                raise WorkflowError("current exact approved parent required")
            for b in db.execute(
                """SELECT id,manifest_json,manifest_sha256 FROM manufacturing_bundles
                    WHERE revision_id=? AND family=? AND created_by=? ORDER BY created_at,id""",
                (association["revision_id"], family, ACTOR),
            ):
                if digest(b["manifest_json"]) != b["manifest_sha256"]:
                    raise WorkflowError("stored staging manifest integrity failure")
                if json.loads(b["manifest_json"]).get("staging_key") == key:
                    return b["id"]
            r, spec, _, _ = s._parent(db, association, require_current=True)
            parent = {**association, "revision": f"R{r['number']}"}
            if family == "HAAS":
                files = haas(spec, s.profile, self.fixture, s.parameters, parent)
                inputs = json.loads(files["inputs.json"])
                refs = dict(
                    machine_profile=dict(
                        revision=self.fixture.machine_profile_revision,
                        profile_id=s.profile.profile_id,
                        sha256=digest(canonical(asdict(s.profile))),
                    ),
                    fixture_profile=dict(
                        revision=self.fixture.fixture_revision,
                        version=self.fixture.version,
                        sha256=digest(canonical(asdict(self.fixture))),
                    ),
                )
            else:
                files = packaging(spec, s.packaging_config, parent)
                inputs = json.loads(files["inputs.json"])
                refs = {}
            return s._store(
                db,
                family,
                association,
                r,
                files,
                inputs,
                ACTOR,
                staging=dict(
                    mode="AUTOMATIC",
                    profile_sha256=signature,
                    staging_key=key,
                    input_source="APPROVED FROZEN PLATE + CONTROLLED PROFILES",
                    **refs,
                ),
            )
