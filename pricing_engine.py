# pricing_engine.py
from typing import Dict, Any, Optional
import math

from pydantic import BaseModel, Field

import pricing_config as cfg


class QuoteInputs(BaseModel):
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

    # --- New fields ---
    handle_label: str = Field(default="No label")
    chamfer_width: Optional[float] = None


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _qty_multiplier(qty: int) -> float:
    tiers = sorted(cfg.QTY_DISCOUNT_TIERS, key=lambda t: t["min_qty"])
    multiplier = tiers[0]["multiplier"]

    for tier in tiers:
        if qty >= tier["min_qty"]:
            multiplier = tier["multiplier"]
        else:
            break

    return multiplier


def _ups_rule_shipping_cents(
    weight_lb: float,
    length_in: float,
    width_in: float,
    height_in: float,
) -> Dict[str, int]:
    """
    Rule-based UPS-style shipping estimator.
    Uses your existing package + weight outputs.
    Tunable constants below.
    """

    # UPS-style dimensional weight (inches / lb)
    DIM_DIVISOR = 139.0
    dim_weight = (length_in * width_in * height_in) / DIM_DIVISOR

    # Billable weight: round up to next whole lb
    billable_weight = math.ceil(max(weight_lb, dim_weight, 1.0))

    # Base pricing model (tune these freely)
    ground_base = 12.00
    ground_per_lb = 0.95

    ground = ground_base + (ground_per_lb * billable_weight)
    two_day = ground * 1.85
    next_day = ground * 2.85

    return {
        "ups_ground_cents": int(round(ground * 100)),
        "ups_2day_cents": int(round(two_day * 100)),
        "ups_nextday_cents": int(round(next_day * 100)),
    }


def calculate_quote(x: QuoteInputs) -> Dict[str, Any]:
    # ---- Validation ----
    _require(x.quantity >= 1, "quantity must be >= 1")
    _require(x.material in cfg.PRICE_PER_SQ_IN, f"unknown material: {x.material}")
    _require(
        x.thickness in cfg.PRICE_PER_SQ_IN[x.material],
        f"no price for thickness {x.thickness} in material {x.material}",
    )
    _require(
        x.bore_tolerance in cfg.INSPECTION_MINS_BY_TOL,
        f"unsupported bore tolerance: {x.bore_tolerance}",
    )
    _require(
        x.ships_in_days in cfg.LEAD_TIME_MULTIPLIER,
        f"unsupported ships_in_days: {x.ships_in_days}",
    )

    # ---- Geometry ----
    paddle_radius = x.paddle_dia / 2
    area_sq_in = x.paddle_dia * (x.handle_length_from_bore + paddle_radius)

    linear_inches = (
        x.handle_width
        + (x.handle_length_from_bore * 2)
        + (paddle_radius * 3.14)
    )

    # ---- Costs ----
    material_cost = area_sq_in * cfg.PRICE_PER_SQ_IN[x.material][x.thickness]
    laser_cost = linear_inches * cfg.LASER_PER_LINEAR_IN

    machine_bore_cost = (
        (3.14 * x.bore_dia) * (cfg.MILL_LABOR_PER_HR / cfg.MILL_SPEED_IPM)
    ) * 2

    chamfer_bore_cost = (
        ((3.14 * x.bore_dia) * (cfg.MILL_LABOR_PER_HR / cfg.CHAMFER_SPEED_IPM)) * 2
        if x.chamfer
        else 0
    )

    load_cost = (cfg.MILL_LABOR_PER_HR / 60) * cfg.LOAD_TIME_MINS
    insp_mins = cfg.INSPECTION_MINS_BY_TOL[x.bore_tolerance]
    inspection_cost = (cfg.MILL_LABOR_PER_HR / 60) * insp_mins

    subtotal = (
        material_cost
        + laser_cost
        + machine_bore_cost
        + chamfer_bore_cost
        + load_cost
        + inspection_cost
    )

    multiplier = cfg.LEAD_TIME_MULTIPLIER[x.ships_in_days]
    unit_price = subtotal * multiplier
    qty_mult = _qty_multiplier(x.quantity)
    unit_price_discounted = unit_price * qty_mult
    total_price = unit_price_discounted * x.quantity

    # =========================
    # Shipping (your rules)
    # =========================
    product_len_in = x.handle_length_from_bore + paddle_radius
    product_w_in = x.paddle_dia

    pkg_len_in = product_len_in + 4.0
    pkg_w_in = product_w_in + 4.0
    pkg_h_in = 1.0 + (max(x.quantity - 1, 0) * x.thickness)

    density = cfg.DENSITY_LB_PER_IN3[x.material]
    unit_weight_lb = area_sq_in * x.thickness * density
    total_weight_lb = unit_weight_lb * x.quantity

    shipping_rates = _ups_rule_shipping_cents(
        weight_lb=total_weight_lb,
        length_in=pkg_len_in,
        width_in=pkg_w_in,
        height_in=pkg_h_in,
    )

    # =========================
    # Final result
    # =========================
    return {
        "area_sq_in": round(area_sq_in, 4),
        "linear_inches": round(linear_inches, 4),
        "material_cost": round(material_cost, 2),
        "laser_cost": round(laser_cost, 2),
        "machine_bore_cost": round(machine_bore_cost, 2),
        "chamfer_bore_cost": round(chamfer_bore_cost, 2),
        "load_cost": round(load_cost, 2),
        "inspection_cost": round(inspection_cost, 2),
        "subtotal_pre_multiplier": round(subtotal, 2),
        "lead_time_multiplier": multiplier,
        "unit_price_pre_qty_discount": round(unit_price, 2),
        "qty_discount_multiplier": qty_mult,
        "unit_price": round(unit_price_discounted, 2),
        "quantity": x.quantity,
        "total_price": round(total_price, 2),

        # --- Shipping outputs ---
        "estimated_unit_weight_lb": round(unit_weight_lb, 2),
        "estimated_total_weight_lb": round(total_weight_lb, 2),
        "estimated_package_in": {
            "length": round(pkg_len_in, 2),
            "width": round(pkg_w_in, 2),
            "height": round(pkg_h_in, 2),
        },
        "shipping": shipping_rates,

        # --- New inputs echoed back (optional but helpful for debugging/UI) ---
        "handle_label": x.handle_label,
        "chamfer_width": x.chamfer_width,
    }
