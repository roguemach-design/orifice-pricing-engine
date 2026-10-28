"""Validation and editor projection for the single authoritative app_config row.

Projection adds existing code defaults in memory only; reading never saves them.
"""

import copy
import hashlib
import json
import math

PROCESS_KEYS = (
    "laser_per_linear_in",
    "precision_bore_allowance_per_in",
    "chamfer_allowance_per_in",
    "today_2_day_multiplier",
    "mill_labor_per_hr",
    "mill_speed_ipm",
    "chamfer_speed_ipm",
    "load_time_mins",
    "inspection_mins_by_tol",
    "qty_discount_tiers",
)


def project(active, baseline):
    result = copy.deepcopy(active)
    for key in PROCESS_KEYS:
        value = copy.deepcopy(baseline[key.upper()])
        if isinstance(value, dict):
            value = {str(k): v for k, v in value.items()}
        result.setdefault(key, value)
    multipliers = result.setdefault("lead_time_multipliers", {})
    for days, multiplier in baseline.get("LEAD_TIME_MULTIPLIER_MASTER", baseline["LEAD_TIME_MULTIPLIER"]).items():
        multipliers.setdefault(str(days), multiplier)
    return result


def version(row):
    raw = json.dumps(
        row.config_json, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256((str(row.updated_at) + raw).encode()).hexdigest()


def changes(before, after, prefix=""):
    rows = []
    for key in sorted(set(before) | set(after)):
        if key in ("updated_at", "updated_by"):
            continue
        a, b = before.get(key), after.get(key)
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(a, dict) and isinstance(b, dict):
            rows.extend(changes(a, b, path))
        elif a != b:
            rows.append({"setting": path, "before": a, "after": b})
    return rows


def validate(value, defaults):
    if not isinstance(value, dict):
        raise ValueError("Configuration must be an object.")
    required = set(defaults) - {"updated_by", "updated_at"}
    if required - set(value):
        raise ValueError(
            "Incomplete configuration: " + ", ".join(sorted(required - set(value)))
        )
    if set(value) - set(defaults) - {"updated_at"}:
        raise ValueError("Unknown configuration fields.")

    def number(n, name, *, positive=False, integer=False):
        if (
            type(n) not in (int, float)
            or not math.isfinite(n)
            or n < 0
            or (positive and n == 0)
        ):
            raise ValueError(
                f'{name} must be a finite {"positive" if positive else "nonnegative"} number.'
            )
        if n > 1_000_000:
            raise ValueError(f"{name} exceeds the supported numeric range.")
        if integer and type(n) is not int:
            raise ValueError(f"{name} must be an integer.")

    def mapping(name):
        m = value[name]
        if not isinstance(m, dict) or not m:
            raise ValueError(f"{name} must be a nonempty object.")
        return m

    def bools(m, name):
        if any(type(v) is not bool for v in m.values()):
            raise ValueError(f"{name} requires true/false values.")

    mats = mapping("material_enabled")
    if set(mats) != set(defaults["material_enabled"]):
        raise ValueError("Material catalog cannot be changed here.")
    bools(mats, "Material availability")
    thickness = mapping("thickness_enabled_by_material")
    prices = mapping("price_per_sq_in")
    if set(thickness) != set(defaults["thickness_enabled_by_material"]):
        raise ValueError("Thickness catalog must remain complete.")
    for material, entries in thickness.items():
        if material not in mats or not isinstance(entries, dict) or not entries:
            raise ValueError("Invalid thickness catalog.")
        if set(entries) != set(defaults["thickness_enabled_by_material"][material]):
            raise ValueError("Thickness catalog must remain complete.")
        bools(entries, "Thickness availability")
        for t in entries:
            if t not in defaults["thickness_enabled_by_material"].get(material, {}):
                raise ValueError("Unsupported thickness.")
    for material, entries in prices.items():
        if material not in mats or not isinstance(entries, dict) or not entries:
            raise ValueError("Invalid price table.")
        for t, p in entries.items():
            if t not in thickness.get(material, {}):
                raise ValueError("Price requires a supported thickness.")
            number(p, "Material price")
    for name in ("density_lb_per_in3", "weight_multiplier_by_material"):
        entries = mapping(name)
        if set(entries) - set(mats):
            raise ValueError("Unknown material in " + name)
        for v in entries.values():
            number(v, name, positive=True)
    for material, enabled in mats.items():
        if not enabled:
            continue
        available = [t for t, on in thickness.get(material, {}).items() if on]
        if not available or any(t not in prices.get(material, {}) for t in available):
            raise ValueError(f"{material} needs a price for every enabled thickness.")
        if material not in value["density_lb_per_in3"]:
            raise ValueError(f"{material} needs a density.")
    leads = mapping("lead_time_enabled")
    bools(leads, "Lead-time availability")
    if set(leads) != set(defaults["lead_time_enabled"]):
        raise ValueError("Lead-time catalog cannot be changed here.")
    multipliers = mapping("lead_time_multipliers")
    if set(multipliers) != set(defaults["lead_time_multipliers"]):
        raise ValueError("Unsupported lead-time multiplier catalog.")
    for v in multipliers.values():
        number(v, "Lead-time multiplier", positive=True)
    if any(on and d not in multipliers for d, on in leads.items()):
        raise ValueError("Enabled lead time has no supported multiplier.")
    number(
        value["default_lead_time_days"],
        "Default lead time",
        positive=True,
        integer=True,
    )
    if not leads.get(str(value["default_lead_time_days"]), False):
        raise ValueError("Default lead time must be enabled.")
    for name in (
        "max_paddle_dia_in",
        "max_bore_dia_in",
        "mill_speed_ipm",
        "chamfer_speed_ipm",
    ):
        number(value[name], name, positive=True)
    if value["max_bore_dia_in"] >= value["max_paddle_dia_in"]:
        raise ValueError("Maximum bore must be smaller than maximum plate diameter.")
    number(
        value["max_handle_label_chars"], "Marking length", positive=True, integer=True
    )
    for name in ("laser_per_linear_in", "mill_labor_per_hr", "load_time_mins",
                 "precision_bore_allowance_per_in", "chamfer_allowance_per_in"):
        number(value[name], name)
    number(value["today_2_day_multiplier"], "Today / 2-Day multiplier", positive=True)
    inspection = mapping("inspection_mins_by_tol")
    if set(inspection) != set(defaults["inspection_mins_by_tol"]):
        raise ValueError("Inspection tolerance catalog must remain complete.")
    for v in inspection.values():
        number(v, "Inspection minutes")
    tiers = value["qty_discount_tiers"]
    if not isinstance(tiers, list) or not tiers:
        raise ValueError("Quantity tiers must be a nonempty list.")
    last_qty, last_mult = 0, 1.0
    for tier in tiers:
        if not isinstance(tier, dict) or set(tier) != {"min_qty", "multiplier"}:
            raise ValueError("Invalid quantity tier.")
        number(tier["min_qty"], "Minimum quantity", positive=True, integer=True)
        number(tier["multiplier"], "Quantity multiplier", positive=True)
        if tier["min_qty"] <= last_qty or tier["multiplier"] > last_mult:
            raise ValueError(
                "Tiers require increasing quantities and nonincreasing discounts at most 1."
            )
        last_qty, last_mult = tier["min_qty"], tier["multiplier"]
    if tiers[0]["min_qty"] != 1:
        raise ValueError("Quantity tiers must start at one.")
    return copy.deepcopy(value)
