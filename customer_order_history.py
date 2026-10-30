"""Read-only customer projections. No repricing or administrative payloads."""

from sqlalchemy import cast, String
from customer_safety import PRODUCT_FIELDS

PRODUCT_KEYS = {
    *PRODUCT_FIELDS,
    "chamfer_angle_degrees",
    "chamfer_side",
    "flow_orientation",
    "chamfer_width_definition",
}


def product_lines(payload):
    payload = payload if isinstance(payload, dict) else {}
    source = payload.get("cart_items")
    source = source if isinstance(source, list) else [payload] if payload else []
    return [
        {
            "line_id": f"line-{i+1}",
            "specifications": {
                k: v
                for k, v in item.items()
                if k in PRODUCT_KEYS
                and (v is None or isinstance(v, (str, int, float, bool)))
            },
        }
        for i, item in enumerate(source)
        if isinstance(item, dict)
    ]


def summary(order, mode):
    money = lambda value: None if value is None else value / 100
    return dict(
        id=order.id,
        order_number_display=(
            f"OP-{order.order_number:04d}" if order.order_number else None
        ),
        created_at=order.created_at.isoformat() if order.created_at else None,
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
        status=order.status,
        payment_mode=mode,
        amount_total_usd=money(order.amount_total_cents),
        amount_subtotal_usd=money(order.amount_subtotal_cents),
        amount_shipping_usd=money(order.amount_shipping_cents),
        line_count=len(product_lines(order.quote_payload)),
    )


def detail(order, mode):
    return {
        **summary(order, mode),
        "lines": product_lines(order.quote_payload),
        "shipping_service": order.shipping_service,
        "shipping_name": order.shipping_name,
        "shipping_address": {
            k: v
            for k, v in (
                order.shipping_address
                if isinstance(order.shipping_address, dict)
                else {}
            ).items()
            if k in {"line1", "line2", "city", "state", "postal_code", "country"}
            and isinstance(v, str)
        },
    }


def listing(
    db, model, customer_id, mode, *, search="", sort="newest", offset=0, limit=20
):
    query = db.query(model).filter(model.customer_id == customer_id)
    if search:
        term = search.strip().upper().removeprefix("OP-")
        # Search owned order numbers only; no wildcard interpretation or other-customer lookup.
        query = query.filter(
            cast(model.order_number, String) == str(int(term))
            if term.isdigit()
            else model.id == ""
        )
    ordering = {
        "newest": model.created_at.desc(),
        "oldest": model.created_at.asc(),
        "total_high": model.amount_total_cents.desc().nullslast(),
        "total_low": model.amount_total_cents.asc().nullslast(),
    }
    count = query.count()
    rows = query.order_by(ordering[sort], model.id).offset(offset).limit(limit).all()
    return {
        "orders": [summary(o, mode(o)) for o in rows],
        "total": count,
        "offset": offset,
        "limit": limit,
    }
