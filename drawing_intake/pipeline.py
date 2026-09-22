from __future__ import annotations

from .documents import NormalizedDocument, normalize_document
from .models import (
    CanonicalConfigurationCandidate,
    DocumentStatus,
    DocumentStructureAssessment,
    DomainValidationResult,
    StrictModel,
    ValidationIssue,
    ValidationSeverity,
)
from .providers import ExtractionProvider
from .structure import assess_document_structure
from .validation import CanonicalProductRules, validate_extraction

_REQUIRED_CANONICAL_FIELDS = (
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


class DrawingPipelineResult(StrictModel):
    normalized_document: NormalizedDocument
    structure: DocumentStructureAssessment
    validation: DomainValidationResult


def _enforce_structure_safety(
    validation: DomainValidationResult,
    structure: DocumentStructureAssessment,
) -> DomainValidationResult:
    if structure.status != DocumentStatus.MULTIPLE_CANDIDATES:
        return validation

    extraction = validation.extraction.model_copy(
        update={
            "document_warnings": [
                *validation.extraction.document_warnings,
                "Multiple plate-like regions detected; explicit part selection is required.",
            ]
        }
    )
    return DomainValidationResult(
        extraction=extraction,
        issues=[
            *validation.issues,
            ValidationIssue(
                code="unsupported_multi_part_sheet",
                message=(
                    "Multiple plate-like regions were detected. The whole document "
                    "cannot become one canonical configuration without explicit part selection."
                ),
                severity=ValidationSeverity.ERROR,
                field_names=[],
            ),
        ],
        field_outcomes=validation.field_outcomes,
        canonical_candidate=CanonicalConfigurationCandidate(
            missing_required_fields=list(_REQUIRED_CANONICAL_FIELDS)
        ),
    )


class DrawingIntakePipeline:
    def __init__(
        self,
        provider: ExtractionProvider,
        rules: CanonicalProductRules | None = None,
    ) -> None:
        self._provider = provider
        self._rules = rules

    def process(
        self,
        data: bytes,
        filename: str,
        media_type: str | None = None,
    ) -> DrawingPipelineResult:
        document = normalize_document(data, filename, media_type)
        structure = assess_document_structure(document)
        extraction = self._provider.extract_drawing(document)
        validation = validate_extraction(extraction, self._rules)
        validation = _enforce_structure_safety(validation, structure)
        return DrawingPipelineResult(
            normalized_document=document,
            structure=structure,
            validation=validation,
        )
