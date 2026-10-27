"""Pricing estimates only: never generates toolpaths or grants fulfillment eligibility."""
from math import pi
from types import SimpleNamespace
from plate_geometry import rough_bore_diameter

MODEL_VERSION = "diameter-allowances-2026-10"
TODAY_2_DAY_ID = "today_2_day"
TODAY_2_DAY_LABEL = "Today / 2-Day"
SPRING_PASSES = {0.005: 0, 0.002: 1, 0.001: 2}


def machining_costs(x, cfg):
    rough = rough_bore_diameter(SimpleNamespace(
        finished_bore_diameter=x.bore_dia, bore_tolerance=x.bore_tolerance))
    # Two rough contours and one finish contour split the nominal stock evenly.
    # Part-contour estimates, not measured cycles or cutter-center toolpaths.
    stock = x.bore_dia - rough
    contours = [rough + stock / 3, rough + 2 * stock / 3, x.bore_dia]
    contours += [x.bore_dia] * SPRING_PASSES[x.bore_tolerance]
    bore_minutes = sum(pi * diameter for diameter in contours) / cfg.MILL_SPEED_IPM
    bore_time_cost = bore_minutes * cfg.MILL_LABOR_PER_HR / 60
    bore_allowance = x.bore_dia * cfg.PRECISION_BORE_ALLOWANCE_PER_IN
    if x.chamfer and x.chamfer_width is None:
        raise ValueError("chamfer_width is required for chamfer pricing")
    # One nominal chamfer contour at its mean diameter. Tool/face access and
    # single-pass capability require owner confirmation before production adoption.
    # No second setup/load or unverified flip time is silently charged.
    chamfer_minutes = (pi * (x.bore_dia + x.chamfer_width) / cfg.CHAMFER_SPEED_IPM
                       if x.chamfer else 0.0)
    chamfer_time_cost = chamfer_minutes * cfg.MILL_LABOR_PER_HR / 60
    chamfer_allowance = x.bore_dia * cfg.CHAMFER_ALLOWANCE_PER_IN if x.chamfer else 0.0
    return dict(
        pricing_model_version=MODEL_VERSION,
        rough_bore_diameter_in=rough,
        bore_pass_count=len(contours),
        bore_spring_passes=SPRING_PASSES[x.bore_tolerance],
        bore_contour_diameters_in=contours,
        bore_machining_minutes=bore_minutes,
        bore_time_cost=bore_time_cost,
        precision_bore_allowance=bore_allowance,
        machine_bore_cost=bore_time_cost + bore_allowance,
        chamfer_pass_count=1 if x.chamfer else 0,
        chamfer_machining_minutes=chamfer_minutes,
        chamfer_time_cost=chamfer_time_cost,
        chamfer_diameter_allowance=chamfer_allowance,
        chamfer_bore_cost=chamfer_time_cost + chamfer_allowance,
        additional_chamfer_setup_cost=0.0,
        chamfer_method_confirmation_required=bool(x.chamfer),
    )


def future_rush_eligibility(*, material_ready=False, blank_ready=False,
                            capacity_confirmed=False, cutoff_confirmed=False,
                            method_qualified=False, shipment_window_confirmed=False):
    readiness = dict(material_ready=material_ready, blank_ready=blank_ready,
                     capacity_confirmed=capacity_confirmed, cutoff_confirmed=cutoff_confirmed,
                     method_qualified=method_qualified,
                     shipment_window_confirmed=shipment_window_confirmed)
    if any(type(value) is not bool for value in readiness.values()):
        raise ValueError("Future eligibility evidence requires boolean confirmations")
    return dict(service_id=TODAY_2_DAY_ID, label=TODAY_2_DAY_LABEL,
                eligible=False, available=False, status="Coming Soon",
                readiness_requirements_met=all(readiness.values()),
                blockers=["Separate owner activation is required"]
                         + [name for name, ready in readiness.items() if not ready])


def simulate_future_rush(subtotal, quantity, quantity_multiplier, multiplier):
    """Offline simulation; no customer route accepts this service identifier."""
    unit = round(subtotal * multiplier * quantity_multiplier, 2)
    return dict(service_id=TODAY_2_DAY_ID, label=TODAY_2_DAY_LABEL,
                available=False, multiplier=multiplier, unit_price=unit,
                total_price=round(unit * quantity, 2))
