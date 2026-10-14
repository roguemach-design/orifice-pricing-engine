"""Owner-only organizational archive. No payment or manufacturing mutations."""

from datetime import datetime, timezone
import re
from sqlalchemy import or_
from fastapi import HTTPException


def filter_orders(query, model, *, archive_view="Active", search=None):
    if archive_view not in ("Active", "Archived", "All"):
        raise ValueError("Invalid archive view")
    if archive_view == "Active":
        query = query.filter(model.owner_archived_at.is_(None))
    elif archive_view == "Archived":
        query = query.filter(model.owner_archived_at.is_not(None))
    if search and search.strip():
        term = search.strip()
        pattern = (
            "%"
            + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        predicates = [
            column.ilike(pattern, escape="\\")
            for column in (
                model.id,
                model.customer_email,
                model.customer_id,
                model.shipping_name,
                model.stripe_session_id,
                model.stripe_payment_intent,
            )
        ]
        match = re.fullmatch(r"(?:OP-?)?([0-9]+)", term, flags=re.I)
        if match and len(match[1]) <= 18:
            predicates.append(model.order_number == int(match[1]))
        query = query.filter(or_(*predicates))
    return query


def set_archived(db, model, order_id, archived):
    order = db.query(model).filter(model.id == order_id).with_for_update().first()
    if order is None:
        raise HTTPException(404, "Order not found")
    # Completed orders and explicitly identified sandbox orders only.
    is_test = bool(
        re.fullmatch(r"cs_test_[A-Za-z0-9_]+", order.stripe_session_id or "")
    )
    if order.status != "completed" and not is_test:
        raise HTTPException(409, "Only completed or TEST orders can be archived")
    if archived and order.owner_archived_at is None:
        order.owner_archived_at = datetime.now(timezone.utc)
    elif not archived:
        order.owner_archived_at = None
    # SQLAlchemy writes this one dirty field only. All other order fields and
    # every Frozen Plate table/object remain untouched.
    db.commit()
    db.refresh(order)
    return {
        "id": order.id,
        "owner_archived_at": (
            order.owner_archived_at.isoformat() if order.owner_archived_at else None
        ),
    }
