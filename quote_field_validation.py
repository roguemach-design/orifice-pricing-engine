"""Customer field feedback using the existing quote and geometry constraints."""

import math

from drawing_intake.assisted_quote import _validation_errors, canonical_required_fields
from plate_geometry import PlateSpec, build_plate_geometry


def field_errors(values, availability):
    values = dict(values)
    errors = {}
    required = canonical_required_fields(chamfer=values.get("chamfer"))
    if values.get("handle_hole_enabled"):
        required += ["handle_hole_diameter", "handle_hole_center_from_handle_end"]
    for field in required:
        value = values.get(field)
        if value is None or value == "":
            errors[field] = "Required. Enter a value." if field not in {
                "material", "thickness", "bore_tolerance", "chamfer", "ships_in_days"
            } else "Required. Select an option."
        elif field not in {"material", "chamfer"} and (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            errors[field] = "Enter a finite number."
            values[field] = None
    values["handle_label"] = (values.get("handle_label") or "").strip() or "No label"
    for field, message in _validation_errors(values, availability).items():
        errors.setdefault(field, message)

    def conflict(fields, message):
        for field in fields:
            errors.setdefault(field, message)

    od, bore = values.get("paddle_dia"), values.get("bore_dia")
    width, length = values.get("handle_width"), values.get("handle_length_from_bore")
    if od is not None and bore is not None and bore >= od:
        conflict(("paddle_dia", "bore_dia"), "Bore diameter must be smaller than the outside diameter.")
    if od is not None and length is not None and length <= od / 2:
        conflict(("paddle_dia", "handle_length_from_bore"), "Handle length must extend beyond the plate radius.")
    if od is not None and width is not None and width >= od:
        conflict(("paddle_dia", "handle_width"), "Handle width must be smaller than the outside diameter.")
    if "handle_hole_diameter" in errors and values.get("handle_hole_enabled"):
        message = errors["handle_hole_diameter"]
        if "90%" in message:
            conflict(("handle_width",), message)
        elif "inside the handle end" in message or "rounded handle tip" in message:
            conflict(("handle_hole_center_from_handle_end",), message)
        elif "neck transition" in message:
            conflict(("handle_hole_center_from_handle_end", "handle_length_from_bore", "paddle_dia"), message)

    if not errors:
        try:
            # Reuse canonical validation; never clamp or alter customer dimensions.
            build_plate_geometry(PlateSpec.from_configuration(values))
        except ValueError as exc:
            message = str(exc)
            if "tolerance envelope" in message:
                conflict(("bore_dia", "bore_tolerance", "paddle_dia"), "Bore and tolerance must remain inside the plate.")
            elif "twice the corner radius" in message:
                conflict(("handle_width",), "Handle width must exceed 0.0625 in. for the existing corner radii.")
            elif "separate tangent" in message:
                conflict(("handle_length_from_bore", "handle_width", "paddle_dia"), "Handle is too short for the existing neck and tip radii.")
            else:
                conflict(("paddle_dia", "bore_dia", "handle_width", "handle_length_from_bore"), message)
    return errors
