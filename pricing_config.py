# pricing_config.py

PRICE_PER_SQ_IN = {
    "304": {0.125: 0.220, 0.25: 0.425, 0.375: 0.460},
    "316": {0.125: 0.270, 0.25: 0.440, 0.375: 0.580},
    "Carbon Steel": {0.125: 0.090, 0.25: 0.100, 0.375: 0.130},
    "Monel": {0.125: 2.780, 0.25: 6.670},  # 0.375 optional/blank
    "Hastelloy": {0.125: 3.580, 0.25: 7.540, 0.375: 14.020},
}

LASER_PER_LINEAR_IN = 0.826

MILL_LABOR_PER_HR = 150
MILL_SPEED_IPM = 28
CHAMFER_SPEED_IPM = 28

LOAD_TIME_MINS = 6

INSPECTION_MINS_BY_TOL = {0.005: 6, 0.002: 12, 0.001: 18}

LEAD_TIME_MULTIPLIER = {7: 2.3, 14: 1.6, 21: 1.0}

# Quantity discounts (multiplier applied to UNIT price)
# Example: 5% off means multiplier = 0.95
QTY_DISCOUNT_TIERS = [
    {"min_qty": 1,   "multiplier": 1.00},
    {"min_qty": 5,   "multiplier": 0.97},  # 3% off
    {"min_qty": 10,  "multiplier": 0.95},  # 5% off
    {"min_qty": 25,  "multiplier": 0.92},  # 8% off
    {"min_qty": 50,  "multiplier": 0.90},  # 10% off
]
