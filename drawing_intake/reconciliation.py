from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .models import (
    ComparisonStatus,
    DomainValidationResult,
    FieldComparison,
    FieldStatus,
    MeasurementUnit,
    ReconciliationResult,
)
from .value_normalization import to_inches

EXTRACTION_TO_CANONICAL = {
    "outside_diameter": "paddle_dia",
    "bore_diameter": "bore_dia",
    "thickness": "thickness",
    "material": "material",
    "quantity": "quantity",
    "bore_tolerance_plus": "bore_tolerance",
    "bore_tolerance_minus": "bore_tolerance",
    "chamfer_present": "chamfer",
    "chamfer_width": "chamfer_width",
    "marking_text": "handle_label",
}
NORMALIZED_INCH_FIELDS = {
    "outside_diameter",
    "bore_diameter",
    "thickness",
    "bore_tolerance_plus",
    "bore_tolerance_minus",
    "chamfer_width",
}


def _configuration_dict(configuration: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(configuration, BaseModel):
        return configuration.model_dump()
    return dict(configuration)


def _drawing_value(field_name: str, field) -> Any:
    if field_name in NORMALIZED_INCH_FIELDS and isinstance(field.value, (int, float)):
        return to_inches(float(field.value), field.normalized_unit)
    return field.value


def compare_extraction_to_configuration(
    validation: DomainValidationResult,
    canonical_config: Mapping[str, Any] | BaseModel,
    *,
    numeric_tolerance: float = 1e-9,
) -> ReconciliationResult:
    """Compare only; drawing values never mutate the supplied configuration."""

    customer = _configuration_dict(canonical_config)
    comparisons: list[FieldComparison] = []
    for field_name in type(validation.extraction.fields).model_fields:
        field = getattr(validation.extraction.fields, field_name)
        canonical_field = EXTRACTION_TO_CANONICAL.get(field_name)
        drawing_value = (
            _drawing_value(field_name, field) if field.value is not None else None
        )
        comparison_unit = (
            MeasurementUnit.INCH
            if drawing_value is not None and field_name in NORMALIZED_INCH_FIELDS
            else field.normalized_unit
        )

        if canonical_field is None:
            comparisons.append(
                FieldComparison(
                    extraction_field=field_name,
                    canonical_field=None,
                    status=ComparisonStatus.NOT_COMPARABLE,
                    drawing_value=drawing_value,
                    drawing_unit=comparison_unit,
                    message="No corresponding field exists in the current canonical QuoteInputs schema.",
                )
            )
            continue

        customer_value = customer.get(canonical_field)
        outcome = validation.field_outcomes.get(field_name)
        if outcome in {FieldStatus.UNSUPPORTED, FieldStatus.CONFLICT_DETECTED}:
            status = ComparisonStatus.UNSUPPORTED
            message = "The drawing value is outside or cannot be represented by the current O-Plates configuration."
        elif field.status != FieldStatus.DETECTED or field.value is None:
            status = ComparisonStatus.EXTRACTION_UNKNOWN
            message = f"Drawing field status is {field.status}."
        elif customer_value is None:
            status = ComparisonStatus.NOT_COMPARABLE
            message = "The customer configuration does not contain a comparable value."
        else:
            if isinstance(drawing_value, (int, float)) and isinstance(
                customer_value, (int, float)
            ):
                equal = math.isclose(
                    float(drawing_value),
                    float(customer_value),
                    rel_tol=0.0,
                    abs_tol=numeric_tolerance,
                )
            else:
                equal = drawing_value == customer_value
            status = ComparisonStatus.MATCH if equal else ComparisonStatus.MISMATCH
            message = None
        comparisons.append(
            FieldComparison(
                extraction_field=field_name,
                canonical_field=canonical_field,
                status=status,
                customer_value=customer_value,
                drawing_value=drawing_value,
                drawing_unit=comparison_unit,
                message=message,
            )
        )
    return ReconciliationResult(comparisons=comparisons)
