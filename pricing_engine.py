# pricing_engine.py
from dataclasses import dataclass
from typing import Dict, Any

import pricing_config as cfg


@dataclass(frozen=True)
class QuoteInputs:
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


def calculate_quote(x: QuoteInputs) -> Dict[str, Any]:
    # ---- Basic validation ----
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

    # ---- Geometry (matches your Excel logic) ----
    paddle_radius = x.paddle_dia / 2
    area_sq_in = x.paddle_dia * (x.handle_length_from_bore + paddle_radius)

    # Linear inches (Excel used 3.14)
    linear_inches = (
        x.handle_width
        + (x.handle_length_from_bore * 2)
        + (paddle_radius * 3.14)
    )

    # ---- Costs (pre-multiplier) ----
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
    # Shipping estimates
    # =========================

    # Product footprint
    product_len_in = x.handle_length_from_bore + paddle_radius
    product_w_in = x.paddle_dia

    # Packaging rules (+4" L/W)
    pkg_len_in = product_len_in + 4.0
    pkg_w_in = product_w_in + 4.0

    # Height rule:
    # 1" base for qty=1, then + thickness for each additional piece
    pkg_h_in = 1.0 + (max(x.quantity - 1, 0) * x.thickness)

    # Weight
    density = cfg.DENSITY_LB_PER_IN3[x.material]
    unit_weight_lb = area_sq_in * x.thickness * density
    total_weight_lb = unit_weight_lb * x.quantity

    breakdown = {
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

        # --- Shipping outputs (Shopify-ready) ---
        "estimated_unit_weight_lb": round(unit_weight_lb, 2),
        "estimated_total_weight_lb": round(total_weight_lb, 2),
        "estimated_package_in": {
            "length": round(pkg_len_in, 2),
            "width": round(pkg_w_in, 2),
            "height": round(pkg_h_in, 2),
        },
    }

    return breakdown


if __name__ == "__main__":
    inputs = QuoteInputs(
        quantity=1,
        material="304",
        thickness=0.25,
        handle_width=2,
        handle_length_from_bore=18,
        paddle_dia=6,
        bore_dia=2,
        bore_tolerance=0.005,
        chamfer=True,
        ships_in_days=21,
    )

    result = calculate_quote(inputs)
    print("UNIT:", result["unit_price"])
    print("TOTAL:", result["total_price"])
    print("WEIGHT:", result["estimated_total_weight_lb"])
    print("PKG:", result["estimated_package_in"])
