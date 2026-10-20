from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .classification import DrawingDocumentClass
from .deterministic import (
    DeterministicRecognitionResult,
    EvidenceClassification,
)
from .document_recognition import DeterministicDocumentRecognitionResult
from .models import (
    CRITICAL_FIELDS,
    ComparisonStatus,
    DomainValidationResult,
    FieldStatus,
    ReconciliationResult,
    StrictModel,
)
from .reconciliation import compare_extraction_to_configuration


class ReconciliationEntryStatus(str, Enum):
    ELIGIBLE_SINGLE_CANDIDATE = "eligible_single_candidate"
    SELECTION_REQUIRED = "selection_required"
    NOT_QUOTE_SPECIFIC = "not_quote_specific"


class ReconciliationReviewStatus(str, Enum):
    MATCH = "match"
    REQUIRES_RESOLUTION = "requires_resolution"
    BLOCKED = "blocked"


class ReconciliationEntryAssessment(StrictModel):
    status: ReconciliationEntryStatus
    candidate_count: int | None = Field(default=None, ge=0)
    reason: str
    automatic_candidate_selection_permitted: bool = False
    canonical_candidate_created: bool = False


class ReconciliationReview(StrictModel):
    selected_candidate_id: str
    status: ReconciliationReviewStatus
    comparison: ReconciliationResult
    critical_mismatches: list[str] = Field(default_factory=list)
    critical_unknowns: list[str] = Field(default_factory=list)
    critical_unsupported: list[str] = Field(default_factory=list)
    confirmation_required: list[str] = Field(default_factory=list)
    reason: str
    automatic_overwrite_permitted: bool = False
    pricing_invoked: bool = False


_QUOTE_SPECIFIC_CLASSES = {
    DrawingDocumentClass.SINGLE_PLATE_DRAWING,
    DrawingDocumentClass.MULTI_PLATE_DRAWING,
    DrawingDocumentClass.TABLE_DRIVEN_PLATE_SCHEDULE,
}


def assess_reconciliation_entry(
    recognition: DeterministicDocumentRecognitionResult,
) -> ReconciliationEntryAssessment:
    """Decide whether a whole document may enter data-level reconciliation."""

    classification = recognition.classification
    if (
        classification.document_class not in _QUOTE_SPECIFIC_CLASSES
        or not classification.quote_specific
    ):
        return ReconciliationEntryAssessment(
            status=ReconciliationEntryStatus.NOT_QUOTE_SPECIFIC,
            candidate_count=classification.candidate_count,
            reason=(
                "The document does not identify a unique quote-specific plate "
                "configuration."
            ),
        )
    if classification.candidate_count != 1:
        return ReconciliationEntryAssessment(
            status=ReconciliationEntryStatus.SELECTION_REQUIRED,
            candidate_count=classification.candidate_count,
            reason=(
                "Explicit candidate selection is required before values may be "
                "compared with a customer configuration."
            ),
        )
    return ReconciliationEntryAssessment(
        status=ReconciliationEntryStatus.ELIGIBLE_SINGLE_CANDIDATE,
        candidate_count=1,
        reason="One quote-specific plate candidate may be recognized and compared.",
    )


def _evidence_map(
    recognition: DeterministicRecognitionResult,
) -> dict[str, EvidenceClassification]:
    return {
        name: result.evidence_classification
        for name, result in recognition.field_results.items()
    }


def build_reconciliation_review(
    validation: DomainValidationResult,
    canonical_config: Mapping[str, Any] | BaseModel,
    *,
    selected_candidate_id: str,
    evidence_by_field: Mapping[str, EvidenceClassification | str],
) -> ReconciliationReview:
    """Compare one explicitly selected candidate without mutation or pricing."""

    comparison = compare_extraction_to_configuration(validation, canonical_config)
    critical = set(CRITICAL_FIELDS)
    by_field = {
        item.extraction_field: item
        for item in comparison.comparisons
        if item.extraction_field in critical
    }
    mismatches = sorted(
        name
        for name, item in by_field.items()
        if item.status == ComparisonStatus.MISMATCH
    )
    unsupported = sorted(
        name
        for name in critical
        if validation.field_outcomes.get(name)
        in {FieldStatus.UNSUPPORTED, FieldStatus.CONFLICT_DETECTED}
        or (name in by_field and by_field[name].status == ComparisonStatus.UNSUPPORTED)
    )
    fields = validation.extraction.fields
    unknown = sorted(
        name
        for name in critical
        if name not in unsupported
        and (
            getattr(fields, name).value is None
            or getattr(fields, name).status
            not in {FieldStatus.DETECTED, FieldStatus.LOW_CONFIDENCE}
        )
    )
    confirmation = sorted(
        name
        for name in critical
        if getattr(fields, name).value is not None
        and (
            getattr(fields, name).status == FieldStatus.LOW_CONFIDENCE
            or evidence_by_field.get(name)
            in {
                EvidenceClassification.REQUIRES_CONFIRMATION,
                EvidenceClassification.AMBIGUOUS,
                "requires_confirmation",
                "ambiguous",
            }
        )
    )

    if unsupported:
        status = ReconciliationReviewStatus.BLOCKED
        reason = "At least one critical drawing value is unsupported or contradictory."
    elif mismatches or unknown or confirmation:
        status = ReconciliationReviewStatus.REQUIRES_RESOLUTION
        reason = (
            "The customer must resolve mismatches, unknowns, or confirmation-only "
            "drawing observations."
        )
    else:
        status = ReconciliationReviewStatus.MATCH
        reason = "All critical drawing observations match the customer configuration."
    return ReconciliationReview(
        selected_candidate_id=selected_candidate_id,
        status=status,
        comparison=comparison,
        critical_mismatches=mismatches,
        critical_unknowns=unknown,
        critical_unsupported=unsupported,
        confirmation_required=confirmation,
        reason=reason,
    )


def reconcile_selected_region(
    recognition: DeterministicRecognitionResult,
    canonical_config: Mapping[str, Any] | BaseModel,
) -> ReconciliationReview:
    """Reconcile one selected region; never accept a whole multi-part sheet."""

    return build_reconciliation_review(
        recognition.validation,
        canonical_config,
        selected_candidate_id=recognition.region.region_id,
        evidence_by_field=_evidence_map(recognition),
    )
