import os
from typing import Optional

import stripe
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pricing_engine import QuoteInputs, calculate_quote

# ----------------------------
# App + config
# ----------------------------
app = FastAPI(title="Orifice Pricing API", version="1.0.0")

# CORS: restrict to your real UI origins (add others only if needed)
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

# Stripe config (set these in Render -> orifice-pricing-api -> Environment)
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://quote.o-plates.com")

if not stripe.api_key:
    # You can still run /health and /quote without Stripe,
    # but /checkout/create will fail until STRIPE_SECRET_KEY is set.
    pass


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
    # If you want API-key protection:
    if API_KEY:
        if not x_api_key or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    inputs = QuoteInputs(**req.model_dump())
    return calculate_quote(inputs)


@app.post("/checkout/create")
def checkout_create(req: CheckoutCreateRequest, x_api_key: Optional[str] = Header(default=None)):
    """
    Called by Streamlit to start Stripe Checkout.
    Server recomputes pricing + shipping options (do not trust client).
    """

    # If you want API-key protection (optional):
    if API_KEY:
        if not x_api_key or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe is not configured (missing STRIPE_SECRET_KEY).")

    # Recompute quote on server
    inputs = QuoteInputs(**req.inputs.model_dump())
    result = calculate_quote(inputs)

    # Expected from calculate_quote:
    # - result["total_price"] (dollars) OR result["total_price_cents"]
    # - result["shipping"]["ups_ground_cents"], ["ups_2day_cents"], ["ups_nextday_cents"]
    if "total_price_cents" in result:
        total_cents = int(result["total_price_cents"])
    else:
        total_cents = int(round(float(result["total_price"]) * 100))

    shipping = result.get("shipping") or {}

    # Validate shipping fields exist
    missing = [k for k in ("ups_ground_cents", "ups_2day_cents", "ups_nextday_cents") if k not in shipping]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing shipping fields from pricing engine: {', '.join(missing)}",
        )

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
            # Keep metadata small; store full configuration server-side if/when you add a DB.
            "quote_id": str(result.get("quote_id", "")),
        },
    )

    return {"checkout_url": session.url, "session_id": session.id}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe calls this. Do NOT protect with API_KEY.
    Must verify signature using STRIPE_WEBHOOK_SECRET.
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
        # For now, just log. Next step: generate drawing + email approval link.
        print(
            "✅ PAYMENT CONFIRMED:",
            session.get("id"),
            "quote_id:",
            (session.get("metadata") or {}).get("quote_id"),
        )

    return {"ok": True}
