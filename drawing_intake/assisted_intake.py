from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from pydantic import Field

from .assisted_quote import (
    AssistedQuoteSession,
    CanonicalFormAvailability,
    build_assisted_quote_session,
    build_manual_quote_session,
)
from .classification import DrawingDocumentClass
from .confirmation_contract import (
    ConfirmationFieldProposal,
    ConfirmationWorkflowStatus,
    CustomerConfirmationContract,
)
from .deterministic import (
    DeterministicRegionRecognizer,
    EvidenceClassification,
)
from .document_recognition import (
    DeterministicDocumentRecognitionResult,
    recognize_document_structure,
)
from .documents import NormalizedDocument, normalize_document
from .models import (
    DocumentReference,
    DrawingExtractionResult,
    DrawingFields,
    FieldStatus,
    IntegerField,
    NumericField,
    ProviderDataHandling,
    StrictModel,
    StringField,
    UnitField,
)
from .reconciliation import EXTRACTION_TO_CANONICAL
from .regions import DerivedDrawingRegion, derive_candidate_regions
from .table_schedule import TableFieldObservation, TablePlateCandidate
from .validation import validate_extraction


class AssistedCandidateKind(str, Enum):
    DETAIL_REGION = "detail_region"
    SCHEDULE_ROW = "schedule_row"


class AssistedCandidateOption(StrictModel):
    candidate_id: str
    kind: AssistedCandidateKind
    label: str
    page_number: int = Field(ge=1)
    source_bbox: tuple[float, float, float, float] | None = None
    row_index: int | None = Field(default=None, ge=1)


class AssistedDocumentReview(StrictModel):
    filename: str
    sha256: str
    document_class: DrawingDocumentClass
    quote_specific: bool
    reason: str
    candidates: list[AssistedCandidateOption] = Field(default_factory=list)
    selection_required: bool
    manual_configuration_available: bool = True
    processing_seconds: float = Field(ge=0)
    external_service_used: bool = False
    persistent_storage_used: bool = False


@dataclass(frozen=True)
class ProcessedAssistedUpload:
    document: NormalizedDocument
    recognition: DeterministicDocumentRecognitionResult
    review: AssistedDocumentReview
    regions: dict[str, DerivedDrawingRegion]
    schedule_rows: dict[str, TablePlateCandidate]


def _first_evidence(observation: TableFieldObservation):
    return observation.evidence


def _table_field(
    observation: TableFieldObservation,
    field_type,
):
    return field_type(
        value=observation.value,
        normalized_unit=observation.normalized_unit,
        raw_text=observation.raw_text,
        status=observation.status,
        evidence=[observation.evidence] if observation.evidence else [],
        warnings=[observation.reason] if observation.reason else [],
    )


def _schedule_extraction(
    document: NormalizedDocument,
    row: TablePlateCandidate,
) -> DrawingExtractionResult:
    return DrawingExtractionResult(
        document=DocumentReference(
            filename=document.filename,
            media_type=document.media_type,
            sha256=document.sha256,
            page_count=len(document.pages),
        ),
        provider_name="deterministic_local_schedule_v1",
        provider_data_handling=ProviderDataHandling(
            external_service=False,
            retention="in_memory_only",
            sends_document_content=False,
        ),
        fields=DrawingFields(
            outside_diameter=_table_field(row.outside_diameter, NumericField),
            bore_diameter=_table_field(row.bore_diameter, NumericField),
            thickness=_table_field(row.thickness, NumericField),
            material=_table_field(row.material, StringField),
            quantity=_table_field(row.quantity, IntegerField),
            global_units=_table_field(row.global_units, UnitField),
            bore_tolerance_plus=_table_field(row.bore_tolerance_plus, NumericField),
            bore_tolerance_minus=_table_field(row.bore_tolerance_minus, NumericField),
            customer_part_number=_table_field(row.tag, StringField),
        ),
        document_warnings=[
            "Recognition is scoped to one explicitly selected schedule row; customer review remains required."
        ],
    )


def _evidence_classification(status: FieldStatus | str) -> EvidenceClassification:
    value = status.value if isinstance(status, FieldStatus) else str(status)
    if value == FieldStatus.AMBIGUOUS.value:
        return EvidenceClassification.AMBIGUOUS
    if value in {FieldStatus.NOT_DETECTED.value, FieldStatus.UNREADABLE.value}:
        return EvidenceClassification.NOT_DETECTED
    if value in {FieldStatus.UNSUPPORTED.value, FieldStatus.CONFLICT_DETECTED.value}:
        return EvidenceClassification.UNSUPPORTED
    return EvidenceClassification.REQUIRES_CONFIRMATION


def _schedule_contract(
    document: NormalizedDocument,
    row: TablePlateCandidate,
    *,
    candidate_id: str,
) -> CustomerConfirmationContract:
    extraction = _schedule_extraction(document, row)
    # Schedule observations intentionally remain low-confidence until the row is
    # selected and reviewed. Product-support validation still needs to evaluate
    # the observed values, so use a validation-only copy with present values
    # marked detected. The original observation status remains on every proposal.
    support_fields = extraction.fields.model_copy(
        update={
            name: (
                field.model_copy(update={"status": FieldStatus.DETECTED})
                if field.value is not None
                else field
            )
            for name in type(extraction.fields).model_fields
            for field in [getattr(extraction.fields, name)]
        }
    )
    validation = validate_extraction(
        extraction.model_copy(update={"fields": support_fields})
    )
    proposals: list[ConfirmationFieldProposal] = []
    for name in type(extraction.fields).model_fields:
        field = getattr(extraction.fields, name)
        outcome = validation.field_outcomes.get(name, field.status)
        source = field.evidence[0] if field.evidence else None
        outcome_value = (
            outcome.value if isinstance(outcome, FieldStatus) else str(outcome)
        )
        unsupported = outcome_value in {
            FieldStatus.UNSUPPORTED.value,
            FieldStatus.CONFLICT_DETECTED.value,
        }
        proposals.append(
            ConfirmationFieldProposal(
                extraction_field=name,
                canonical_field=EXTRACTION_TO_CANONICAL.get(name),
                proposed_value=field.value,
                normalized_unit=field.normalized_unit,
                raw_text=field.raw_text,
                source_document=document.filename,
                source_sha256=document.sha256,
                source_page=source.page_number if source else None,
                source_bbox=source.bbox if source else None,
                source_coordinate_unit=source.coordinate_unit if source else None,
                evidence_status=_evidence_classification(field.status),
                validation_status=outcome,
                confirmation_required=field.value is not None,
                unsupported=unsupported,
            )
        )
    return CustomerConfirmationContract(
        source_document=document.filename,
        source_sha256=document.sha256,
        document_class=DrawingDocumentClass.TABLE_DRIVEN_PLATE_SCHEDULE,
        candidate_count=1,
        selected_candidate_id=candidate_id,
        selection_required=False,
        proposals=proposals,
        required_manual_fields=list(
            validation.canonical_candidate.missing_required_fields
        ),
        status=ConfirmationWorkflowStatus.REQUIRES_CONFIRMATION,
    )


def inspect_assisted_upload(
    data: bytes,
    filename: str,
    media_type: str | None = None,
) -> ProcessedAssistedUpload:
    """Normalize/classify an upload in memory and enumerate selectable candidates."""

    started = time.perf_counter()
    document = normalize_document(data, filename, media_type)
    recognition = recognize_document_structure(document)
    candidates: list[AssistedCandidateOption] = []
    regions: dict[str, DerivedDrawingRegion] = {}
    schedule_rows: dict[str, TablePlateCandidate] = {}

    if (
        recognition.classification.document_class
        == DrawingDocumentClass.TABLE_DRIVEN_PLATE_SCHEDULE
        and recognition.table_schedule is not None
    ):
        for row in recognition.table_schedule.candidates:
            candidate_id = f"schedule-row-{row.row_index}"
            schedule_rows[candidate_id] = row
            evidence = _first_evidence(row.tag)
            label = str(row.tag.value or f"Schedule row {row.row_index}")
            candidates.append(
                AssistedCandidateOption(
                    candidate_id=candidate_id,
                    kind=AssistedCandidateKind.SCHEDULE_ROW,
                    label=label,
                    page_number=evidence.page_number if evidence else 1,
                    source_bbox=evidence.bbox if evidence else None,
                    row_index=row.row_index,
                )
            )
    elif recognition.classification.quote_specific:
        derived = derive_candidate_regions(
            document,
            recognition.structure,
            source_group_id=document.sha256[:16],
        )
        for region in derived:
            regions[region.region_id] = region
            candidates.append(
                AssistedCandidateOption(
                    candidate_id=region.region_id,
                    kind=AssistedCandidateKind.DETAIL_REGION,
                    label=f"Plate detail {region.region_id}",
                    page_number=region.page_number,
                    source_bbox=region.source_bbox,
                )
            )

    selection_required = len(candidates) > 1
    review = AssistedDocumentReview(
        filename=document.filename,
        sha256=document.sha256,
        document_class=recognition.classification.document_class,
        quote_specific=recognition.classification.quote_specific,
        reason=recognition.classification.reason,
        candidates=candidates,
        selection_required=selection_required,
        processing_seconds=time.perf_counter() - started,
    )
    return ProcessedAssistedUpload(
        document=document,
        recognition=recognition,
        review=review,
        regions=regions,
        schedule_rows=schedule_rows,
    )


def select_assisted_candidate(
    upload: ProcessedAssistedUpload,
    candidate_id: str,
    *,
    recognizer: DeterministicRegionRecognizer | None = None,
    availability: CanonicalFormAvailability | None = None,
) -> AssistedQuoteSession:
    """Recognize exactly one selected region/row; values cannot cross candidates."""

    if candidate_id in upload.regions:
        recognition = (recognizer or DeterministicRegionRecognizer()).recognize(
            upload.document,
            upload.regions[candidate_id],
        )
        contract = CustomerConfirmationContract(
            **{
                **build_assisted_contract_for_region(recognition).model_dump(),
                "candidate_count": 1,
                "selected_candidate_id": candidate_id,
                "selection_required": False,
            }
        )
    elif candidate_id in upload.schedule_rows:
        contract = _schedule_contract(
            upload.document,
            upload.schedule_rows[candidate_id],
            candidate_id=candidate_id,
        )
    else:
        raise ValueError(f"unknown candidate: {candidate_id}")

    session = build_assisted_quote_session(contract, availability=availability)
    return session.model_copy(
        update={
            "candidate_count": len(upload.review.candidates),
            "selected_candidate_id": candidate_id,
            "selection_required": False,
        }
    )


def build_assisted_contract_for_region(recognition):
    """Local import wrapper keeps the region contract on the accepted Phase 1E path."""

    from .confirmation_contract import build_customer_confirmation_contract

    return build_customer_confirmation_contract(
        recognition,
        document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
        candidate_count=1,
        selected_candidate_id=recognition.region.region_id,
    )


def manual_session_for_upload(upload: ProcessedAssistedUpload) -> AssistedQuoteSession:
    return build_manual_quote_session(
        source_document=upload.document.filename,
        source_sha256=upload.document.sha256,
        document_class=upload.review.document_class,
    )
