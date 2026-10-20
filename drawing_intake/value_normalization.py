from __future__ import annotations

from fractions import Fraction

from .models import MeasurementUnit

MATERIAL_ALIASES = {
    "304": "304",
    "304 ss": "304",
    "ss 304": "304",
    "304 stainless": "304",
    "304 stainless steel": "304",
    "316": "316",
    "316 ss": "316",
    "ss 316": "316",
    "316 stainless": "316",
    "316 stainless steel": "316",
    "carbon steel": "Carbon Steel",
    "cs": "Carbon Steel",
    "mild steel": "Carbon Steel",
}


def parse_number(raw: str) -> float:
    text = raw.strip().replace(",", "")
    if " " in text and "/" in text:
        whole, fraction = text.split(None, 1)
        return float(whole) + float(Fraction(fraction))
    if "/" in text:
        return float(Fraction(text))
    return float(text)


def normalize_unit(raw: str | None) -> MeasurementUnit | None:
    if not raw:
        return None
    token = raw.strip().lower().replace(".", "")
    if token in {'"', "in", "inch", "inches"}:
        return MeasurementUnit.INCH
    if token in {"mm", "millimeter", "millimeters", "millimetre", "millimetres"}:
        return MeasurementUnit.MILLIMETER
    if token in {"deg", "degree", "degrees", "°"}:
        return MeasurementUnit.DEGREE
    return None


def normalize_material(raw: str) -> str:
    compact = " ".join(raw.strip().lower().replace("-", " ").split())
    return MATERIAL_ALIASES.get(compact, raw.strip())


def to_inches(value: float, unit: MeasurementUnit | str | None) -> float:
    if unit == MeasurementUnit.MILLIMETER or unit == MeasurementUnit.MILLIMETER.value:
        return value / 25.4
    return value
