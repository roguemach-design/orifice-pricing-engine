# tuning_knobs.py
"""
TUNING KNOBS (EDIT THIS FILE)

This is the ONLY file you should need to edit to tune pricing + availability.
"""

# ============================================================
# 1) MATERIAL + THICKNESS PRICING ($/sq in)
# ============================================================
PRICE_PER_SQ_IN = {
    "304": {
        0.120: 0.1302,   # 11ga approx
        0.250: 0.2564,
        0.375: 0.3814,
        0.500: 0.6307,
    },
    "316": {
        0.120: 0.1868,   # 11ga approx
        0.250: 0.3763,
        0.375: 0.5710,
        0.500: 0.8773,
    },
    "Carbon Steel": {
        0.120: 0.04785,  # 11ga approx
        0.250: 0.07444,
        0.375: 0.11065,
        0.500: 0.15030,
    },
}

# Use density math for weight, but correct stainless upward
WEIGHT_MULTIPLIER_BY_MATERIAL = {
    "304": 1.06,
    "316": 1.06,
    "Carbon Steel": 1.00,
}

# ============================================================
# 2) MATERIAL + THICKNESS AVAILABILITY TOGGLES
# ============================================================

MATERIAL_ENABLED = {
    "304": True,
    "316": True,
    "Carbon Steel": True,
    "Monel": False,
    "Hastelloy": False,
}

# Optional: thickness enable/disable per material
# If omitted, thickness is assumed enabled if it exists in PRICE_PER_SQ_IN.
THICKNESS_ENABLED_BY_MATERIAL = {
    "304": {0.125: True, 0.25: True, 0.375: True, 0.5: True},
    "316": {0.125: True, 0.25: True, 0.375: True, 0.5: True},
    "Carbon Steel": {0.125: True, 0.25: True, 0.375: True, 0.5: True},
    "Monel": {0.125: True, 0.25: True, 0.5: False},       # example: keep 1/2 OFF
    "Hastelloy": {0.125: True, 0.25: True, 0.375: True, 0.5: True},
}

def _is_thickness_enabled(material: str, thickness: float) -> bool:
    # material must be enabled
    if not MATERIAL_ENABLED.get(material, False):
        return False

    # if not explicitly listed, assume True (as long as price exists)
    enabled_map = THICKNESS_ENABLED_BY_MATERIAL.get(material)
    if enabled_map is None:
        return True

    return bool(enabled_map.get(thickness, False))


# Filter PRICE_PER_SQ_IN based on toggles
_filtered_price = {}
for mat, tmap in PRICE_PER_SQ_IN.items():
    if not MATERIAL_ENABLED.get(mat, False):
        continue
    filtered_th = {t: p for t, p in tmap.items() if _is_thickness_enabled(mat, t)}
    if filtered_th:
        _filtered_price[mat] = filtered_th

PRICE_PER_SQ_IN = _filtered_price

# ============================================================
# 3) DENSITY (for shipping weight)
# ============================================================
DENSITY_LB_PER_IN3 = {
    "304": 0.289,
    "316": 0.289,
    "Carbon Steel": 0.283,
    "Monel": 0.319,
    "Hastelloy": 0.322,
}

# ============================================================
# 4) PROCESS COSTS / RATES
# ============================================================
LASER_PER_LINEAR_IN = 0.826

MILL_LABOR_PER_HR = 150
MILL_SPEED_IPM = 28
CHAMFER_SPEED_IPM = 28

LOAD_TIME_MINS = 6

INSPECTION_MINS_BY_TOL = {
    0.005: 6,
    0.002: 12,
    0.001: 18,
}

# ============================================================
# 5) LEAD TIMES (multiplier-based) + TOGGLES
# ============================================================
LEAD_TIME_PRESET = "normal"  # "normal", "no_rush", "rush_only"

LEAD_TIME_MULTIPLIER_MASTER = {
    7: 2.3,
    14: 1.6,
    21: 1.0,
}

LEAD_TIME_PRESETS = {
    "normal":   {7: True,  14: True,  21: True},
    "no_rush":  {7: False, 14: True,  21: True},
    "rush_only":{7: True,  14: False, 21: False},
}

LEAD_TIME_ENABLED = LEAD_TIME_PRESETS.get(LEAD_TIME_PRESET, {7: True, 14: True, 21: True})

LEAD_TIME_MULTIPLIER = {
    days: mult
    for days, mult in LEAD_TIME_MULTIPLIER_MASTER.items()
    if LEAD_TIME_ENABLED.get(days, False)
}

DEFAULT_LEAD_TIME_DAYS = 21

# ============================================================
# 6) QUANTITY DISCOUNTS
# ============================================================
QTY_DISCOUNT_TIERS = [
    {"min_qty": 1,   "multiplier": 1.00},
    {"min_qty": 5,   "multiplier": 0.97},
    {"min_qty": 10,  "multiplier": 0.95},
    {"min_qty": 25,  "multiplier": 0.92},
    {"min_qty": 50,  "multiplier": 0.90},
]

