from __future__ import annotations

import re
from enum import Enum

from pydantic import Field

from .models import MeasurementUnit, StrictModel
from .value_normalization import normalize_material, normalize_unit, parse_number


class NormalizedEngineeringText(StrictModel):
    raw_text: str
    normalized_text: str
    normalization_rules: list[str] = Field(default_factory=list)


class ParsedMeasurement(StrictModel):
    value: float
    unit: MeasurementUnit | None = None
    explicit_unit: bool = False
    raw_text: str
    normalized_text: str
    normalization_rules: list[str] = Field(default_factory=list)


class ToleranceKind(str, Enum):
    SYMMETRIC = "symmetric"
    BILATERAL = "bilateral"
    UNILATERAL = "unilateral"
    LIMITS = "limits"


class ParsedTolerance(StrictModel):
    kind: ToleranceKind
    plus: float | None = None
    minus: float | None = None
    upper_limit: float | None = None
    lower_limit: float | None = None
    unit: MeasurementUnit | None = None
    raw_text: str
    normalized_text: str
    normalization_rules: list[str] = Field(default_factory=list)


class ParsedChamfer(StrictModel):
    width_or_depth: float
    dimension_unit: MeasurementUnit | None = None
    angle_degrees: float
    raw_text: str
    normalized_text: str
    normalization_rules: list[str] = Field(default_factory=list)


_NUMBER = r"(?:\d+\s+\d+\s*/\s*\d+|\d+\s*/\s*\d+|(?:\d+(?:\.\d*)?|\.\d+))"


def normalize_engineering_text(
    raw: str,
    *,
    numeric_context: bool = False,
    tolerance_context: bool = False,
    thickness_context: bool = False,
) -> NormalizedEngineeringText:
    text = raw.strip()
    rules: list[str] = []

    translated = text.translate(
        str.maketrans(
            {
                "“": '"',
                "”": '"',
                "″": '"',
                "’": "'",
                "′": "'",
                "º": "°",
                "⌀": "Ø",
                "∅": "Ø",
                "—": "-",
                "–": "-",
            }
        )
    )
    if translated != text:
        rules.append("unicode_engineering_symbol_normalization")
    text = translated.upper()

    if "Ø" in text:
        text = text.replace("Ø", " DIA ")
        rules.append("diameter_symbol_to_dia")
    if "°" in text:
        text = text.replace("°", " DEG ")
        rules.append("degree_symbol_to_deg")

    if tolerance_context:
        repaired = re.sub(r"(?<=\d),(?=\d{1,4}(?:\D|$))", ".", text)
        if repaired != text:
            text = repaired
            rules.append("decimal_comma_in_tolerance_context")

    if thickness_context:
        repaired = re.sub(
            r"(?<![A-Z0-9])[¥YV%]{1,2}\s*([248])(?=\s*(?:\"|IN|THK|THICK|$))",
            r"1/\1",
            text,
        )
        if repaired != text:
            text = repaired
            rules.append("ocr_compact_fraction_slash_repair_in_thickness_context")
        repaired = re.sub(
            r"(?<![\d./])1\s*([248])(?=\s*(?:\"|IN|$))",
            r"1/\1",
            text,
        )
        if repaired != text:
            text = repaired
            rules.append("ocr_missing_fraction_slash_repair_in_thickness_context")

    if numeric_context:
        compact = re.sub(r"[\s\"']", "", text)
        if re.fullmatch(r"[OIL\d.,+\-/]+", compact):
            repaired = text.replace("O", "0").replace("I", "1").replace("L", "1")
            if repaired != text:
                text = repaired
                rules.append("ocr_alphanumeric_to_numeric_in_numeric_context")
        repaired = re.sub(r"(?<=\d)S(?=\d)", "5", text)
        if repaired != text:
            text = repaired
            rules.append("ocr_s_to_five_between_digits")

    cleaned = re.sub(r"_+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" |;")
    if cleaned != text.strip():
        rules.append("drawing_line_noise_cleanup")
    return NormalizedEngineeringText(
        raw_text=raw,
        normalized_text=cleaned,
        normalization_rules=list(dict.fromkeys(rules)),
    )


def _number_from_match(raw_number: str) -> float:
    compact = re.sub(r"\s*/\s*", "/", raw_number.strip())
    compact = re.sub(r"^(\d+)-(\d+/\d+)$", r"\1 \2", compact)
    return parse_number(compact)


def parse_measurement(
    raw: str,
    *,
    default_unit: MeasurementUnit | None = None,
    thickness_context: bool = False,
) -> ParsedMeasurement | None:
    normalized = normalize_engineering_text(
        raw,
        numeric_context=True,
        thickness_context=thickness_context,
    )
    text = normalized.normalized_text
    explicit_unit = False
    unit = default_unit
    if '"' in text:
        unit = MeasurementUnit.INCH
        explicit_unit = True
    else:
        unit_match = re.search(
            r"\b(MM|MILLIMETERS?|MILLIMETRES?|IN|INCH(?:ES)?)\b", text
        )
        if unit_match:
            unit = normalize_unit(unit_match.group(1))
            explicit_unit = True

    match = re.search(_NUMBER, text)
    if not match:
        return None
    try:
        value = _number_from_match(match.group(0))
    except (ValueError, ZeroDivisionError):
        return None
    return ParsedMeasurement(
        value=value,
        unit=unit,
        explicit_unit=explicit_unit,
        raw_text=raw,
        normalized_text=text,
        normalization_rules=normalized.normalization_rules,
    )


def parse_tolerance(
    raw: str,
    *,
    default_unit: MeasurementUnit | None = None,
) -> ParsedTolerance | None:
    normalized = normalize_engineering_text(
        raw,
        numeric_context=True,
        tolerance_context=True,
    )
    text = normalized.normalized_text
    unit = MeasurementUnit.INCH if '"' in text else default_unit
    unit_match = re.search(r"\b(MM|IN|INCH(?:ES)?)\b", text)
    if unit_match:
        unit = normalize_unit(unit_match.group(1))

    symmetric = re.search(rf"(?:±|\+\s*/\s*-|\+-)\s*(?P<value>{_NUMBER})", text)
    if symmetric:
        value = _number_from_match(symmetric.group("value"))
        return ParsedTolerance(
            kind=ToleranceKind.SYMMETRIC,
            plus=value,
            minus=value,
            unit=unit,
            raw_text=raw,
            normalized_text=text,
            normalization_rules=normalized.normalization_rules,
        )

    bilateral = re.search(
        rf"\+\s*(?P<plus>{_NUMBER})\s*(?:/|\\)\s*-\s*(?P<minus>{_NUMBER})",
        text,
    )
    if bilateral:
        return ParsedTolerance(
            kind=ToleranceKind.BILATERAL,
            plus=_number_from_match(bilateral.group("plus")),
            minus=_number_from_match(bilateral.group("minus")),
            unit=unit,
            raw_text=raw,
            normalized_text=text,
            normalization_rules=normalized.normalization_rules,
        )

    plus_match = re.search(rf"\+\s*(?P<value>{_NUMBER})", text)
    minus_match = re.search(rf"-\s*(?P<value>{_NUMBER})", text)
    if plus_match or minus_match:
        return ParsedTolerance(
            kind=ToleranceKind.UNILATERAL,
            plus=(
                _number_from_match(plus_match.group("value")) if plus_match else None
            ),
            minus=(
                _number_from_match(minus_match.group("value")) if minus_match else None
            ),
            unit=unit,
            raw_text=raw,
            normalized_text=text,
            normalization_rules=normalized.normalization_rules,
        )

    limits = re.search(rf"(?P<upper>{_NUMBER})\s*/\s*(?P<lower>{_NUMBER})", text)
    if limits:
        upper = _number_from_match(limits.group("upper"))
        lower = _number_from_match(limits.group("lower"))
        if upper >= lower:
            return ParsedTolerance(
                kind=ToleranceKind.LIMITS,
                upper_limit=upper,
                lower_limit=lower,
                unit=unit,
                raw_text=raw,
                normalized_text=text,
                normalization_rules=normalized.normalization_rules,
            )
    return None


def parse_chamfer_notation(
    raw: str,
    *,
    default_unit: MeasurementUnit | None = None,
) -> ParsedChamfer | None:
    normalized = normalize_engineering_text(raw, numeric_context=True)
    text = normalized.normalized_text
    match = re.search(
        rf"(?P<width>{_NUMBER})\s*(?:\"|MM|IN)?\s*[X×]\s*(?P<angle>{_NUMBER})\s*DEG",
        text,
    )
    if not match:
        return None
    unit = MeasurementUnit.INCH if '"' in text else default_unit
    if "MM" in text:
        unit = MeasurementUnit.MILLIMETER
    return ParsedChamfer(
        width_or_depth=_number_from_match(match.group("width")),
        dimension_unit=unit,
        angle_degrees=_number_from_match(match.group("angle")),
        raw_text=raw,
        normalized_text=text,
        normalization_rules=normalized.normalization_rules,
    )


def parse_material(raw: str) -> str | None:
    text = normalize_engineering_text(raw).normalized_text
    compact = " ".join(re.sub(r"[^A-Z0-9]+", " ", text).split())
    known_patterns = (
        r"\b304\s+(?:SS|STAINLESS(?:\s+STEEL)?)\b",
        r"\b(?:SS|STAINLESS(?:\s+STEEL)?)\s+304\b",
        r"\b316\s+(?:SS|STAINLESS(?:\s+STEEL)?)\b",
        r"\b(?:SS|STAINLESS(?:\s+STEEL)?)\s+316\b",
        r"\b(?:CARBON|MILD)\s+STEEL\b",
        r"\bHASTELLOY\s+C[ -]?276\b",
        r"\bS\s*S\s*316\b",
        r"\bS\s*S\s*304\b",
    )
    for pattern in known_patterns:
        match = re.search(pattern, compact)
        if match:
            material = match.group(0)
            if re.fullmatch(r"S\s*S\s*(?:304|316)", material):
                material = "SS " + material.split()[-1]
            return normalize_material(material)
    return None


_QUANTITY_WORDS = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
    "SIX": 6,
    "SEVEN": 7,
    "EIGHT": 8,
    "NINE": 9,
    "TEN": 10,
}


def parse_quantity(raw: str) -> int | None:
    text = normalize_engineering_text(raw).normalized_text
    for word, value in _QUANTITY_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return value
    label = r"(?:QTY|QUANTITY|REQD|REQUIRED|NO\.?\s*REQ(?:\.?\s*'?D)?)"
    match = re.search(rf"\b{label}\.?\s*[,;:=]?\s*(\d+)\b", text)
    return int(match.group(1)) if match else None
