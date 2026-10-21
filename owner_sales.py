"""Read-only owner sales from persisted, signed-webhook completion evidence.

No Stripe calls, order writes, refunds inference, or bounded UI snapshots.
All date boundaries and buckets use UTC; amounts stay integer cents in SQL.
"""
from calendar import monthrange
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, and_, or_


PERIODS = {"1y": (12, "month"), "6m": (6, "month"), "3m": (3, "week"), "1m": (1, "day")}


def shift_month(value, months):
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    return value.replace(year=year, month=month + 1, day=min(value.day, monthrange(year, month + 1)[1]))


def period_bounds(period, now):
    months, grain = PERIODS[period]
    today = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = shift_month(today.replace(day=1), 1 - months) if grain == "month" else shift_month(today, -months)
    return start, now.astimezone(timezone.utc), grain


def bucket_start(value, grain):
    value = value.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "month":
        return value.replace(day=1)
    if grain == "week":
        return value - timedelta(days=value.weekday())
    return value


def aggregate_sales(db, order, period="1y", *, now=None):
    now = now or datetime.now(timezone.utc)
    start, end, grain = period_bounds(period, now)
    # Fail closed: live Checkout session + payment intent + signed webhook event,
    # explicit completed state + recorded paid_at. Never created_at backfill alone.
    mode = order.quote_payload["_payment"]["mode"].as_string()
    eligible = and_(
        order.stripe_session_id.regexp_match(r"^cs_live_[A-Za-z0-9_]+$"),
        order.stripe_payment_intent.regexp_match(r"^pi_[A-Za-z0-9_]+$"),
        order.last_stripe_event_id.regexp_match(r"^evt_[A-Za-z0-9_]+$"),
        order.status == "completed", order.paid_at.is_not(None),
        order.amount_total_cents > 0,
        or_(mode.is_(None), mode == "live"),
    )
    # Rank before date filtering: the same payment cannot appear in two periods.
    ranked = select(
        order.paid_at.label("paid_at"), order.amount_total_cents.label("cents"),
        func.row_number().over(partition_by=order.stripe_payment_intent, order_by=(order.paid_at, order.id)).label("intent_rank"),
        func.row_number().over(partition_by=order.stripe_session_id, order_by=(order.paid_at, order.id)).label("session_rank"),
        func.row_number().over(partition_by=order.last_stripe_event_id, order_by=(order.paid_at, order.id)).label("event_rank"),
    ).where(eligible).subquery()
    paid = ranked.c.paid_at
    if db.bind.dialect.name == "postgresql":
        bucket = func.date_trunc(grain, func.timezone("UTC", paid))
    else:  # SQLite isolated regression fixtures; production is PostgreSQL.
        bucket = (func.strftime("%Y-%m-01", paid) if grain == "month" else
                  func.date(paid, "-6 days", "weekday 1") if grain == "week" else func.date(paid))
    query = select(bucket.label("bucket"), func.sum(ranked.c.cents), func.count()).where(
        ranked.c.intent_rank == 1, ranked.c.session_rank == 1, ranked.c.event_rank == 1,
        paid >= start, paid <= end,
    ).group_by(bucket).order_by(bucket)
    values = {str(row[0])[:10]: (int(row[1]), int(row[2])) for row in db.execute(query)}
    points = []
    cursor = bucket_start(start, grain)
    while cursor <= end:
        cents, count = values.get(cursor.date().isoformat(), (0, 0))
        points.append({"date": cursor.date().isoformat(), "amount_cents": cents, "order_count": count})
        cursor = shift_month(cursor, 1) if grain == "month" else cursor + timedelta(days=7 if grain == "week" else 1)
    return {
        "period": period, "grain": grain, "timezone": "UTC", "currency": "USD",
        "start": start.isoformat(), "end": end.isoformat(),
        "label": "LIVE paid order total", "points": points,
        "total_cents": sum(p["amount_cents"] for p in points),
        "order_count": sum(p["order_count"] for p in points),
        "basis": "Recorded paid timestamp (UTC). Includes shipping. Refunds, chargebacks and adjustments are not deducted; not net revenue.",
    }
