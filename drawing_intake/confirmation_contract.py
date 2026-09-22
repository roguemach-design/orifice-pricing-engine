from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from .classification import DrawingDocumentClass
from .deterministic import (
    DeterministicRecognitionResult,
    EvidenceClassification,
)
from .models import (
    CRITICAL_FIELDS,
    CoordinateUnit,
    FieldStatus,
    MeasurementUnit,
    ScalarValue,
    StrictModel,
)
from .reconciliation import EXTRACTION_TO_CANONICAL


class CustomerDecision(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ConfirmationWorkflowStatus(str, Enum):
    SELECTION_REQUIRED = "selection_required"
    BLOCKED = "blocked"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    READY_FOR_CONFIGURATION_REVIEW = "ready_for_configuration_review"


class ConfirmationFieldProposal(StrictModel):
    extraction_field: str
    canonical_field: str | None = None
    proposed_value: ScalarValue | None = None
    normalized_unit: MeasurementUnit | None = None
    raw_text: str | None = None
    source_document: str
    source_sha256: str
    source_page: int | None = Field(default=None, ge=1)
    source_bbox: tuple[float, float, float, float] | None = None
    source_coordinate_unit: CoordinateUnit | None = None
    evidence_status: EvidenceClassification
    validation_status: FieldStatus
    confirmation_required: bool
    unsupported: bool
    competing_values: list[ScalarValue] = Field(default_factory=list)
    customer_decision: CustomerDecision = CustomerDecision.PENDING
    customer_value: ScalarValue | None = None
    decision_reason: str | None = None


class CustomerConfirmationContract(StrictModel):
    schema_version: str = "1.0"
    source_document: str
    source_sha256: str
    document_class: DrawingDocumentClass
    candidate_count: int | None = Field(default=None, ge=0)
    selected_candidate_id: str | None = None
    selection_required: bool
    proposals: list[ConfirmationFieldProposal]
    required_manual_fields: list[str] = Field(default_factory=list)
    completed_manual_values: dict[str, Any] = Field(default_factory=dict)
    status: ConfirmationWorkflowStatus
    automatic_overwrite_permitted: bool = False
    canonical_configuration_created: bool = False
    pricing_invoked: bool = False


def _workflow_status(
    contract: CustomerConfirmationContract,
) -> ConfirmationWorkflowStatus:
    if contract.selection_required:
        return ConfirmationWorkflowStatus.SELECTION_REQUIRED
    if any(proposal.unsupported for proposal in contract.proposals):
        return ConfirmationWorkflowStatus.BLOCKED
    unresolved_proposals = any(
        proposal.confirmation_required
        and proposal.customer_decision == CustomerDecision.PENDING
        for proposal in contract.proposals
    )
    unresolved_manual = any(
        name not in contract.completed_manual_values
        for name in contract.required_manual_fields
    )
    if unresolved_proposals or unresolved_manual:
        return ConfirmationWorkflowStatus.REQUIRES_CONFIRMATION
    return ConfirmationWorkflowStatus.READY_FOR_CONFIGURATION_REVIEW


def build_customer_confirmation_contract(
    recognition: DeterministicRecognitionResult,
    *,
    document_class: DrawingDocumentClass,
    candidate_count: int | None,
    selected_candidate_id: str | None,
) -> CustomerConfirmationContract:
    """Create a UI-neutral review contract without producing QuoteInputs."""

    document = recognition.extraction.document
    selection_required = candidate_count != 1 or selected_candidate_id is None
    proposals: list[ConfirmationFieldProposal] = []
    for name, result in recognition.field_results.items():
        extracted = getattr(recognition.extraction.fields, name)
        sources = extracted.evidence
        source = sources[0] if sources else None
        validation_status = recognition.validation.field_outcomes.get(
            name, FieldStatus(extracted.status)
        )
        unsupported = validation_status in {
            FieldStatus.UNSUPPORTED,
            FieldStatus.CONFLICT_DETECTED,
        }
        value_present = extracted.value is not None or bool(result.candidate_values)
        confirmation_required = (
            name in CRITICAL_FIELDS
            or (
                value_present
                and result.evidence_classification
                in {
                    EvidenceClassification.REQUIRES_CONFIRMATION,
                    EvidenceClassification.AMBIGUOUS,
                }
            )
            or (value_present and unsupported)
        )
        proposals.append(
            ConfirmationFieldProposal(
                extraction_field=name,
                canonical_field=EXTRACTION_TO_CANONICAL.get(name),
                proposed_value=extracted.value,
                normalized_unit=extracted.normalized_unit,
                raw_text=extracted.raw_text or result.raw_text,
                source_document=document.filename,
                source_sha256=document.sha256,
                source_page=source.page_number if source else None,
                source_bbox=source.bbox if source else None,
                source_coordinate_unit=(source.coordinate_unit if source else None),
                evidence_status=result.evidence_classification,
                validation_status=validation_status,
                confirmation_required=confirmation_required,
                unsupported=unsupported,
                competing_values=result.candidate_values,
            )
        )
    contract = CustomerConfirmationContract(
        source_document=document.filename,
        source_sha256=document.sha256,
        document_class=document_class,
        candidate_count=candidate_count,
        selected_candidate_id=selected_candidate_id,
        selection_required=selection_required,
        proposals=proposals,
        required_manual_fields=sorted(
            set(recognition.validation.canonical_candidate.missing_required_fields)
        ),
        status=ConfirmationWorkflowStatus.REQUIRES_CONFIRMATION,
    )
    return contract.model_copy(update={"status": _workflow_status(contract)})


def record_customer_decision(
    contract: CustomerConfirmationContract,
    extraction_field: str,
    decision: CustomerDecision,
    *,
    customer_value: ScalarValue | None = None,
    reason: str | None = None,
) -> CustomerConfirmationContract:
    """Return a new contract; the original proposal and evidence remain intact."""

    matches = [
        proposal
        for proposal in contract.proposals
        if proposal.extraction_field == extraction_field
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate extraction field: {extraction_field}")
    original = matches[0]
    if decision == CustomerDecision.CONFIRMED and original.proposed_value is None:
        raise ValueError("a missing proposal cannot be confirmed")
    if decision == CustomerDecision.CORRECTED and customer_value is None:
        raise ValueError("a corrected proposal requires customer_value")
    if decision in {CustomerDecision.CONFIRMED, CustomerDecision.REJECTED}:
        customer_value = None
    updated = original.model_copy(
        update={
            "customer_decision": decision,
            "customer_value": customer_value,
            "decision_reason": reason,
        }
    )
    proposals = [
        updated if proposal.extraction_field == extraction_field else proposal
        for proposal in contract.proposals
    ]
    result = contract.model_copy(update={"proposals": proposals})
    return result.model_copy(update={"status": _workflow_status(result)})


def record_manual_value(
    contract: CustomerConfirmationContract,
    canonical_field: str,
    value: Any,
) -> CustomerConfirmationContract:
    """Record a manual field without constructing or pricing a QuoteInputs object."""

    if canonical_field not in contract.required_manual_fields:
        raise ValueError(f"field is not required by this contract: {canonical_field}")
    values = {**contract.completed_manual_values, canonical_field: value}
    result = contract.model_copy(update={"completed_manual_values": values})
    return result.model_copy(update={"status": _workflow_status(result)})
