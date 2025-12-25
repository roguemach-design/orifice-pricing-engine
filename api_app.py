import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, Dict

import stripe
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pricing_engine import QuoteInputs, calculate_quote

# DB (Postgres via Render)
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

# Email (SendGrid)
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


# ----------------------------
# App + config
# ----------------------------
app = FastAPI(title="Orifice Pricing API", version="1.0.0")

ALLOWED_ORIGINS = [
    "https://quote.o-plates.com",
    "https://orifice-pricing-ui.onrender.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key protection (for your own endpoints, not Stripe webhooks)
API_KEY = os.environ.get("API_KEY", "")

# Stripe config (set in Render -> orifice-pricing-api -> Environment)
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://quote.o-plates.com")

# DB config
DATABASE_URL = os.environ.get("DATABASE_URL", "")
Base = declarative_base()
engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine) if engine else None

# Email config
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "orders@o-plates.com")


# ----------------------------
# DB Model
# ----------------------------
class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True)  # uuid4
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    stripe_session_id = Column(String, unique=True, index=True)
    stripe_payment_intent = Column(String, nullable=True)

    customer_email = Column(String, nullable=True)

    amount_subtotal_cents = Column(Integer, nullable=True)
    amount_shipping_cents = Column(Integer, nullable=True)
    amount_total_cents = Column(Integer, nullable=True)

    shipping_service = Column(String, nullable=True)  # ups_ground / ups_2day / ups_nextday
    shipping_name = Column(String, nullable=True)
    shipping_address = Column(JSON, nullable=True)

    quote_payload = Column(JSON, nullable=True)  # what customer configured


def init_db() -> None:
    if engine:
        Base.metadata.create_all(bind=engine)


init_db()


# ----------------------------
# Helpers
# ----------------------------
def _require_api_key(x_api_key: Optional[str]) -> None:
    if API_KEY:
        if not x_api_key or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")


def _send_email(to_email: str, subject: str, html: str) -> None:
    # Allow running without email configured
    if not SENDGRID_API_KEY:
        print("ℹ️ SENDGRID_API_KEY not set; skipping email.")
        return

    msg = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html,
    )
    SendGridAPIClient(SENDGRID_API_KEY).send(msg)


def _db_required() -> None:
    if not SessionLocal:
        raise HTTPException(status_code=500, detail="DB not configured (missing DATABASE_URL).")


# ----------------------------
# Request models
# ----------------------------
class QuoteRequest(BaseModel):
    quantity: int
    material: str
    thickness: float
    handle_width: float
    handle_length_from_bore: float
    paddle_dia: float
    bore_dia: float
    bore_tolerance: float
    chamfer: bool
    ships_in_days: int


class CheckoutCreateRequest(BaseModel):
    inputs: QuoteRequest


# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/quote")
def quote(req: QuoteRequest, x_api_key: Optional[str] = Header(default=None)):
    _require_api_key(x_api_key)
    inputs = QuoteInputs(**req.model_dump())
    return calculate_quote(inputs)


@app.post("/checkout/create")
def checkout_create(req: CheckoutCreateRequest, x_api_key: Optional[str] = Header(default=None)):
    """
    Called by Streamlit to start Stripe Checkout.
    Server recomputes pricing + shipping options (do not trust client).
    Also saves a "pending" order record keyed to the Stripe session.
    """
    _require_api_key(x_api_key)

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe is not configured (missing STRIPE_SECRET_KEY).")

    # Recompute quote on server
    inputs = QuoteInputs(**req.inputs.model_dump())
    result = calculate_quote(inputs)

    total_cents = int(result.get("total_price_cents") or round(float(result["total_price"]) * 100))

    shipping = result.get("shipping") or {}
    missing = [k for k in ("ups_ground_cents", "ups_2day_cents", "ups_nextday_cents") if k not in shipping]
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing shipping fields from pricing engine: {', '.join(missing)}")

    # Create Stripe Checkout session
    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{APP_BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{APP_BASE_URL}/cancel",
        shipping_address_collection={"allowed_countries": ["US"]},
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Custom Orifice Plate"},
                    "unit_amount": total_cents,
                },
                "quantity": 1,
            }
        ],
        shipping_options=[
            {
                "shipping_rate_data": {
                    "type": "fixed_amount",
                    "fixed_amount": {"amount": int(shipping["ups_ground_cents"]), "currency": "usd"},
                    "display_name": "UPS Ground",
                    "metadata": {"service": "ups_ground"},
                }
            },
            {
                "shipping_rate_data": {
                    "type": "fixed_amount",
                    "fixed_amount": {"amount": int(shipping["ups_2day_cents"]), "currency": "usd"},
                    "display_name": "UPS 2nd Day Air",
                    "metadata": {"service": "ups_2day"},
                }
            },
            {
                "shipping_rate_data": {
                    "type": "fixed_amount",
                    "fixed_amount": {"amount": int(shipping["ups_nextday_cents"]), "currency": "usd"},
                    "display_name": "UPS Next Day Air",
                    "metadata": {"service": "ups_nextday"},
                }
            },
        ],
        metadata={
            "quote_id": str(result.get("quote_id", "")),
        },
    )

    # Save a "pending" order (optional but helpful)
    if SessionLocal:
        db = SessionLocal()
        try:
            existing = db.query(Order).filter(Order.stripe_session_id == session.id).first()
            if not existing:
                o = Order(
                    id=str(uuid.uuid4()),
                    stripe_session_id=session.id,
                    quote_payload=req.inputs.model_dump(),
                    # amounts will be updated from webhook after payment
                )
                db.add(o)
                db.commit()
        finally:
            db.close()

    return {"checkout_url": session.url, "session_id": session.id}


@app.get("/orders/by-session/{session_id}")
def get_order_by_session(session_id: str):
    """
    Used by the Streamlit success page to show order summary after redirect.
    """
    _db_required()

    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.stripe_session_id == session_id).first()
        if not o:
            raise HTTPException(status_code=404, detail="Order not found yet")

        return {
            "id": o.id,
            "customer_email": o.customer_email,
            "amount_total_usd": (o.amount_total_cents or 0) / 100.0,
            "amount_subtotal_usd": (o.amount_subtotal_cents or 0) / 100.0,
            "amount_shipping_usd": (o.amount_shipping_cents or 0) / 100.0,
            "shipping_service": o.shipping_service,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
    finally:
        db.close()


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe calls this. Do NOT protect with API_KEY.
    Must verify signature using STRIPE_WEBHOOK_SECRET.
    Saves the paid order and emails confirmation.
    """
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook not configured (missing STRIPE_WEBHOOK_SECRET).")

    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        stripe_session_id = session.get("id")
        payment_intent = session.get("payment_intent")

        customer_email = (session.get("customer_details") or {}).get("email")
        amount_total = session.get("amount_total")          # cents
        amount_subtotal = session.get("amount_subtotal")    # cents
        amount_shipping = ((session.get("shipping_cost") or {}).get("amount_total"))  # cents

        shipping_details = session.get("shipping_details") or {}
        shipping_name = shipping_details.get("name")
        shipping_address = shipping_details.get("address")

        # Note: identifying which shipping option was chosen is easiest if you
        # store it server-side or retrieve the shipping_rate object. For v1, we
        # leave it blank unless you want to add retrieval.
        shipping_service = None

        print("✅ PAYMENT CONFIRMED:", stripe_session_id)

        # Save/update order in DB
        if SessionLocal:
            db = SessionLocal()
            try:
                o = db.query(Order).filter(Order.stripe_session_id == stripe_session_id).first()
                if not o:
                    # If not created earlier, create it now
                    o = Order(
                        id=str(uuid.uuid4()),
                        stripe_session_id=stripe_session_id,
                    )
                    db.add(o)

                o.stripe_payment_intent = payment_intent
                o.customer_email = customer_email
                o.amount_total_cents = amount_total
                o.amount_subtotal_cents = amount_subtotal
                o.amount_shipping_cents = amount_shipping
                o.shipping_name = shipping_name
                o.shipping_address = shipping_address
                o.shipping_service = shipping_service

                db.commit()

                order_id = o.id
            finally:
                db.close()
        else:
            order_id = "N/A"
            print("ℹ️ DATABASE_URL not set; skipping DB save.")

        # Email confirmation
        if customer_email:
            _send_email(
                to_email=customer_email,
                subject="O-Plates order received",
                html=f"""
                <p>Thanks — we received your order.</p>
                <p><b>Order ID:</b> {order_id}</p>
                <p><b>Total Paid:</b> ${((amount_total or 0) / 100):.2f}</p>
                <p>We’ll email your approval drawing next.</p>
                """,
            )

    return {"ok": True}
