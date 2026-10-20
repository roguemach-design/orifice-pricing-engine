"""Server-owned completed-order snapshots; safe to retry after partial failure."""

from hashlib import sha256
from section_geometry import build_section_geometry
from .order_adapter import specification_from_order
from .repository import WorkflowError, canonical


def freeze_line(
    repo,
    snapshot,
    line_index,
    part_identifier,
    *,
    expected_current=None,
    reason=None,
    revision=False,
):
    spec, source = specification_from_order(
        snapshot, line_index=line_index, part_identifier=part_identifier
    )
    if reason is None:
        reason = "Completed production order" if getattr(repo, "order_actor", None) == "completed-order" else "Completed staging order"
    section = build_section_geometry(spec)
    if "HOLD" in section.status:
        raise WorkflowError("HOLD: explicit complete chamfer configuration required")
    plate_id = repo.ensure_order_plate(
        order_id=snapshot["id"],
        line_id=f"line-{line_index + 1}",
        configuration_id=sha256(canonical(source).encode()).hexdigest()[:40],
        customer_id=snapshot["customer_id"],
        actor=getattr(repo, "order_actor", "staging-order"),
    )
    plate = repo.plate(plate_id)
    if not revision and plate["current_revision"]:
        current = repo.revision(plate["current_revision"])
        if current["source_sha256"] != sha256(canonical(source).encode()).hexdigest():
            raise WorkflowError("HOLD: changed order requires explicit revision review")
        return current
    try:
        return repo.create_revision(
            plate_id,
            spec,
            expected_current=expected_current,
            reason=reason,
            actor=getattr(repo, "order_actor", "staging-order"),
            source_snapshot=source,
        )
    except WorkflowError:
        # Two completion workers may race after creating the stable plate identity.
        # Only the identical initial snapshot may be reused; explicit revisions fail.
        if revision:
            raise
        current_id = repo.plate(plate_id)["current_revision"]
        if not current_id:
            raise
        current = repo.revision(current_id)
        if current["source_sha256"] != sha256(canonical(source).encode()).hexdigest():
            raise
        return current


def complete_order(repo, snapshot):
    items = snapshot["quote_payload"].get("cart_items")
    count = len(items) if items is not None else 1
    if count < 1:
        raise WorkflowError("HOLD: empty completed order")
    result = []
    for index in range(count):
        part = getattr(repo, "part_prefix", "STG-") + sha256(snapshot["id"].encode()).hexdigest()[:16] + f"-{index+1}"
        try:
            rev = freeze_line(repo, snapshot, index, part)
        except (WorkflowError, ValueError, KeyError):
            result.append({"line_id": f"line-{index+1}", "state": "HOLD"})
            continue
        with repo.connect() as db:
            captured = db.execute(
                "SELECT id,mime_sha256 FROM frozen_plate_deliveries WHERE revision_id=? ORDER BY generated_at DESC",
                (rev["id"],),
            ).fetchone()
        if captured and hasattr(repo, "storage"):
            try:
                content = repo.storage.get("confirmation/" + captured["id"] + ".eml")
                captured = sha256(content).hexdigest() == captured["mime_sha256"]
            except WorkflowError:
                captured = False
        if not captured:
            repo.create_delivery(rev["id"])
        result.append(
            {
                "line_id": f"line-{index+1}",
                "state": "FROZEN",
                "plate_id": rev["plate_id"],
                "revision_id": rev["id"],
            }
        )
    return result
