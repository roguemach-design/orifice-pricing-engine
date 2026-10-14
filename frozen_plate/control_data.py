"""Bounded read model. Metadata only; no artifact reads or workflow mutations."""

from datetime import datetime, timezone
import json
from .repository import digest

SCOPE = "Completed orders within the latest 200 order records; current Frozen Plate lines for those orders"


def approved(revision, approvals):
    pdf = revision.get("artifacts", {}).get("pdf", {})
    return bool(
        pdf.get("sha256")
        and any(
            a.get("pdf_sha256") == pdf["sha256"]
            and a.get("spec_sha256") == revision.get("spec_sha256")
            for a in approvals
        )
    )


def bounded_summary(orders, repo):
    orders = [dict(o) for o in orders[:200] if o["status"] == "completed"]
    ids = [o["id"] for o in orders]
    lines = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        # One bounded SQL statement and one connection. Approval counts are evidence,
        # not byte verification; orphan inventory is deliberately a separate scope.
        with repo.connect() as db:
            rows = db.execute(
                f"""
                SELECT p.id,p.order_id,p.line_id,p.lifecycle,p.current_revision,
                  r.number,r.spec_json,r.spec_sha256,
                  a.pdf_sha256 AS approval_pdf,a.spec_sha256 AS approval_spec,
                  f.sha256 AS pdf_sha,
                  (SELECT COUNT(*) FROM frozen_plate_sourcing s WHERE s.revision_id=r.id) AS sourcing_count
                FROM frozen_plates p
                LEFT JOIN frozen_plate_revisions r ON r.id=p.current_revision
                LEFT JOIN frozen_plate_approvals a ON a.revision_id=r.id
                LEFT JOIN frozen_plate_artifacts f ON f.revision_id=r.id AND f.kind='pdf'
                WHERE p.order_id IN ({placeholders}) ORDER BY p.order_id,p.line_id
            """,
                tuple(ids),
            )
            for raw in rows:
                row = dict(raw)
                try:
                    spec = json.loads(row["spec_json"])
                    if digest(row["spec_json"]) != row["spec_sha256"]:
                        raise ValueError("metadata mismatch")
                except (ValueError, TypeError):
                    spec = {}
                lines.append(
                    {
                        "plate_id": row["id"],
                        "order_id": row["order_id"],
                        "line_id": row["line_id"],
                        "revision_id": row["current_revision"],
                        "revision_number": row["number"],
                        "material": spec.get("material"),
                        "thickness": spec.get("thickness"),
                        "quantity": spec.get("quantity"),
                        "metadata_available": bool(spec),
                        "approved": bool(
                            spec
                            and row["pdf_sha"]
                            and row["approval_pdf"] == row["pdf_sha"]
                            and row["approval_spec"] == row["spec_sha256"]
                        ),
                        "sourcing_count": row["sourcing_count"],
                        "lifecycle": row["lifecycle"],
                    }
                )
    for order in orders:
        order["lines"] = [line for line in lines if line["order_id"] == order["id"]]
    return {
        "orders": orders,
        "scope": SCOPE,
        "partial": True,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "awaiting_approval": sum(
                bool(l["revision_id"]) and l["metadata_available"] and not l["approved"]
                for l in lines
            ),
            "approved": sum(l["approved"] for l in lines),
            "ready_for_release": sum(
                l["approved"] and l["lifecycle"] == "READY_FOR_RELEASE" for l in lines
            ),
            "sourcing_recorded": sum(bool(l["sourcing_count"]) for l in lines),
            "record_unavailable": sum(not o["lines"] for o in orders)
            + sum(not l["metadata_available"] for l in lines),
            "hold": None,
            "email_reconciliation": None,
        },
    }
