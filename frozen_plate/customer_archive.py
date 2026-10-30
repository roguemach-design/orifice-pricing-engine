"""Permanent authenticated PDF archive using existing ownership and approval bindings.

No confirmation tokens, writes, regeneration, manufacturing artifacts or signed URLs.
Only the selected PDF is downloaded; parent hashes remain independently verified.
"""

import json
from .repository import WorkflowError, digest

SPEC_KEYS = {
    "finished_od",
    "finished_bore_diameter",
    "handle_width",
    "centerline_to_handle_end",
    "material",
    "thickness",
    "bore_tolerance",
    "chamfer",
    "chamfer_width",
    "chamfer_angle_degrees",
    "chamfer_side",
    "flow_orientation",
    "chamfer_width_definition",
    "marking",
    "quantity",
    "handle_hole_enabled",
    "handle_hole_diameter",
    "handle_hole_center_from_handle_end",
}


def parent(repo, db, revision_id):
    revision = repo._one(
        db, "SELECT * FROM frozen_plate_revisions WHERE id=?", (revision_id,)
    )
    if (
        digest(revision["spec_json"]) != revision["spec_sha256"]
        or digest(revision["source_json"]) != revision["source_sha256"]
    ):
        raise WorkflowError("frozen specification integrity failure")
    return revision


def binding(repo, db, revision, plate):
    artifact = db.execute(
        "SELECT * FROM frozen_plate_artifacts WHERE revision_id=? AND kind='pdf'",
        (revision["id"],),
    ).fetchone()
    approval = db.execute(
        "SELECT * FROM frozen_plate_approvals WHERE revision_id=?", (revision["id"],)
    ).fetchone()
    if approval:
        if not artifact or any(
            (
                approval["pdf_id"] != artifact["id"],
                approval["pdf_sha256"] != artifact["sha256"],
                approval["spec_sha256"] != revision["spec_sha256"],
                approval["customer_id"] != plate["customer_id"],
                approval["order_id"] != plate["order_id"],
                approval["status"] != "CUSTOMER_APPROVED",
            )
        ):
            raise WorkflowError("approval integrity failure")
    return artifact, approval


def inventory(repo, order_id, customer_id):
    with repo.connect() as db:
        db.execute("BEGIN")
        plates = db.execute(
            "SELECT id,line_id,current_revision,lifecycle FROM frozen_plates WHERE order_id=? AND customer_id=? ORDER BY line_id",
            (order_id, customer_id),
        ).fetchall()
        result = []
        for p in plates:
            plate = repo._one(db, "SELECT * FROM frozen_plates WHERE id=?", (p["id"],))
            revisions = db.execute(
                "SELECT id FROM frozen_plate_revisions WHERE plate_id=? ORDER BY number DESC",
                (p["id"],),
            ).fetchall()
            history = []
            for row in revisions:
                revision = parent(repo, db, row["id"])
                artifact, approval = binding(repo, db, revision, plate)
                spec = json.loads(revision["spec_json"])
                history.append(
                    dict(
                        id=revision["id"],
                        number=revision["number"],
                        current=revision["id"] == plate["current_revision"],
                        created_at=revision["created_at"],
                        approved=bool(approval),
                        approved_at=approval["approved_at"] if approval else None,
                        pdf_available=bool(artifact and approval),
                        pdf_sha256=(
                            artifact["sha256"] if artifact and approval else None
                        ),
                        pdf_size=artifact["size"] if artifact and approval else None,
                        filename=f"drawing-{order_id}-{p['line_id']}-R{revision['number']}.pdf",
                        specifications={
                            k: v for k, v in spec.items() if k in SPEC_KEYS
                        },
                    )
                )
            result.append(
                dict(
                    id=p["id"],
                    line_id=p["line_id"],
                    current_revision=p["current_revision"],
                    lifecycle=p["lifecycle"],
                    revisions=history,
                )
            )
        return result


def pdf(repo, order_id, revision_id, customer_id):
    with repo.connect() as db:
        db.execute("BEGIN")
        # Authorize metadata before any private object read.
        row = db.execute(
            "SELECT r.id FROM frozen_plate_revisions r JOIN frozen_plates p ON p.id=r.plate_id WHERE r.id=? AND p.order_id=? AND p.customer_id=?",
            (revision_id, order_id, customer_id),
        ).fetchone()
        if not row:
            raise LookupError("Not found")
        revision = parent(repo, db, revision_id)
        plate = repo._one(
            db, "SELECT * FROM frozen_plates WHERE id=?", (revision["plate_id"],)
        )
        artifact, approval = binding(repo, db, revision, plate)
        if not approval or not artifact:
            raise WorkflowError("approved PDF unavailable")
        content = repo._read_object(artifact["object_key"])
        if digest(content) != artifact["sha256"] or len(content) != artifact["size"]:
            raise WorkflowError("artifact integrity failure")
        return content, artifact, revision
