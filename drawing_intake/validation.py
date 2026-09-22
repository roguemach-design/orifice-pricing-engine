from __future__ import annotations

import math
import re
from dataclasses import dataclass

import tuning_knobs as cfg

from .models import (
    CanonicalConfigurationCandidate,
    DomainValidationResult,
    DrawingExtractionResult,
    FieldStatus,
    MeasurementUnit,
    ValidationIssue,
    ValidationSeverity,
)
from .value_normalization import normalize_material, to_inches


@dataclass(frozen=True)
class CanonicalProductRules:
    max_paddle_dia_in: float
    max_bore_dia_in: float
    max_handle_label_chars: int
    material_thicknesses: dict[str, frozenset[float]]
    bore_tolerances_in: frozenset[float]

    @classmethod
    def from_current_tuning_knobs(cls) -> "CanonicalProductRules":
        return cls(
            max_paddle_dia_in=float(cfg.MAX_PADDLE_DIA_IN),
            max_bore_dia_in=float(cfg.MAX_BORE_DIA_IN),
            max_handle_label_chars=int(cfg.MAX_HANDLE_LABEL_CHARS),
            material_thicknesses={
                str(material): frozenset(float(value) for value in thicknesses)
                for material, thicknesses in cfg.PRICE_PER_SQ_IN.items()
            },
            bore_tolerances_in=frozenset(
                float(value) for value in cfg.INSPECTION_MINS_BY_TOL
            ),
        )


def _close(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


def _detected(field) -> bool:
    return field.status == FieldStatus.DETECTED and field.value is not None


def _dimension_in(field) -> float | None:
    if not _detected(field) or not isinstance(field.value, (int, float)):
        return None
    if field.normalized_unit not in {MeasurementUnit.INCH, MeasurementUnit.MILLIMETER}:
        return None
    return to_inches(float(field.value), field.normalized_unit)


def validate_extraction(
    extraction: DrawingExtractionResult,
    rules: CanonicalProductRules | None = None,
) -> DomainValidationResult:
    """Validate what was read without pricing or silently replacing any value."""

    rules = rules or CanonicalProductRules.from_current_tuning_knobs()
    fields = extraction.fields
    issues: list[ValidationIssue] = []
    outcomes: dict[str, FieldStatus] = {}

    def add(
        code: str,
        message: str,
        field_names: list[str],
        *,
        severity: ValidationSeverity = ValidationSeverity.ERROR,
        outcome: FieldStatus = FieldStatus.UNSUPPORTED,
    ) -> None:
        issues.append(
            ValidationIssue(
                code=code,
                message=message,
                severity=severity,
                field_names=field_names,
            )
        )
        if severity == ValidationSeverity.ERROR:
            for name in field_names:
                outcomes[name] = outcome

    dimension_names = (
        "outside_diameter",
        "bore_diameter",
        "thickness",
        "bore_tolerance_plus",
        "bore_tolerance_minus",
        "general_dimensional_tolerance",
        "chamfer_width",
        "chamfer_depth",
    )
    for name in dimension_names:
        field = getattr(fields, name)
        if not _detected(field):
            continue
        if not isinstance(field.value, (int, float)) or not math.isfinite(
            float(field.value)
        ):
            add("non_finite_dimension", f"{name} must be a finite number.", [name])
            continue
        if float(field.value) < 0 or (
            name not in {"bore_tolerance_minus"} and float(field.value) == 0
        ):
            add("non_positive_dimension", f"{name} must be positive.", [name])
        if field.normalized_unit not in {
            MeasurementUnit.INCH,
            MeasurementUnit.MILLIMETER,
        }:
            add(
                "dimension_unit_missing",
                f"{name} has no supported inch/mm unit.",
                [name],
            )

    outside_diameter = _dimension_in(fields.outside_diameter)
    bore_diameter = _dimension_in(fields.bore_diameter)
    thickness = _dimension_in(fields.thickness)
    tolerance_plus = _dimension_in(fields.bore_tolerance_plus)
    tolerance_minus = _dimension_in(fields.bore_tolerance_minus)

    if outside_diameter is not None and outside_diameter > rules.max_paddle_dia_in:
        add(
            "outside_diameter_out_of_envelope",
            f"Drawing OD {outside_diameter:g} in exceeds the current {rules.max_paddle_dia_in:g} in limit.",
            ["outside_diameter"],
        )
    if bore_diameter is not None and bore_diameter > rules.max_bore_dia_in:
        add(
            "bore_diameter_out_of_envelope",
            f"Drawing bore {bore_diameter:g} in exceeds the current {rules.max_bore_dia_in:g} in limit.",
            ["bore_diameter"],
        )
    if (
        outside_diameter is not None
        and bore_diameter is not None
        and bore_diameter >= outside_diameter
    ):
        add(
            "bore_not_smaller_than_od",
            "Drawing bore must be smaller than drawing OD.",
            ["bore_diameter", "outside_diameter"],
            outcome=FieldStatus.CONFLICT_DETECTED,
        )

    material = (
        normalize_material(fields.material.value)
        if _detected(fields.material)
        else None
    )
    if material is not None and material not in rules.material_thicknesses:
        add(
            "unsupported_material",
            f"Drawing material {fields.material.value!r} is not enabled for O-Plates.",
            ["material"],
        )
    if thickness is not None and material in rules.material_thicknesses:
        if not any(
            _close(thickness, supported)
            for supported in rules.material_thicknesses[material]
        ):
            add(
                "unsupported_thickness",
                f"Drawing thickness {thickness:g} in is not enabled for {material}.",
                ["thickness"],
            )

    if _detected(fields.quantity) and int(fields.quantity.value) < 1:
        add("invalid_quantity", "Drawing quantity must be at least 1.", ["quantity"])

    if tolerance_plus is not None and tolerance_minus is not None:
        if tolerance_plus < 0 or tolerance_minus < 0:
            add(
                "invalid_tolerance_sign",
                "Tolerance magnitudes must be non-negative.",
                ["bore_tolerance_plus", "bore_tolerance_minus"],
            )
        elif not _close(tolerance_plus, tolerance_minus):
            add(
                "asymmetric_tolerance_not_canonical",
                "The drawing tolerance is asymmetric; the current O-Plates configuration accepts only symmetric ± tolerance.",
                ["bore_tolerance_plus", "bore_tolerance_minus"],
            )
        elif not any(
            _close(tolerance_plus, supported) for supported in rules.bore_tolerances_in
        ):
            add(
                "unsupported_bore_tolerance",
                f"Drawing bore tolerance ±{tolerance_plus:g} in is not currently supported.",
                ["bore_tolerance_plus", "bore_tolerance_minus"],
            )
    elif tolerance_plus is not None or tolerance_minus is not None:
        add(
            "incomplete_bore_tolerance",
            "Only one side of the bore tolerance was detected.",
            ["bore_tolerance_plus", "bore_tolerance_minus"],
            outcome=FieldStatus.AMBIGUOUS,
        )

    if _detected(fields.chamfer_present) and fields.chamfer_present.value is False:
        if _detected(fields.chamfer_width) or _detected(fields.chamfer_depth):
            add(
                "chamfer_conflict",
                "The drawing says no chamfer but also supplies chamfer dimensions.",
                ["chamfer_present", "chamfer_width", "chamfer_depth"],
                outcome=FieldStatus.CONFLICT_DETECTED,
            )
    if _detected(fields.chamfer_angle):
        angle = float(fields.chamfer_angle.value)
        if angle <= 0 or angle >= 90:
            add(
                "invalid_chamfer_angle",
                "Chamfer angle must be between 0 and 90 degrees.",
                ["chamfer_angle"],
            )

    if _detected(fields.marking_text):
        marking = str(fields.marking_text.value)
        if len(marking) > rules.max_handle_label_chars:
            add(
                "marking_too_long",
                f"Handle marking exceeds {rules.max_handle_label_chars} characters.",
                ["marking_text"],
            )
        elif not re.fullmatch(r"[A-Za-z0-9 .,_/#()+\-:=]+", marking):
            add(
                "unsupported_marking_characters",
                "Handle marking contains unsupported characters.",
                ["marking_text"],
            )

    candidate_values = {
        "quantity": (
            int(fields.quantity.value)
            if _detected(fields.quantity) and "quantity" not in outcomes
            else None
        ),
        "material": (
            material if material is not None and "material" not in outcomes else None
        ),
        "thickness": (
            thickness if thickness is not None and "thickness" not in outcomes else None
        ),
        "paddle_dia": (
            outside_diameter
            if outside_diameter is not None and "outside_diameter" not in outcomes
            else None
        ),
        "bore_dia": (
            bore_diameter
            if bore_diameter is not None and "bore_diameter" not in outcomes
            else None
        ),
        "chamfer": (
            bool(fields.chamfer_present.value)
            if _detected(fields.chamfer_present) and "chamfer_present" not in outcomes
            else None
        ),
        "chamfer_width": (
            _dimension_in(fields.chamfer_width)
            if "chamfer_width" not in outcomes
            else None
        ),
        "handle_label": (
            str(fields.marking_text.value)
            if _detected(fields.marking_text) and "marking_text" not in outcomes
            else None
        ),
    }
    if (
        tolerance_plus is not None
        and tolerance_minus is not None
        and _close(tolerance_plus, tolerance_minus)
        and "bore_tolerance_plus" not in outcomes
        and "bore_tolerance_minus" not in outcomes
    ):
        candidate_values["bore_tolerance"] = tolerance_plus
    else:
        candidate_values["bore_tolerance"] = None

    source_fields = {
        "quantity": "quantity",
        "material": "material",
        "thickness": "thickness",
        "paddle_dia": "outside_diameter",
        "bore_dia": "bore_diameter",
        "bore_tolerance": "bore_tolerance_plus+bore_tolerance_minus",
        "chamfer": "chamfer_present",
        "chamfer_width": "chamfer_width",
        "handle_label": "marking_text",
    }
    required = (
        "quantity",
        "material",
        "thickness",
        "handle_width",
        "handle_length_from_bore",
        "paddle_dia",
        "bore_dia",
        "bore_tolerance",
        "chamfer",
        "ships_in_days",
    )
    candidate = CanonicalConfigurationCandidate(
        **candidate_values,
        source_fields={
            key: value
            for key, value in source_fields.items()
            if candidate_values.get(key) is not None
        },
        missing_required_fields=[
            key for key in required if candidate_values.get(key) is None
        ],
    )
    return DomainValidationResult(
        extraction=extraction,
        issues=issues,
        field_outcomes=outcomes,
        canonical_candidate=candidate,
    )
