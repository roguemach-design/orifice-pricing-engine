from __future__ import annotations

import math
from abc import ABC, abstractmethod
from enum import Enum

from pydantic import Field

from .documents import NormalizedDocument
from .models import (
    CRITICAL_FIELDS,
    DrawingExtractionResult,
    ExtractedField,
    StrictModel,
)
from .value_normalization import to_inches


class VerificationAgreement(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    UNCERTAIN = "uncertain"


class CriticalFieldVerification(StrictModel):
    field_name: str
    independently_read: ExtractedField


class VerificationResult(StrictModel):
    provider_name: str
    fields: list[CriticalFieldVerification]


class VerificationComparison(StrictModel):
    field_name: str
    status: VerificationAgreement
    primary_value: float | int | str | bool | None = None
    verifier_value: float | int | str | bool | None = None


class VerificationReconciliation(StrictModel):
    comparisons: list[VerificationComparison] = Field(default_factory=list)


class CriticalFieldVerifier(ABC):
    @abstractmethod
    def verify_critical_fields(
        self,
        document: NormalizedDocument,
        field_names: frozenset[str] = CRITICAL_FIELDS,
    ) -> VerificationResult:
        raise NotImplementedError


def _comparable_value(field_name: str, field: ExtractedField):
    if field_name in {
        "outside_diameter",
        "bore_diameter",
        "thickness",
        "bore_tolerance_plus",
        "bore_tolerance_minus",
    } and isinstance(field.value, (int, float)):
        return to_inches(float(field.value), field.normalized_unit)
    return field.value


def reconcile_independent_verification(
    primary: DrawingExtractionResult,
    verification: VerificationResult,
    *,
    numeric_tolerance: float = 1e-9,
) -> VerificationReconciliation:
    by_name = {item.field_name: item.independently_read for item in verification.fields}
    comparisons = []
    for field_name in sorted(CRITICAL_FIELDS):
        primary_field = getattr(primary.fields, field_name)
        verifier_field = by_name.get(field_name)
        primary_value = _comparable_value(field_name, primary_field)
        verifier_value = (
            _comparable_value(field_name, verifier_field) if verifier_field else None
        )
        if primary_value is None or verifier_value is None:
            status = VerificationAgreement.UNCERTAIN
        elif isinstance(primary_value, (int, float)) and isinstance(
            verifier_value, (int, float)
        ):
            status = (
                VerificationAgreement.AGREE
                if math.isclose(
                    float(primary_value),
                    float(verifier_value),
                    rel_tol=0.0,
                    abs_tol=numeric_tolerance,
                )
                else VerificationAgreement.DISAGREE
            )
        else:
            status = (
                VerificationAgreement.AGREE
                if primary_value == verifier_value
                else VerificationAgreement.DISAGREE
            )
        comparisons.append(
            VerificationComparison(
                field_name=field_name,
                status=status,
                primary_value=primary_value,
                verifier_value=verifier_value,
            )
        )
    return VerificationReconciliation(comparisons=comparisons)
