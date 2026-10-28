"""Delivery names only. Never used for object keys or generated artifact names."""

from decimal import Decimal, InvalidOperation
import re

MATERIALS = {
    "304": "304",
    "304 SS": "304",
    "304 Stainless": "304",
    "304 Stainless Steel": "304",
    "316": "316",
    "316 SS": "316",
    "316 Stainless": "316",
    "316 Stainless Steel": "316",
    "CS": "CS",
    "Carbon Steel": "CS",
    "carbon": "CS",
}


def dxf_delivery_name(spec, order_number, line_id, revision):
    material = {k.casefold(): v for k, v in MATERIALS.items()}.get(
        str(spec.get("material", "")).casefold()
    )
    order = re.fullmatch(r"OP-([0-9]{4,})", str(order_number))
    line = re.fullmatch(r"line-([1-9][0-9]*)", str(line_id))
    if (
        not material
        or not order
        or not line
        or type(revision) is not int
        or revision < 1
    ):
        raise ValueError("Authoritative delivery name unavailable")
    try:
        thickness = Decimal(str(spec["thickness"]))
    except (KeyError, InvalidOperation, ValueError):
        raise ValueError("Canonical thickness unavailable") from None
    if not thickness.is_finite() or not Decimal("0") < thickness <= Decimal("100"):
        raise ValueError("Canonical thickness unavailable")
    # At least three places, without rounding away canonical precision.
    places = max(3, -thickness.normalize().as_tuple().exponent)
    if places > 12:
        raise ValueError("Canonical thickness precision unavailable")
    token = f"{thickness:.{places}f}"
    if token.startswith("0."):
        token = token[1:]
    return f"OP-{material}-{token}-OP{order[1]}-L{int(line[1]):02d}-R{revision}.dxf"
