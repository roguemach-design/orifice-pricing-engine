# api_app.py
import os
import uuid
import copy
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pricing_engine import QuoteInputs, calculate_quote

# IMPORTANT:
# - pricing_engine.py imports its config module (tuning_knobs/pricing_config) internally as cfg.
# - We will dynamically apply DB knobs by updating that cfg module in-memory during a pricing call.
import tuning_knobs as cfg  # must exist in API service

# DB (Postgres via Render)
from sqlalchemy import Column, DateTime, Integer, JSON, String, create_engine, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

# Email (SendGrid)
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# JWT (Supabase)
import jwt
from jwt import PyJWKClient


# ----------------------------
# App + config
# ----------------------------
app = FastAPI(title="Orifice Pricing API", version="1.0.0")

ALLOWED_ORIGINS = [
    "https://quote.o-plates.com",
    "https://orifice-pricing-ui.onrender.com",
    "https://orifice-admin-ui.onrender.com",
    # add your portal origin once deployed, e.g.
    # "https://orifice-customer-portal.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API keys (server-to-server / your own UI)
API_KEY = (os.environ.get("API_KEY") or "").strip()
ADMIN_API_KEY = (os.environ.get("ADMIN_API_KEY") or "").strip()  # optional separate admin auth

# Supabase JWT verification (customer portal)
SUPABASE_JWKS_URL = (os.environ.get("SUPABASE_JWKS_URL") or "").strip()
SUPABASE_JWT_ISSUER = (os.environ.get("SUPABASE_JWT_ISSUER") or "").strip()
SUPABASE_JWT_AUD = (os.environ.get("SUPABASE_JWT_AUD") or "authenticated").strip()
_jwk_client: Optional[PyJWKClient] = PyJWKClient(SUPABASE_JWKS_URL) if SUPABASE_JWKS_URL else None

# Stripe config
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

# Serialize dynamic config apply/restore during pricing (avoids cross-request bleed)
_CFG_LOCK = threading.Lock()

# Snapshot of file-based defaults so we can restore after applying DB overrides
_CFG_BASELINE = {
    "PRICE_PER_SQ_IN": copy.deepcopy(getattr(cfg, "PRICE_PER_SQ_IN", {})),
    "MATERIAL_ENABLED": copy.deepcopy(getattr(cfg, "MATERIAL_ENABLED", {})),
    "THICKNESS_ENABLED_BY_MATERIAL": copy.deepcopy(getattr(cfg, "THICKNESS_ENABLED_BY_MATERIAL", {})),
    "LEAD_TIME_MULTIPLIER": copy.deepcopy(getattr(cfg, "LEAD_TIME_MULTIPLIER", {})),
    "LEAD_TIME_ENABLED": copy.deepcopy(getattr(cfg, "LEAD_TIME_ENABLED", {})),
    "DEFAULT_LEAD_TIME_DAYS": getattr(cfg, "DEFAULT_LEAD_TIME_DAYS", 21),
    "WEIGHT_MULTIPLIER_BY_MATERIAL": copy.deepcopy(getattr(cfg, "WEIGHT_MULTIPLIER_BY_MATERIAL", {})),
    "DENSITY_LB_PER_IN3": copy.deepcopy(getattr(cfg, "DENSITY_LB_PER_IN3", {})),
}


# ----------------------------
# DB Models
# ----------------------------
class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True)  # uuid4
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Human-friendly order number (1, 2, 3...) -> display as OP-0001, etc.
    order_number = Column(Integer, unique=True, index=True, nullable=True)

    # Customer identity (Supabase user id)
    customer_id = Column(String, index=True, nullable=True)

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


# single-row config table for knobs
class AppConfig(Base):
    __tablename__ = "app_config"

    id = Column(String, primary_key=True)  # "active"
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    config_json = Column(JSON, nullable=False)


def init_db() -> None:
    if not engine:
        return

    Base.metadata.create_all(bind=engine)

    # Lightweight “auto-migration” (best-effort)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_number INTEGER"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_orders_order_number ON orders(order_number)"))

        conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_id VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON orders(customer_id)"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app_config (
                    id VARCHAR PRIMARY KEY,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                    config_json JSONB NOT NULL
                )
                """
            )
        )


init_db()


# ----------------------------
# Helpers
# ----------------------------
def _db_required() -> None:
    if not SessionLocal:
        raise HTTPException(status_code=500, detail="DB not configured (missing DATABASE_URL).")


def _require_api_key(x_api_key: Optional[str] = Header(default=None, alias="x-api-key")) -> None:
    expected = (API_KEY or "").strip()
    provided = (x_api_key or "").strip()
    if expected and (not provided or provided != expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _require_admin_key(x_api_key: Optional[str] = Header(default=None, alias="x-api-key")) -> None:
    expected = (ADMIN_API_KEY or API_KEY or "").strip()
    provided = (x_api_key or "").strip()
    if expected and (not provided or provided != expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _send_email(to_email: str, subject: str, html: str) -> None:
    if not SENDGRID_API_KEY:
        return
    msg = Mail(from_email=FROM_EMAIL, to_emails=to_email, subject=subject, html_content=html)
    SendGridAPIClient(SENDGRID_API_KEY).send(msg)


def _format_order_number(n: Optional[int]) -> Optional[str]:
    if not n:
        return None
    return f"OP-{n:04d}"


def _assign_order_number(db, o: Order) -> None:
    if o.order_number:
        return

    for _ in range(6):
        next_num = (db.query(func.max(Order.order_number)).scalar() or 0) + 1
        o.order_number = int(next_num)
        try:
            db.commit()
            db.refresh(o)
            return
        except IntegrityError:
            db.rollback()
            o.order_number = None

    raise HTTPException(status_code=500, detail="Could not assign order number (please retry).")


def _decode_supabase_user_id_from_bearer(authorization: Optional[str]) -> Optional[str]:
    """
    Returns Supabase user id (sub) if Authorization: Bearer <jwt> is valid.
    Otherwise returns None.
    """
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None

    if not (_jwk_client and SUPABASE_JWT_ISSUER):
        return None

    try:
        header = jwt.get_unverified_header(token)
        alg = (header.get("alg") or "").upper()

        if alg not in {"RS256", "ES256"}:
            return None

        signing_key = _jwk_client.get_signing_key_from_jwt(token).key

        decoded = jwt.decode(
            token,
            signing_key,
            algorithms=[alg],
            audience=SUPABASE_JWT_AUD,
            issuer=SUPABASE_JWT_ISSUER,
            options={"verify_exp": True},
        )

        return decoded.get("sub")

    except Exception:
        return None


def _require_customer_user_id(
    authorization: Optional[str] = Header(default=None, alias="authorization"),
) -> str:
    user_id = _decode_supabase_user_id_from_bearer(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


def _api_key_or_customer_user_id(
    x_api_key: Optional[str] = Header(default=None, alias="x-api-key"),
    authorization: Optional[str] = Header(default=None, alias="authorization"),
) -> Optional[str]:
    """
    Allows either:
      - x-api-key (your current Streamlit quote UI), OR
      - Authorization: Bearer <supabase_jwt> (customer portal)
    Returns customer_user_id if bearer is valid, else None.
    Raises 401 if neither is valid.
    """
    expected = (API_KEY or "").strip()
    provided = (x_api_key or "").strip()
    if expected and provided == expected:
        return None

    user_id = _decode_supabase_user_id_from_bearer(authorization)
    if user_id:
        return user_id

    raise HTTPException(status_code=401, detail="Unauthorized")


# ----------------------------
# Knobs config helpers (seed + runtime apply)
# ----------------------------
def _baseline_price_per_sq_in_as_db_shape() -> dict[str, dict[str, float]]:
    """
    Convert file baseline PRICE_PER_SQ_IN (float keys) -> DB json shape (string keys).
    """
    out: dict[str, dict[str, float]] = {}
    base_ppsi = copy.deepcopy(_CFG_BASELINE.get("PRICE_PER_SQ_IN") or {})
    for m, tmap in (base_ppsi or {}).items():
        if not isinstance(tmap, dict):
            continue
        out[str(m)] = {str(float(t)): float(p) for t, p in tmap.items()}
    return out


def _default_knobs_config() -> dict:
    """
    Seed config stored in DB.
    NOTE: JSON keys must be strings, so thickness keys are stored as strings.
    """
    mats = copy.deepcopy(_CFG_BASELINE.get("MATERIAL_ENABLED") or {})
    if not mats:
        mats = {"304": True, "316": True, "Carbon Steel": True, "Monel": False, "Hastelloy": False}

    # Default: turn off Monel/Hastelloy unless you explicitly enable
    if "Monel" in mats:
        mats["Monel"] = False
    if "Hastelloy" in mats:
        mats["Hastelloy"] = False

    # Thickness availability stored as strings
    th_by_mat = copy.deepcopy(_CFG_BASELINE.get("THICKNESS_ENABLED_BY_MATERIAL") or {})
    th_by_mat_str: dict[str, dict[str, bool]] = {}
    for m, tmap in (th_by_mat or {}).items():
        if isinstance(tmap, dict):
            th_by_mat_str[str(m)] = {str(float(t)): bool(v) for t, v in tmap.items()}

    # Lead times stored as strings
    lt_enabled = copy.deepcopy(_CFG_BASELINE.get("LEAD_TIME_ENABLED") or {})
    if not lt_enabled and _CFG_BASELINE.get("LEAD_TIME_MULTIPLIER"):
        lt_enabled = {int(k): True for k in _CFG_BASELINE["LEAD_TIME_MULTIPLIER"].keys()}
    lt_enabled_str = {str(int(k)): bool(v) for k, v in (lt_enabled or {}).items()}

    # Price table stored with string thickness keys
    ppsi_str = _baseline_price_per_sq_in_as_db_shape()

    return {
        "material_enabled": {str(k): bool(v) for k, v in mats.items()},
        "thickness_enabled_by_material": th_by_mat_str,
        "lead_time_enabled": lt_enabled_str,
        "default_lead_time_days": int(_CFG_BASELINE.get("DEFAULT_LEAD_TIME_DAYS") or 21),
        "price_per_sq_in": ppsi_str,
        "weight_multiplier_by_material": {str(k): float(v) for k, v in (_CFG_BASELINE.get("WEIGHT_MULTIPLIER_BY_MATERIAL") or {}).items()},
        "density_lb_per_in3": {str(k): float(v) for k, v in (_CFG_BASELINE.get("DENSITY_LB_PER_IN3") or {}).items()},
        "updated_by": "system",
    }


def _get_or_seed_active_config(db) -> dict:
    row = db.query(AppConfig).filter(AppConfig.id == "active").first()
    if not row:
        row = AppConfig(id="active", config_json=_default_knobs_config())
        db.add(row)
        db.commit()
        db.refresh(row)
    return row.config_json if isinstance(row.config_json, dict) else _default_knobs_config()


def _restore_cfg_baseline() -> None:
    cfg.PRICE_PER_SQ_IN = copy.deepcopy(_CFG_BASELINE["PRICE_PER_SQ_IN"])
    cfg.MATERIAL_ENABLED = copy.deepcopy(_CFG_BASELINE["MATERIAL_ENABLED"])
    cfg.THICKNESS_ENABLED_BY_MATERIAL = copy.deepcopy(_CFG_BASELINE["THICKNESS_ENABLED_BY_MATERIAL"])
    cfg.LEAD_TIME_MULTIPLIER = copy.deepcopy(_CFG_BASELINE["LEAD_TIME_MULTIPLIER"])
    cfg.LEAD_TIME_ENABLED = copy.deepcopy(_CFG_BASELINE["LEAD_TIME_ENABLED"])
    cfg.DEFAULT_LEAD_TIME_DAYS = _CFG_BASELINE["DEFAULT_LEAD_TIME_DAYS"]
    cfg.WEIGHT_MULTIPLIER_BY_MATERIAL = copy.deepcopy(_CFG_BASELINE["WEIGHT_MULTIPLIER_BY_MATERIAL"])
    cfg.DENSITY_LB_PER_IN3 = copy.deepcopy(_CFG_BASELINE["DENSITY_LB_PER_IN3"])


def _apply_cfg_from_db_config(config_json: dict) -> None:
    """
    Apply DB knobs into cfg module so pricing_engine uses them immediately.

    IMPORTANT HARDENING:
    - If DB is missing/empty price_per_sq_in, we fall back to baseline price table
      so /quote doesn't 500 from an empty cfg.PRICE_PER_SQ_IN.
    """
    material_enabled = config_json.get("material_enabled") or {}
    th_enabled_by_mat = config_json.get("thickness_enabled_by_material") or {}
    lt_enabled = config_json.get("lead_time_enabled") or {}
    default_lt = config_json.get("default_lead_time_days")

    # Optional tables
    ppsi = config_json.get("price_per_sq_in") or {}
    if not isinstance(ppsi, dict) or not ppsi:
        ppsi = _baseline_price_per_sq_in_as_db_shape()

    wmult = config_json.get("weight_multiplier_by_material") or {}
    dens = config_json.get("density_lb_per_in3") or {}

    # Update cfg module fields used by pricing filtering logic
    cfg.MATERIAL_ENABLED = {str(k): bool(v) for k, v in material_enabled.items()}

    # Thickness enabled keys -> floats
    tebm: dict[str, dict[float, bool]] = {}
    for m, tmap in th_enabled_by_mat.items():
        tebm[str(m)] = {}
        if isinstance(tmap, dict):
            for t_str, enabled in tmap.items():
                try:
                    tebm[str(m)][float(t_str)] = bool(enabled)
                except Exception:
                    continue
    cfg.THICKNESS_ENABLED_BY_MATERIAL = tebm

    # Lead time enabled
    lte: dict[int, bool] = {}
    for d_str, enabled in lt_enabled.items():
        try:
            lte[int(d_str)] = bool(enabled)
        except Exception:
            continue
    cfg.LEAD_TIME_ENABLED = lte
    if isinstance(default_lt, int):
        cfg.DEFAULT_LEAD_TIME_DAYS = int(default_lt)

    # Apply optional densities / weight multipliers if provided
    if isinstance(dens, dict) and dens:
        cfg.DENSITY_LB_PER_IN3 = {str(k): float(v) for k, v in dens.items()}
    if isinstance(wmult, dict) and wmult:
        cfg.WEIGHT_MULTIPLIER_BY_MATERIAL = {str(k): float(v) for k, v in wmult.items()}

    # Apply prices (material -> thickness -> price), filtered by enabled material/thickness
    final_ppsi: dict[str, dict[float, float]] = {}
    for mat, tmap in ppsi.items():
        mat = str(mat)
        if not cfg.MATERIAL_ENABLED.get(mat, False):
            continue
        if not isinstance(tmap, dict):
            continue
        for t_str, price in tmap.items():
            try:
                t = float(t_str)
                p = float(price)
            except Exception:
                continue

            enabled_map = cfg.THICKNESS_ENABLED_BY_MATERIAL.get(mat)
            if isinstance(enabled_map, dict):
                # if thickness map exists, enforce it strictly
                if not enabled_map.get(t, False):
                    continue

            final_ppsi.setdefault(mat, {})[t] = p

    # If we somehow filtered everything out, fall back to baseline (still filtered by enabled)
    if not final_ppsi:
        base_ppsi = _baseline_price_per_sq_in_as_db_shape()
        for mat, tmap in base_ppsi.items():
            if not cfg.MATERIAL_ENABLED.get(mat, False):
                continue
            for t_str, price in (tmap or {}).items():
                try:
                    t = float(t_str)
                    p = float(price)
                except Exception:
                    continue
                enabled_map = cfg.THICKNESS_ENABLED_BY_MATERIAL.get(mat)
                if isinstance(enabled_map, dict) and not enabled_map.get(t, False):
                    continue
                final_ppsi.setdefault(mat, {})[t] = p

    cfg.PRICE_PER_SQ_IN = final_ppsi

    # Lead time multiplier: filter baseline master by enabled keys
    master_lt = copy.deepcopy(_CFG_BASELINE.get("LEAD_TIME_MULTIPLIER") or getattr(cfg, "LEAD_TIME_MULTIPLIER", {}))
    cfg.LEAD_TIME_MULTIPLIER = {int(d): float(master_lt[int(d)]) for d in cfg.LEAD_TIME_ENABLED.keys() if int(d) in master_lt}


def _calculate_quote_with_db_knobs(inputs: QuoteInputs) -> dict:
    """
    Loads active knobs from DB and applies them to cfg for the duration of this calculation.
    """
    _db_required()
    db = SessionLocal()
    try:
        active = _get_or_seed_active_config(db)
    finally:
        db.close()

    with _CFG_LOCK:
        _restore_cfg_baseline()
        _apply_cfg_from_db_config(active)
        try:
            return calculate_quote(inputs)
        finally:
            _restore_cfg_baseline()


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

    handle_label: str = Field(default="No label")
    chamfer_width: Optional[float] = Field(default=0.062)


class CheckoutCreateRequest(BaseModel):
    inputs: QuoteRequest


class CartCheckoutCreateRequest(BaseModel):
    items: List[QuoteRequest]


# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    return {"ok": True}


# Public: UI can fetch what is currently enabled without redeploy
@app.get("/config/active")
def get_active_config_public():
    _db_required()
    db = SessionLocal()
    try:
        active = _get_or_seed_active_config(db)
        return {
            "material_enabled": active.get("material_enabled") or {},
            "thickness_enabled_by_material": active.get("thickness_enabled_by_material") or {},
            "lead_time_enabled": active.get("lead_time_enabled") or {},
            "default_lead_time_days": active.get("default_lead_time_days") or 21,
        }
    finally:
        db.close()


from pydantic import ValidationError  # add near imports if missing

@app.post("/quote", dependencies=[Depends(_require_api_key)])
async def quote(request: Request):
    payload = await request.json()

    # ---- Normalize optional fields ----
    payload["handle_label"] = (payload.get("handle_label") or "").strip() or "No label"

    if payload.get("chamfer"):
        cw = payload.get("chamfer_width")
        if cw is None or cw == "":
            payload["chamfer_width"] = 0.062
    else:
        payload["chamfer_width"] = None

    try:
        inputs = QuoteInputs(**payload)
        return _calculate_quote_with_db_knobs(inputs)

    except ValidationError as e:
        # bad types / missing fields
        raise HTTPException(status_code=422, detail=str(e))

    except ValueError as e:
        # pricing_engine validation ("no price for thickness...", etc.)
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # unexpected
        raise HTTPException(status_code=500, detail=f"Unhandled quote error: {type(e).__name__}: {e}")



# ----------------------------
# Admin config endpoints
# ----------------------------
@app.get("/admin/config", dependencies=[Depends(_require_admin_key)])
def admin_get_config():
    _db_required()
    db = SessionLocal()
    try:
        active = _get_or_seed_active_config(db)
        return active
    finally:
        db.close()


@app.put("/admin/config", dependencies=[Depends(_require_admin_key)])
async def admin_put_config(request: Request):
    _db_required()
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Config must be a JSON object")

    # Light validation
    for k in ("material_enabled", "lead_time_enabled", "thickness_enabled_by_material", "price_per_sq_in"):
        if k in payload and payload[k] is not None and not isinstance(payload[k], dict):
            raise HTTPException(status_code=400, detail=f"{k} must be an object")

    if "default_lead_time_days" in payload:
        try:
            payload["default_lead_time_days"] = int(payload["default_lead_time_days"])
        except Exception:
            raise HTTPException(status_code=400, detail="default_lead_time_days must be an integer")

    payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    db = SessionLocal()
    try:
        row = db.query(AppConfig).filter(AppConfig.id == "active").first()
        if not row:
            row = AppConfig(id="active", config_json=payload)
            db.add(row)
        else:
            row.config_json = payload
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return {"ok": True, "config": row.config_json}
    finally:
        db.close()


@app.post("/admin/config/reset", dependencies=[Depends(_require_admin_key)])
def admin_reset_config():
    """
    Reset the DB 'active' config to the current file defaults (tuning_knobs.py baseline).
    This is the escape hatch when DB config gets out of sync / missing price tables.
    """
    _db_required()
    db = SessionLocal()
    try:
        fresh = _default_knobs_config()
        row = db.query(AppConfig).filter(AppConfig.id == "active").first()
        if not row:
            row = AppConfig(id="active", config_json=fresh)
            db.add(row)
        else:
            row.config_json = fresh
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
        return {"ok": True, "config": row.config_json}
    finally:
        db.close()


# ----------------------------
# Checkout endpoints
# ----------------------------
@app.post("/checkout/create")
def checkout_create(
    req: CheckoutCreateRequest,
    customer_user_id: Optional[str] = Depends(_api_key_or_customer_user_id),
):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe is not configured (missing STRIPE_SECRET_KEY).")

    inputs = QuoteInputs(**req.inputs.model_dump())
    result = _calculate_quote_with_db_knobs(inputs)

    total_cents = int(result.get("total_price_cents") or round(float(result["total_price"]) * 100))

    shipping = result.get("shipping") or {}
    missing = [k for k in ("ups_ground_cents", "ups_2day_cents", "ups_nextday_cents") if k not in shipping]
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing shipping fields from pricing engine: {', '.join(missing)}")

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
            "customer_id": customer_user_id or "",
        },
    )

    # Save "pending" order
    if SessionLocal:
        db = SessionLocal()
        try:
            existing = db.query(Order).filter(Order.stripe_session_id == session.id).first()
            if not existing:
                o = Order(
                    id=str(uuid.uuid4()),
                    stripe_session_id=session.id,
                    quote_payload=req.inputs.model_dump(),
                    customer_id=customer_user_id,
                )
                db.add(o)
                db.commit()
        finally:
            db.close()

    return {"checkout_url": session.url, "session_id": session.id}


@app.post("/checkout/cart/create")
def checkout_cart_create(
    req: CartCheckoutCreateRequest,
    customer_user_id: str = Depends(_require_customer_user_id),
):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe is not configured (missing STRIPE_SECRET_KEY).")

    if not req.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    total_items_cents = 0
    ship_ground_cents = 0
    ship_2day_cents = 0
    ship_nextday_cents = 0

    normalized_items = []

    for it in req.items:
        inputs = QuoteInputs(**it.model_dump())
        res = _calculate_quote_with_db_knobs(inputs)

        line_cents = int(res.get("total_price_cents") or round(float(res["total_price"]) * 100))
        total_items_cents += line_cents

        shipping = res.get("shipping") or {}
        ship_ground_cents += int(shipping.get("ups_ground_cents") or 0)
        ship_2day_cents += int(shipping.get("ups_2day_cents") or 0)
        ship_nextday_cents += int(shipping.get("ups_nextday_cents") or 0)

        normalized_items.append(it.model_dump())

    session = stripe.checkout.Session.create(
        mode="payment",
        success_url=f"{APP_BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{APP_BASE_URL}/cancel",
        shipping_address_collection={"allowed_countries": ["US"]},
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"O-Plates Quote Cart ({len(req.items)} items)"},
                    "unit_amount": int(total_items_cents),
                },
                "quantity": 1,
            }
        ],
        shipping_options=[
            {
                "shipping_rate_data": {
                    "type": "fixed_amount",
                    "fixed_amount": {"amount": int(ship_ground_cents), "currency": "usd"},
                    "display_name": "UPS Ground",
                    "metadata": {"service": "ups_ground"},
                }
            },
            {
                "shipping_rate_data": {
                    "type": "fixed_amount",
                    "fixed_amount": {"amount": int(ship_2day_cents), "currency": "usd"},
                    "display_name": "UPS 2nd Day Air",
                    "metadata": {"service": "ups_2day"},
                }
            },
            {
                "shipping_rate_data": {
                    "type": "fixed_amount",
                    "fixed_amount": {"amount": int(ship_nextday_cents), "currency": "usd"},
                    "display_name": "UPS Next Day Air",
                    "metadata": {"service": "ups_nextday"},
                }
            },
        ],
        metadata={
            "customer_id": customer_user_id,
            "is_cart": "true",
            "cart_count": str(len(req.items)),
        },
    )

    # Save "pending" order (cart payload)
    if SessionLocal:
        db = SessionLocal()
        try:
            existing = db.query(Order).filter(Order.stripe_session_id == session.id).first()
            if not existing:
                o = Order(
                    id=str(uuid.uuid4()),
                    stripe_session_id=session.id,
                    quote_payload={"cart_items": normalized_items},
                    customer_id=customer_user_id,
                )
                db.add(o)
                db.commit()
        finally:
            db.close()

    return {"checkout_url": session.url, "session_id": session.id}


# ----------------------------
# Orders endpoints + webhook (unchanged below)
# ----------------------------
@app.get("/orders/by-session/{session_id}")
def get_order_by_session(session_id: str):
    _db_required()
    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.stripe_session_id == session_id).first()
        if not o:
            raise HTTPException(status_code=404, detail="Order not found yet")

        return {
            "id": o.id,
            "order_number": o.order_number,
            "order_number_display": _format_order_number(o.order_number),
            "customer_email": o.customer_email,
            "amount_total_usd": (o.amount_total_cents or 0) / 100.0,
            "amount_subtotal_usd": (o.amount_subtotal_cents or 0) / 100.0,
            "amount_shipping_usd": (o.amount_shipping_cents or 0) / 100.0,
            "shipping_service": o.shipping_service,
            "shipping_name": o.shipping_name,
            "shipping_address": o.shipping_address,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
    finally:
        db.close()


@app.get("/me/orders")
def me_orders(customer_user_id: str = Depends(_require_customer_user_id), limit: int = 50):
    _db_required()
    limit = max(1, min(int(limit), 200))

    db = SessionLocal()
    try:
        orders = (
            db.query(Order)
            .filter(Order.customer_id == customer_user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "id": o.id,
                "order_number_display": _format_order_number(o.order_number),
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "customer_email": o.customer_email,
                "amount_total_usd": (o.amount_total_cents or 0) / 100.0,
                "amount_shipping_usd": (o.amount_shipping_cents or 0) / 100.0,
                "shipping_service": o.shipping_service,
            }
            for o in orders
        ]
    finally:
        db.close()


@app.get("/me/orders/{order_id}")
def me_order_detail(order_id: str, customer_user_id: str = Depends(_require_customer_user_id)):
    _db_required()
    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.id == order_id, Order.customer_id == customer_user_id).first()
        if not o:
            raise HTTPException(status_code=404, detail="Order not found")

        return {
            "id": o.id,
            "order_number_display": _format_order_number(o.order_number),
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "stripe_session_id": o.stripe_session_id,
            "stripe_payment_intent": o.stripe_payment_intent,
            "customer_email": o.customer_email,
            "amount_subtotal_usd": (o.amount_subtotal_cents or 0) / 100.0,
            "amount_shipping_usd": (o.amount_shipping_cents or 0) / 100.0,
            "amount_total_usd": (o.amount_total_cents or 0) / 100.0,
            "shipping_service": o.shipping_service,
            "shipping_name": o.shipping_name,
            "shipping_address": o.shipping_address,
            "quote_payload": o.quote_payload,
        }
    finally:
        db.close()


@app.get("/admin/orders", dependencies=[Depends(_require_admin_key)])
def admin_list_orders(q: Optional[str] = None, limit: int = 50):
    _db_required()
    limit = max(1, min(int(limit), 200))

    db = SessionLocal()
    try:
        query = db.query(Order).order_by(Order.created_at.desc())

        if q and q.strip():
            qq = q.strip()
            query = query.filter(
                or_(
                    Order.id.ilike(f"%{qq}%"),
                    Order.customer_email.ilike(f"%{qq}%"),
                    Order.stripe_session_id.ilike(f"%{qq}%"),
                )
            )

        orders = query.limit(limit).all()
        return [
            {
                "id": o.id,
                "order_number_display": _format_order_number(o.order_number),
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "customer_email": o.customer_email,
                "amount_total_usd": (o.amount_total_cents or 0) / 100.0,
                "amount_shipping_usd": (o.amount_shipping_cents or 0) / 100.0,
                "shipping_service": o.shipping_service,
                "shipping_name": o.shipping_name,
                "shipping_address": o.shipping_address,
            }
            for o in orders
        ]
    finally:
        db.close()


@app.get("/debug/whoami")
def debug_whoami(
    authorization: Optional[str] = Header(default=None, alias="authorization"),
):
    user_id = _decode_supabase_user_id_from_bearer(authorization)
    return {
        "has_auth_header": bool(authorization),
        "auth_starts_with_bearer": bool(authorization and authorization.lower().startswith("bearer ")),
        "user_id": user_id,
        "issuer": SUPABASE_JWT_ISSUER,
        "aud": SUPABASE_JWT_AUD,
        "jwks_url": SUPABASE_JWKS_URL,
        "jwks_configured": bool(_jwk_client),
    }


@app.get("/admin/orders/{order_id}", dependencies=[Depends(_require_admin_key)])
def admin_get_order(order_id: str):
    _db_required()
    db = SessionLocal()
    try:
        o = db.query(Order).filter(Order.id == order_id).first()
        if not o:
            raise HTTPException(status_code=404, detail="Order not found")

        return {
            "id": o.id,
            "order_number_display": _format_order_number(o.order_number),
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "stripe_session_id": o.stripe_session_id,
            "stripe_payment_intent": o.stripe_payment_intent,
            "customer_email": o.customer_email,
            "amount_subtotal_usd": (o.amount_subtotal_cents or 0) / 100.0,
            "amount_shipping_usd": (o.amount_shipping_cents or 0) / 100.0,
            "amount_total_usd": (o.amount_total_cents or 0) / 100.0,
            "shipping_service": o.shipping_service,
            "shipping_name": o.shipping_name,
            "shipping_address": o.shipping_address,
            "quote_payload": o.quote_payload,
            "customer_id": o.customer_id,
        }
    finally:
        db.close()


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook not configured (missing STRIPE_WEBHOOK_SECRET).")

    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"] or {}

        # Refresh from Stripe to ensure full details
        try:
            session = stripe.checkout.Session.retrieve(
                session.get("id"),
                expand=["shipping_cost.shipping_rate", "customer_details", "shipping_details"],
            )
        except Exception:
            pass

        stripe_session_id = session.get("id")
        payment_intent = session.get("payment_intent")

        customer_details = session.get("customer_details") or {}
        customer_email = customer_details.get("email")

        amount_total = session.get("amount_total")
        amount_subtotal = session.get("amount_subtotal")
        amount_shipping = ((session.get("shipping_cost") or {}).get("amount_total"))

        shipping_service = None
        try:
            shipping_cost = session.get("shipping_cost") or {}
            sr = shipping_cost.get("shipping_rate")
            if isinstance(sr, dict):
                shipping_service = (sr.get("metadata") or {}).get("service") or sr.get("display_name")
            else:
                shipping_rate_id = shipping_cost.get("shipping_rate")
                if shipping_rate_id:
                    sr2 = stripe.ShippingRate.retrieve(shipping_rate_id)
                    shipping_service = (sr2.get("metadata") or {}).get("service") or sr2.get("display_name")
        except Exception:
            shipping_service = None

        shipping_details = session.get("shipping_details") or {}
        shipping_name = shipping_details.get("name") or customer_details.get("name")
        shipping_address = shipping_details.get("address") or customer_details.get("address")

        # Pull customer_id from metadata if present (fallback)
        customer_id = (session.get("metadata") or {}).get("customer_id") or None

        if SessionLocal:
            db = SessionLocal()
            try:
                o = db.query(Order).filter(Order.stripe_session_id == stripe_session_id).first()
                if not o:
                    o = Order(id=str(uuid.uuid4()), stripe_session_id=stripe_session_id)
                    db.add(o)
                    db.commit()
                    db.refresh(o)

                if not o.customer_id and customer_id:
                    o.customer_id = customer_id

                o.stripe_payment_intent = payment_intent
                o.customer_email = customer_email
                o.amount_total_cents = amount_total
                o.amount_subtotal_cents = amount_subtotal
                o.amount_shipping_cents = amount_shipping
                o.shipping_name = shipping_name
                o.shipping_address = shipping_address
                o.shipping_service = shipping_service

                db.commit()
                db.refresh(o)

                _assign_order_number(db, o)
                order_display = _format_order_number(o.order_number) or "OP-????"
            finally:
                db.close()
        else:
            order_display = "OP-????"

        if customer_email:
            _send_email(
                to_email=customer_email,
                subject=f"O-Plates order received ({order_display})",
                html=f"""
                <p>Thanks — we received your order.</p>
                <p><b>Order #:</b> {order_display}</p>
                <p><b>Total Paid:</b> ${((amount_total or 0) / 100):.2f}</p>
                <p>We’ll email your approval drawing next.</p>
                """,
            )

    return {"ok": True}
