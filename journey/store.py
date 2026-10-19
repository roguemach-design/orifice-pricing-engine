"""Separate analytics tables. No customer/order payloads, identifiers or artifact access."""

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import (
    MetaData,
    Table,
    Column,
    String,
    Integer,
    DateTime,
    Boolean,
    UniqueConstraint,
    select,
    insert,
    update,
    delete,
    and_,
    func,
)
from sqlalchemy.exc import IntegrityError
from .schema import STEPS

metadata = MetaData()
sessions = Table(
    "journey_sessions_v1",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("started", DateTime(timezone=True), index=True),
    Column("expires", DateTime(timezone=True)),
    Column("internal", Boolean, nullable=False),
    Column("revoked", Boolean, nullable=False, default=False),
)
events = Table(
    "journey_events_v1",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("session", String(32), index=True),
    Column("received", DateTime(timezone=True), index=True),
    Column("timestamp", DateTime(timezone=True)),
    Column("step", String(24)),
    Column("outcome", String(16)),
    Column("category", String(24)),
    Column("source", String(16)),
)
# Reaches are session-day counts; one session can be counted on two calendar days.
reaches = Table(
    "journey_reaches_v1",
    metadata,
    Column("session", String(32), primary_key=True),
    Column("day", String(10), primary_key=True),
    Column("step", String(24), primary_key=True),
)
daily = Table(
    "journey_daily_v1",
    metadata,
    Column("day", String(10), primary_key=True),
    Column("step", String(24), primary_key=True),
    Column("internal", Boolean, primary_key=True),
    Column("count", Integer, nullable=False),
)
links = Table(
    "journey_checkout_links_v1",
    metadata,
    Column("reference", String(64), primary_key=True),
    Column("session", String(32), index=True),
    Column("created", DateTime(timezone=True)),
    Column("paid", Boolean, default=False, nullable=False),
)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class Store:
    def __init__(self, engine, secret, *, internal=False):
        self.engine, self.secret, self.internal = engine, secret.encode(), internal
        self.lock = threading.RLock()
        metadata.create_all(engine)

    def start(self, internal=False, now=None):
        now = now or datetime.now(timezone.utc)
        sid = secrets.token_hex(16)
        expires = now + timedelta(hours=24)
        with self.lock, self.engine.begin() as db:
            # A fixed daily storage budget complements the in-process request cap.
            if (
                db.scalar(
                    select(func.count())
                    .select_from(sessions)
                    .where(sessions.c.started >= now - timedelta(days=1))
                )
                >= 3000
            ):
                raise ValueError("Collection budget reached")
            db.execute(
                insert(sessions).values(
                    id=sid,
                    started=now,
                    expires=expires,
                    internal=self.internal or internal,
                    revoked=False,
                )
            )
        body = f"{sid}.{int(expires.timestamp())}"
        return (
            body
            + "."
            + hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
        )

    def session(self, db, token, now=None):
        now = now or datetime.now(timezone.utc)
        if not isinstance(token, str) or len(token) != 108:
            raise ValueError("Invalid session")
        sid, expires, signature = token.split(".")
        body = f"{sid}.{expires}"
        if not hmac.compare_digest(
            signature, hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
        ):
            raise ValueError("Invalid session")
        row = (
            db.execute(select(sessions).where(sessions.c.id == sid)).mappings().first()
        )
        if not row or row["revoked"] or utc(row["expires"]) <= now:
            raise ValueError("Expired session")
        return row

    def increment(self, db, day, step, internal, amount=1):
        key = and_(
            daily.c.day == day, daily.c.step == step, daily.c.internal == internal
        )
        if (
            db.execute(
                update(daily).where(key).values(count=daily.c.count + amount)
            ).rowcount
            == 0
        ):
            db.execute(
                insert(daily).values(
                    day=day, step=step, internal=internal, count=amount
                )
            )

    def promote_internal(self, db, row):
        if row["internal"]:
            return
        for reach in db.execute(
            select(reaches).where(reaches.c.session == row["id"])
        ).mappings():
            self.increment(db, reach["day"], reach["step"], False, -1)
            self.increment(db, reach["day"], reach["step"], True)
        db.execute(
            update(sessions).where(sessions.c.id == row["id"]).values(internal=True)
        )

    def add(self, token, event, *, internal=False, now=None):
        now = now or datetime.now(timezone.utc)
        with self.lock, self.engine.begin() as db:
            row = self.session(db, token, now)
            if internal:
                self.promote_internal(db, row)
            if (
                db.scalar(
                    select(func.count())
                    .select_from(events)
                    .where(events.c.session == row["id"])
                )
                >= 100
                or db.scalar(
                    select(func.count())
                    .select_from(events)
                    .where(
                        events.c.received
                        >= now.replace(hour=0, minute=0, second=0, microsecond=0)
                    )
                )
                >= 30000
            ):
                return False
            if db.scalar(select(events.c.id).where(events.c.id == str(event.event_id))):
                return False
            db.execute(
                insert(events).values(
                    id=str(event.event_id),
                    session=row["id"],
                    received=now,
                    timestamp=event.timestamp,
                    step=event.step,
                    outcome=event.outcome,
                    category=event.category,
                    source=event.source,
                )
            )
            # Client errors/attempts never imply successful checkout/payment.
            if (
                (
                    event.outcome in ("reached", "success")
                    and event.step not in ("checkout", "paid_order")
                )
                or (event.step == "checkout" and event.outcome == "attempted")
            ) and event.step in STEPS:
                self.reach(
                    db,
                    row["id"],
                    now.date().isoformat(),
                    event.step,
                    row["internal"] or internal,
                )
            return True

    def reach(self, db, sid, day, step, internal):
        key = and_(
            reaches.c.session == sid, reaches.c.day == day, reaches.c.step == step
        )
        if not db.scalar(select(reaches.c.session).where(key)):
            db.execute(insert(reaches).values(session=sid, day=day, step=step))
            self.increment(db, day, step, internal)

    def bind(self, token, reference, internal=False):
        now = datetime.now(timezone.utc)
        reference = hmac.new(
            self.secret, reference.encode(), hashlib.sha256
        ).hexdigest()
        with self.lock, self.engine.begin() as db:
            row = self.session(db, token)
            if internal:
                self.promote_internal(db, row)
            if db.scalar(
                select(links.c.reference).where(links.c.reference == reference)
            ):
                return
            db.execute(
                insert(links).values(
                    reference=reference, session=row["id"], created=now, paid=False
                )
            )

    def paid(self, reference, *, live):
        now = datetime.now(timezone.utc)
        reference = hmac.new(
            self.secret, reference.encode(), hashlib.sha256
        ).hexdigest()
        with self.lock, self.engine.begin() as db:
            link = (
                db.execute(select(links).where(links.c.reference == reference))
                .mappings()
                .first()
            )
            if not link or link["paid"]:
                return
            row = (
                db.execute(select(sessions).where(sessions.c.id == link["session"]))
                .mappings()
                .first()
            )
            if not row or row["revoked"]:
                return
            if not live:
                self.promote_internal(db, row)
            db.execute(
                update(links).where(links.c.reference == reference).values(paid=True)
            )
            self.reach(
                db,
                row["id"],
                now.date().isoformat(),
                "paid_order",
                row["internal"] or not live,
            )
            db.execute(
                insert(events).values(
                    id=secrets.token_hex(16),
                    session=row["id"],
                    received=now,
                    timestamp=now,
                    step="paid_order",
                    outcome="success",
                    category="none",
                    source="backend",
                )
            )

    def revoke(self, token):
        with self.lock, self.engine.begin() as db:
            row = self.session(db, token)
            # Daily counts are corrected while the diagnostic ledger is retained.
            for reach in db.execute(
                select(reaches).where(reaches.c.session == row["id"])
            ).mappings():
                self.increment(db, reach["day"], reach["step"], row["internal"], -1)
            for table in (events, reaches, links):
                db.execute(delete(table).where(table.c.session == row["id"]))
            db.execute(
                update(sessions).where(sessions.c.id == row["id"]).values(revoked=True)
            )

    def prune(self, now=None):
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=7)
        with self.lock, self.engine.begin() as db:
            for table, column in (
                (events, events.c.received),
                (sessions, sessions.c.started),
                (links, links.c.created),
            ):
                db.execute(delete(table).where(column < cutoff))
            db.execute(delete(reaches).where(reaches.c.day < cutoff.date().isoformat()))
            db.execute(
                delete(daily).where(
                    daily.c.day < (now - timedelta(days=89)).date().isoformat()
                )
            )

    def mark_internal(self, token):
        with self.lock, self.engine.begin() as db:
            self.promote_internal(db, self.session(db, token))

    def report(self, hours, internal=False):
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)
        cutoff = max(since, now - timedelta(days=7))
        with self.lock, self.engine.connect() as db:
            join = events.join(sessions, events.c.session == sessions.c.id)
            filters = (
                events.c.received >= cutoff,
                sessions.c.internal == internal,
                sessions.c.revoked == False,
            )
            counts = db.execute(
                select(events.c.step, func.count(func.distinct(events.c.session)))
                .select_from(join)
                .where(
                    *filters,
                    ((events.c.step == "checkout") & (events.c.outcome == "attempted"))
                    | (
                        (events.c.step != "checkout")
                        & events.c.outcome.in_(["success", "reached"])
                    ),
                )
                .group_by(events.c.step)
            ).all()
            if hours <= 168:
                funnel = {step: dict(counts).get(step, 0) for step in STEPS}
                unit = "distinct observed sessions"
            else:
                # Whole UTC days, explicitly labeled; never pretends to be unique visitors.
                agg = db.execute(
                    select(daily.c.step, func.sum(daily.c.count))
                    .where(
                        daily.c.day
                        >= (now - timedelta(days=hours // 24 - 1)).date().isoformat(),
                        daily.c.internal == internal,
                    )
                    .group_by(daily.c.step)
                ).all()
                funnel = {step: dict(agg).get(step, 0) for step in STEPS}
                unit = "session-days (UTC daily aggregates; not distinct visitors)"
            error_rows = db.execute(
                select(
                    events.c.step,
                    events.c.category,
                    events.c.source,
                    func.count().label("frequency"),
                    func.count(func.distinct(events.c.session)).label("sessions"),
                )
                .select_from(join)
                .where(*filters, events.c.category != "none")
                .group_by(events.c.step, events.c.category, events.c.source)
                .order_by(func.count().desc())
                .limit(30)
            ).mappings()
            errors = [dict(row) for row in error_rows]
            latest = list(
                db.scalars(
                    select(events.c.session)
                    .select_from(join)
                    .where(*filters)
                    .group_by(events.c.session)
                    .order_by(func.max(events.c.received).desc())
                    .limit(100)
                )
            )
            rows = (
                list(
                    db.execute(
                        select(events)
                        .where(
                            events.c.session.in_(latest), events.c.received >= cutoff
                        )
                        .order_by(events.c.received)
                    ).mappings()
                )
                if latest
                else []
            )
            timelines = {}
            for row in rows:
                timelines.setdefault(row["session"], []).append(
                    {
                        k: (
                            utc(row[k]).isoformat()
                            if k in ("timestamp", "received")
                            else row[k]
                        )
                        for k in (
                            "timestamp",
                            "received",
                            "step",
                            "outcome",
                            "category",
                            "source",
                        )
                    }
                )
            session_rows = []
            for sid in latest:
                timeline = timelines[sid]
                successes = [
                    e["step"]
                    for e in timeline
                    if e["outcome"] in ("success", "reached")
                ]
                last = timeline[-1]
                inactive = datetime.fromisoformat(last["received"]) < now - timedelta(
                    minutes=30
                )
                outstanding = {}
                for e in timeline:
                    if e["category"] != "none":
                        outstanding[e["step"]] = e["category"]
                    elif e["outcome"] in ("success", "reached"):
                        outstanding.pop(e["step"], None)
                status = (
                    "paid"
                    if any(e["step"] == "paid_order" for e in timeline)
                    else (
                        next(reversed(outstanding.values()))
                        if outstanding
                        else "possible_abandonment" if inactive else "active"
                    )
                )
                session_rows.append(
                    {
                        "session": sid,
                        "last_successful_step": successes[-1] if successes else "none",
                        "classification": status,
                        "timeline": timeline,
                    }
                )
            return {
                "version": 1,
                "generated_at": now.isoformat(),
                "window_hours": hours,
                "funnel_unit": unit,
                "funnel": funnel,
                "errors": errors,
                "sessions": session_rows,
                "session_list_limit": 100,
                "diagnostic_days": 7,
                "aggregate_days": 90,
                "internal": internal,
                "notes": [
                    "Opted-in observed traffic only; missing telemetry is unknown, not proof of abandonment.",
                    "Direct entry and cart/PDF branches can skip steps; these are stage reaches, not a forced linear funnel.",
                    "No historical backfill. Payments require committed server records; client events cannot prove payment or approval.",
                    "Possible abandonment means 30 minutes inactive with no observed blocker; it is not a confirmed reason.",
                    "Diagnostics cover at most 7 days, even when the aggregate filter covers 30 or 90 days.",
                ],
            }
