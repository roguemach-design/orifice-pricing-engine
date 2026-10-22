"""Saved commercial quotes: private records and an adapter into the existing cart.

No prices, Stripe settings, shipping rules or manufacturing logic live here.
All new routes default closed until SAVED_QUOTES_ENABLED is explicitly enabled.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit
from uuid import uuid4
from contextvars import ContextVar

CHECKOUT_QUOTE = ContextVar("saved_quote_checkout", default=None)
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Integer,
    JSON,
    LargeBinary,
    UniqueConstraint,
    event,
    inspect,
    or_,
)
from sqlalchemy.exc import IntegrityError

from quote_document import render_quote_pdf, quote_filename, subtotal

UNAVAILABLE = "Quote not available for this account."
IMMUTABLE = {
    "quote_id",
    "root_quote_id",
    "revision",
    "supersedes_quote_id",
    "owner_user_id",
    "created_at",
    "valid_through",
    "snapshot",
    "pdf_bytes",
    "pdf_sha256",
}


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def unavailable():
    raise HTTPException(404, UNAVAILABLE)


def enabled():
    return os.environ.get("SAVED_QUOTES_ENABLED") == "true"


def register_models(Base):
    class Quote(Base):
        __tablename__ = "saved_quotes"
        quote_id = Column(String(40), primary_key=True)
        root_quote_id = Column(String(40), nullable=False, index=True)
        revision = Column(Integer, nullable=False)
        supersedes_quote_id = Column(String(40))
        owner_user_id = Column(String, nullable=False, index=True)
        created_at = Column(DateTime(timezone=True), nullable=False)
        valid_through = Column(DateTime(timezone=True), nullable=False)
        snapshot = Column(JSON, nullable=False)
        pdf_bytes = Column(LargeBinary, nullable=False)
        pdf_sha256 = Column(String(64), nullable=False)
        status = Column(String(16), nullable=False, default="open")
        ordered_order_id = Column(String, unique=True)
        checkout = Column(JSON)
        __table_args__ = (UniqueConstraint("root_quote_id", "revision"),)

    @event.listens_for(Quote, "before_update")
    def prevent_snapshot_changes(mapper, connection, target):
        if any(inspect(target).attrs[k].history.has_changes() for k in IMMUTABLE):
            raise ValueError("Saved quote snapshots are immutable; create a revision.")

    class Share(Base):
        __tablename__ = "quote_shares"
        id = Column(String, primary_key=True)
        quote_id = Column(String(40), nullable=False, index=True)
        invited_email = Column(String(254), nullable=False)
        accepted_user_id = Column(String, index=True)
        token_hash = Column(String(64), nullable=False, unique=True)
        expires_at = Column(DateTime(timezone=True), nullable=False)
        revoked_at = Column(DateTime(timezone=True))
        accepted_at = Column(DateTime(timezone=True))
        delivery_state = Column(String, nullable=False, default="pending")

    class Event(Base):
        __tablename__ = "quote_events"
        id = Column(String, primary_key=True, default=lambda: str(uuid4()))
        quote_id = Column(String(40), nullable=False, index=True)
        actor_user_id = Column(String, nullable=False)
        action = Column(String, nullable=False)
        created_at = Column(DateTime(timezone=True), nullable=False, default=now)
        detail = Column(JSON, nullable=False, default=dict)

    class Review(Base):
        __tablename__ = "quote_reviews"
        id = Column(String, primary_key=True)
        quote_id = Column(String(40), nullable=False, index=True)
        buyer_user_id = Column(String, nullable=False)
        expires_at = Column(DateTime(timezone=True), nullable=False)
        snapshot = Column(JSON, nullable=False)

    class MailRecord(Base):
        __tablename__ = "quote_mail"
        id = Column(String, primary_key=True)
        quote_id = Column(String(40), nullable=False, index=True)
        recipient = Column(String, nullable=False)
        state = Column(String, nullable=False, default="pending")
        created_at = Column(DateTime(timezone=True), nullable=False, default=now)

    return SimpleNamespace(
        Quote=Quote, Share=Share, Event=Event, Review=Review, Mail=MailRecord
    )


class SaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict] = Field(min_length=1, max_length=60)
    customer: dict = Field(default_factory=dict)
    pricing_config_version: str


class RevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict] | None = Field(default=None, min_length=1, max_length=60)
    customer: dict | None = None


class ShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)


class AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=20, max_length=128)


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_times: list[int] | None = Field(default=None, max_length=60)


def verified_identity(api, authorization):
    """Fresh Auth-server user lookup; never trust browser email or user_metadata."""
    uid = api._require_customer_user_id(authorization)
    from supabase import create_client

    url = (
        os.environ.get("SUPABASE_URL")
        or api.SUPABASE_JWT_ISSUER.removesuffix("/auth/v1")
    ).rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ.get(
        "SUPABASE_ANON_KEY"
    )
    if not url or not key:
        raise HTTPException(503, "Account verification unavailable.")
    try:
        user = (
            create_client(url, key).auth.get_user(authorization.split(" ", 1)[1]).user
        )
        if (
            str(user.id) != uid
            or not user.email
            or not user.email_confirmed_at
            or user.is_anonymous
            or getattr(user, "deleted_at", None)
            or (
                getattr(user, "banned_until", None)
                and datetime.fromisoformat(
                    str(user.banned_until).replace("Z", "+00:00")
                )
                > now()
            )
        ):
            raise ValueError("Verified email required")
        return {"id": uid, "email": user.email.strip().lower()}
    except Exception:
        raise HTTPException(401, "Sign in with a verified email to continue.") from None


class Service:
    def __init__(self, api):
        self.api = api
        self.m = api.QUOTE_MODELS

    def log(self, db, qid, who, action, detail=None):
        db.add(
            self.m.Event(
                quote_id=qid, actor_user_id=who, action=action, detail=detail or {}
            )
        )

    def guard(self, request, person):
        if not enabled():
            raise HTTPException(404, "Saved quotes are not available.")
        self.api._db_required()
        self.api._RATE_LIMITER.check("quotes-user:" + person["id"], 60, 60)
        # Peer IP only; never trust arbitrary forwarded headers.
        self.api._RATE_LIMITER.check(
            "quotes-ip:" + (request.client.host if request.client else "unknown"),
            300,
            60,
        )

    def get(self, db, qid, person, *, owner=False, lock=False):
        query = db.query(self.m.Quote).filter(
            self.m.Quote.quote_id == qid.strip().upper()
        )
        if lock:
            query = query.with_for_update()
        q = query.first()
        if not q:
            unavailable()
        if q.owner_user_id != person["id"]:
            if owner:
                unavailable()
            share = (
                db.query(self.m.Share)
                .filter(
                    self.m.Share.quote_id == q.quote_id,
                    self.m.Share.accepted_user_id == person["id"],
                    self.m.Share.invited_email == person["email"],
                    self.m.Share.revoked_at.is_(None),
                    self.m.Share.expires_at > now(),
                )
                .first()
            )
            if not share:
                unavailable()
        return q

    def state(self, q):
        if q.status != "open":
            return q.status
        return "expired" if aware(q.valid_through) <= now() else "open"

    def public(self, q, person, detail=False):
        result = {
            "quote_id": q.quote_id,
            "root_quote_id": q.root_quote_id,
            "supersedes_quote_id": q.supersedes_quote_id,
            "created_at": aware(q.created_at).isoformat(),
            "valid_through": aware(q.valid_through).isoformat(),
            "status": self.state(q),
            "subtotal": str(subtotal(q.snapshot["lines"])),
            "shared_with_you": q.owner_user_id != person["id"],
            "pdf_sha256": q.pdf_sha256,
            "ordered_order_id": (
                q.ordered_order_id
                if q.checkout and q.checkout["buyer_id"] == person["id"]
                else None
            ),
        }
        if detail:
            result["snapshot"] = copy.deepcopy(q.snapshot)
            result["checkout_in_progress"] = bool(q.checkout and q.status != "ordered")
        return result

    def quote_url(self, qid, token=None):
        origin = self.api.APP_BASE_URL
        if urlsplit(origin).scheme != "https" and self.api.APP_ENV != "test":
            raise HTTPException(503, "Quote links are not configured.")
        return (
            origin
            + "/My_Quotes?"
            + urlencode({"quote": qid, **({"invite": token} if token else {})})
        )

    def price(self, items):
        lines = []
        version = None
        for raw in items:
            try:
                req = self.api.QuoteRequest.model_validate(raw)
                inputs = req.model_dump()
                res = self.api._calculate_quote_with_db_knobs(
                    self.api.QuoteInputs(**inputs)
                )
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    422,
                    "A plate or selected lead time is unavailable. Review the configuration.",
                ) from None
            current = res.get("pricing_config_version")
            if not current or version is not None and version != current:
                raise HTTPException(409, "Pricing changed. Please review again.")
            version = current
            lines.append(
                {
                    "inputs": inputs,
                    "unit_price": res["unit_price"],
                    "total_price": res["total_price"],
                    "qty_mult": res.get("qty_discount_multiplier", 1),
                    "weight": res.get("estimated_total_weight_lb", 0),
                }
            )
        return lines, version

    def clean_customer(self, customer):
        keys = (
            "company",
            "name",
            "email",
            "phone",
            "addr1",
            "addr2",
            "city_state_zip",
            "country",
            "purchasing_name",
            "purchasing_email",
        )
        if any(len(str(customer.get(k, ""))) > 300 for k in keys):
            raise HTTPException(
                422, "Customer fields may contain at most 300 characters."
            )
        return {k: str(customer[k]).strip() for k in keys if customer.get(k)}

    def save(self, db, person, items, customer, *, version=None, previous=None):
        lines, current = self.price(items)
        if version and current != version:
            raise HTTPException(409, "Pricing changed. Refresh before saving.")
        created = now()
        root = "Q-" + uuid4().hex[:10].upper()
        number = 1
        supersedes = None
        if previous and previous.owner_user_id == person["id"]:
            root = previous.root_quote_id
            latest = (
                db.query(self.m.Quote)
                .filter(self.m.Quote.root_quote_id == root)
                .order_by(self.m.Quote.revision.desc())
                .first()
            )
            if latest.quote_id != previous.quote_id:
                raise HTTPException(409, "Open the latest revision before editing.")
            if previous.checkout:
                raise HTTPException(
                    409, "Cancel the active checkout before revising this quote."
                )
            if previous.status == "ordered":
                raise HTTPException(409, "This quote has already been ordered.")
            number = previous.revision + 1
            supersedes = previous.quote_id
        qid = root + (f"-R{number}" if number > 1 else "")
        doc = {
            "quote_id": qid,
            "issued": created.astimezone(ZoneInfo("America/New_York"))
            .date()
            .isoformat(),
            "customer": self.clean_customer(customer),
            "pricing_ref": current,
            "lines": lines,
            "supersedes": supersedes,
        }
        # Immutable choice. Existing saved PDFs never gain links on redownload.
        doc["retrieval_live"] = os.environ.get("SAVED_QUOTES_LIVE") == "true"
        if doc["retrieval_live"]:
            doc["retrieval_url"] = self.quote_url(qid)
        render_doc = copy.deepcopy(doc)
        render_doc["issued"] = datetime.fromisoformat(doc["issued"]).date()
        pdf = render_quote_pdf(render_doc)
        q = self.m.Quote(
            quote_id=qid,
            root_quote_id=root,
            revision=number,
            supersedes_quote_id=supersedes,
            owner_user_id=person["id"],
            created_at=created,
            valid_through=created + timedelta(days=30),
            snapshot=doc,
            pdf_bytes=pdf,
            pdf_sha256=hashlib.sha256(pdf).hexdigest(),
            status="open",
        )
        db.add(q)
        if previous and supersedes:
            previous.status = "superseded"
        self.log(
            db,
            qid,
            person["id"],
            "create",
            {
                "supersedes": supersedes,
                "copied_from": (
                    previous.quote_id if previous and not supersedes else None
                ),
            },
        )
        mail = self.m.Mail(
            id=str(uuid4()), quote_id=qid, recipient=person["email"], state="pending"
        )
        db.add(mail)
        db.flush()
        return q, mail.id

    def mail(self, to, subject, html, pdf=None, filename=None):
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import (
            Mail,
            Attachment,
            FileContent,
            FileName,
            FileType,
            Disposition,
        )
        import base64

        html += "<p>Rogue Machine LLC<br>400 Public Rd, Yorkville, OH 43971, United States<br>sales@o-plates.com</p>"
        mode = os.environ.get("SAVED_QUOTES_EMAIL_MODE", "capture")
        if mode == "capture":
            return "captured"
        if mode != "sendgrid":
            raise RuntimeError("Quote email delivery mode is not configured")
        if not self.api.SENDGRID_API_KEY:
            raise RuntimeError("Email unavailable")
        msg = Mail(
            from_email=self.api.FROM_EMAIL,
            to_emails=to,
            subject=subject,
            html_content=html,
        )
        msg.reply_to = "sales@o-plates.com"
        if pdf:
            msg.attachment = Attachment(
                FileContent(base64.b64encode(pdf).decode()),
                FileName(filename),
                FileType("application/pdf"),
                Disposition("attachment"),
            )
        response = SendGridAPIClient(self.api.SENDGRID_API_KEY).send(msg)
        if response.status_code != 202:
            raise RuntimeError("Email not accepted")
        return "accepted"

    def deliver_quote(self, mail_id):
        # Claim before network I/O. Ambiguous delivery is not automatically retried.
        with self.api.SessionLocal.begin() as db:
            mail = db.query(self.m.Mail).filter_by(id=mail_id).with_for_update().one()
            if mail.state != "pending":
                return mail.state
            mail.state = "sending"
            qid = mail.quote_id
            recipient = mail.recipient
            q = db.get(self.m.Quote, qid)
            pdf = q.pdf_bytes
        try:
            state = self.mail(
                recipient,
                "Your O-Plates quote " + qid,
                '<h1>Your quote is ready</h1><p><a href="'
                + escape(self.quote_url(qid), quote=True)
                + '">View Your Quote</a></p><p>Sign in to view your saved quotation. The PDF is attached.</p>',
                pdf,
                quote_filename(qid),
            )
        except Exception:
            state = "needs_review"
        with self.api.SessionLocal.begin() as db:
            db.get(self.m.Mail, mail_id).state = state
        return state

    def validate_review(self, db, q, person, review_id, ack):
        review = db.get(self.m.Review, review_id or "")
        if (
            not review
            or review.quote_id != q.quote_id
            or review.buyer_user_id != person["id"]
            or aware(review.expires_at) <= now()
        ):
            raise HTTPException(409, "Review current pricing again before checkout.")
        if review.snapshot["changed"] and not ack:
            raise HTTPException(
                409, "Acknowledge the reviewed changes before checkout."
            )
        fresh, version = self.price([l["inputs"] for l in review.snapshot["lines"]])
        if (
            fresh != review.snapshot["lines"]
            or version != review.snapshot["pricing_ref"]
        ):
            raise HTTPException(409, "Pricing changed. Review current pricing again.")
        return review

    def checkout(self, req, person, checkout_mode, journey_session):
        if not enabled():
            raise HTTPException(404, "Saved quotes are not available.")
        # Commit a stable reservation before external I/O. A retry, worker restart,
        # or another buyer cannot turn an ambiguous Stripe response into two charges.
        with self.api.SessionLocal.begin() as db:
            q = self.get(db, req.saved_quote_id, person, lock=True)
            if self.state(q) != "open":
                raise HTTPException(
                    409,
                    "This quote is not open for ordering. Use Update Pricing if expired.",
                )
            if q.checkout:
                if q.checkout.get("mode") != (
                    "owner_test" if checkout_mode == "owner_test" else self.api.APP_ENV
                ):
                    raise HTTPException(
                        409, "Resume this quote in its original payment mode."
                    )
                if q.checkout["buyer_id"] != person["id"]:
                    raise HTTPException(
                        409, "A purchasing checkout is already in progress."
                    )
                if q.checkout.get("result"):
                    return q.checkout["result"]
                if q.checkout["review_id"] != req.saved_quote_review_id:
                    raise HTTPException(
                        409,
                        "Resume the original checkout review; a payment attempt is being reconciled.",
                    )
            review = self.validate_review(
                db, q, person, req.saved_quote_review_id, req.saved_quote_acknowledged
            )
            expected = [l["inputs"] for l in review.snapshot["lines"]]
            if [
                i.model_dump() for i in req.items
            ] != expected or req.pricing_config_version != review.snapshot[
                "pricing_ref"
            ]:
                raise HTTPException(
                    409,
                    "The cart differs from this quote review. Review the quote again.",
                )
            key = digest(
                {"quote": q.quote_id, "buyer": person["id"], "review": review.id}
            )
            if aware(q.valid_through) < now() + timedelta(minutes=31):
                raise HTTPException(
                    409, "This quote expires shortly. Update Pricing before checkout."
                )
            if not q.checkout:
                q.checkout = {
                    "buyer_id": person["id"],
                    "buyer_email": person["email"],
                    "review_id": review.id,
                    "key": key,
                    "expires_at": int(
                        min(
                            aware(q.valid_through), now() + timedelta(hours=24)
                        ).timestamp()
                    ),
                    "mode": (
                        "owner_test"
                        if checkout_mode == "owner_test"
                        else self.api.APP_ENV
                    ),
                }
        with self.api.SessionLocal.begin() as db:
            q = self.get(db, req.saved_quote_id, person, lock=True)
            if q.checkout.get("result"):
                return q.checkout["result"]
            review = self.validate_review(
                db, q, person, req.saved_quote_review_id, req.saved_quote_acknowledged
            )
            inner = self.api.CartCheckoutCreateRequest(
                items=[l["inputs"] for l in review.snapshot["lines"]],
                pricing_config_version=review.snapshot["pricing_ref"],
                idempotency_key=q.checkout["key"],
            )
            context = CHECKOUT_QUOTE.set(
                {
                    "quote_id": q.quote_id,
                    "email": q.checkout["buyer_email"],
                    "expires_at": q.checkout["expires_at"],
                }
            )
            try:
                result = self.api.checkout_cart_create(
                    inner, person["id"], checkout_mode, journey_session
                )
            finally:
                CHECKOUT_QUOTE.reset(context)
            order = (
                db.query(self.api.Order)
                .filter_by(stripe_session_id=result["session_id"])
                .one()
            )
            if order.customer_id != person["id"]:
                raise HTTPException(409, "Checkout identity mismatch.")
            q.checkout = {**q.checkout, "result": result, "order_id": order.id}
            self.log(
                db,
                q.quote_id,
                person["id"],
                "checkout",
                {"order_id": order.id, "review_id": review.id},
            )
            return result

    def cancel_checkout(self, db, q, person):
        if not q.checkout:
            return
        if q.status == "ordered":
            raise HTTPException(409, "A paid checkout cannot be canceled here.")
        result = q.checkout.get("result")
        if not result:
            raise HTTPException(
                409,
                "A payment attempt needs reconciliation before access can be revoked.",
            )
        args = (
            {"api_key": self.api.STRIPE_TEST_SECRET_KEY}
            if q.checkout.get("mode") == "owner_test"
            else {}
        )
        try:
            session = self.api.stripe.checkout.Session.retrieve(
                result["session_id"], **args
            )
            if session.get("status") == "open":
                session = self.api.stripe.checkout.Session.expire(
                    result["session_id"], **args
                )
            if session.get("status") != "expired":
                raise ValueError("Session may be paid or pending")
        except Exception:
            raise HTTPException(
                409,
                "Checkout could not be safely canceled. It may already be paid; refresh the quote.",
            ) from None
        self.log(
            db,
            q.quote_id,
            person["id"],
            "cancel_checkout",
            {"order_id": q.checkout.get("order_id")},
        )
        q.checkout = None

    def paid(self, db, order):
        qid = (order.quote_payload or {}).get("saved_quote_id")
        if not qid:
            return
        q = db.query(self.m.Quote).filter_by(quote_id=qid).with_for_update().one()
        if (
            not q.checkout
            or q.checkout["buyer_id"] != order.customer_id
            or q.checkout["order_id"] != order.id
        ):
            raise HTTPException(400, "Saved quote payment identity mismatch.")
        if q.ordered_order_id and q.ordered_order_id != order.id:
            raise HTTPException(409, "Quote already ordered.")
        order.customer_email = q.checkout["buyer_email"]
        if q.status != "ordered":
            q.status = "ordered"
            q.ordered_order_id = order.id
            self.log(db, qid, order.customer_id, "order", {"order_id": order.id})


def install_routes(api):
    s = Service(api)
    app = api.app

    def identity(request: Request, authorization: str | None = Header(default=None)):
        if not enabled():
            raise HTTPException(404, "Saved quotes are not available.")
        person = verified_identity(api, authorization)
        s.guard(request, person)
        return person

    s.identity = identity

    @app.middleware("http")
    async def quote_privacy(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/quotes", "/me/quotes")):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/quotes/availability")
    def availability():
        return {"enabled": enabled()}

    @app.post("/quotes")
    def save(body: SaveBody, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q, mail_id = s.save(
                db,
                person,
                body.items,
                body.customer,
                version=body.pricing_config_version,
            )
            result = s.public(q, person, True)
        result["email_status"] = s.deliver_quote(mail_id)
        return result

    @app.get("/me/quotes")
    def my_quotes(person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            shares = db.query(s.m.Share.quote_id).filter(
                s.m.Share.accepted_user_id == person["id"],
                s.m.Share.invited_email == person["email"],
                s.m.Share.revoked_at.is_(None),
                s.m.Share.expires_at > now(),
            )
            rows = (
                db.query(s.m.Quote)
                .filter(
                    or_(
                        s.m.Quote.owner_user_id == person["id"],
                        s.m.Quote.quote_id.in_(shares),
                    )
                )
                .order_by(s.m.Quote.created_at.desc())
                .limit(200)
                .all()
            )
            s.log(db, "ACCOUNT", person["id"], "list")
            return [s.public(q, person) for q in rows]

    @app.get("/quotes/{qid}")
    def view(qid: str, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person)
            s.log(db, q.quote_id, person["id"], "view")
            return s.public(q, person, True)

    @app.get("/quotes/{qid}/pdf")
    def pdf(qid: str, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person)
            if hashlib.sha256(q.pdf_bytes).hexdigest() != q.pdf_sha256:
                raise HTTPException(503, "Quote document integrity check failed.")
            s.log(db, q.quote_id, person["id"], "download")
            return Response(
                q.pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": 'attachment; filename="'
                    + quote_filename(q.quote_id)
                    + '"',
                    "Cache-Control": "private, no-store",
                },
            )

    @app.post("/quotes/{qid}/revisions")
    def revise(qid: str, body: RevisionBody, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            previous = s.get(db, qid, person, lock=True)
            q, mail_id = s.save(
                db,
                person,
                body.items or [l["inputs"] for l in previous.snapshot["lines"]],
                (
                    body.customer
                    if body.customer is not None
                    else previous.snapshot["customer"]
                ),
                previous=previous,
            )
            result = s.public(q, person, True)
        result["email_status"] = s.deliver_quote(mail_id)
        return result

    @app.post("/quotes/{qid}/shares")
    def share(qid: str, body: ShareBody, person=Depends(identity)):
        email = body.email.strip().lower()
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email):
            raise HTTPException(422, "Enter a valid purchasing email.")
        token = secrets.token_urlsafe(32)
        sid = str(uuid4())
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person, owner=True, lock=True)
            if s.state(q) != "open":
                raise HTTPException(409, "Only open quotes may be shared.")
            row = s.m.Share(
                id=sid,
                quote_id=q.quote_id,
                invited_email=email,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=q.valid_through,
            )
            db.add(row)
            s.log(db, q.quote_id, person["id"], "share", {"share_id": sid})
        try:
            state = s.mail(
                email,
                "Invitation to purchase O-Plates quote " + qid,
                '<h1>A quote was shared with you</h1><p><a href="'
                + escape(s.quote_url(qid, token), quote=True)
                + '">View Your Quote</a></p><p>Sign in with this invited email and accept the invitation to review current pricing and order.</p>',
            )
        except Exception:
            state = "needs_review"
        with api.SessionLocal.begin() as db:
            db.get(s.m.Share, sid).delivery_state = state
        return {"share_id": sid, "email_status": state}

    @app.post("/quotes/{qid}/email")
    def email_quote(qid: str, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person, owner=True, lock=True)
            mail = s.m.Mail(
                id=str(uuid4()),
                quote_id=q.quote_id,
                recipient=person["email"],
                state="pending",
            )
            db.add(mail)
            s.log(db, q.quote_id, person["id"], "email", {"mail_id": mail.id})
            mail_id = mail.id
        return {"email_status": s.deliver_quote(mail_id)}

    @app.get("/quotes/{qid}/shares")
    def shares(qid: str, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person, owner=True)
            s.log(db, q.quote_id, person["id"], "list_shares")
            return [
                {
                    "share_id": r.id,
                    "email": r.invited_email,
                    "accepted": bool(r.accepted_at),
                    "revoked": bool(r.revoked_at),
                    "email_status": r.delivery_state,
                }
                for r in db.query(s.m.Share).filter_by(quote_id=q.quote_id)
            ]

    @app.post("/quotes/{qid}/shares/{sid}/revoke")
    def revoke(qid: str, sid: str, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person, owner=True, lock=True)
            row = db.query(s.m.Share).filter_by(id=sid, quote_id=q.quote_id).first()
            if not row:
                unavailable()
            if q.checkout and row.accepted_user_id == q.checkout["buyer_id"]:
                s.cancel_checkout(db, q, person)
            row.revoked_at = now()
            s.log(db, q.quote_id, person["id"], "revoke", {"share_id": sid})
        return {"revoked": True}

    @app.post("/quotes/{qid}/accept")
    def accept(qid: str, body: AcceptBody, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = db.query(s.m.Quote).filter_by(quote_id=qid).with_for_update().first()
            row = (
                db.query(s.m.Share)
                .filter_by(
                    quote_id=qid,
                    token_hash=hashlib.sha256(body.token.encode()).hexdigest(),
                )
                .with_for_update()
                .first()
            )
            if (
                not q
                or not row
                or row.revoked_at
                or row.accepted_at
                or aware(row.expires_at) <= now()
                or row.invited_email != person["email"]
                or s.state(q) != "open"
            ):
                unavailable()
            row.accepted_user_id = person["id"]
            row.accepted_at = now()
            s.log(db, qid, person["id"], "accept", {"share_id": row.id})
        return {"accepted": True, "quote_id": qid}

    @app.post("/quotes/{qid}/checkout/cancel")
    def cancel(qid: str, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person, lock=True)
            if q.checkout and person["id"] not in (
                q.owner_user_id,
                q.checkout["buyer_id"],
            ):
                unavailable()
            s.cancel_checkout(db, q, person)
        return {"canceled": True}

    @app.post("/quotes/{qid}/revalidate")
    def revalidate(qid: str, body: ReviewBody, person=Depends(identity)):
        with api.SessionLocal.begin() as db:
            q = s.get(db, qid, person, lock=True)
            if s.state(q) != "open":
                raise HTTPException(
                    409, "This quote is not open. Use Update Pricing if expired."
                )
            items = copy.deepcopy([l["inputs"] for l in q.snapshot["lines"]])
            if body.lead_times is not None:
                if len(body.lead_times) != len(items):
                    raise HTTPException(422, "Choose a lead time for every plate.")
                for line, days in zip(items, body.lead_times):
                    line["ships_in_days"] = days
            lines, version = s.price(items)
            changed = (
                lines != q.snapshot["lines"] or version != q.snapshot["pricing_ref"]
            )
            snap = {"lines": lines, "pricing_ref": version, "changed": changed}
            review = s.m.Review(
                id=str(uuid4()),
                quote_id=q.quote_id,
                buyer_user_id=person["id"],
                expires_at=now() + timedelta(minutes=15),
                snapshot=snap,
            )
            db.add(review)
            s.log(
                db,
                q.quote_id,
                person["id"],
                "revalidate",
                {"review_id": review.id, "changed": changed},
            )
            return {
                **snap,
                "review_id": review.id,
                "quoted_lines": q.snapshot["lines"],
                "quoted_subtotal": str(subtotal(q.snapshot["lines"])),
                "current_subtotal": str(subtotal(lines)),
            }

    return s
