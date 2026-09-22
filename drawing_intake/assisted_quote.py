from __future__ import annotations

import hashlib
import json
import math
import re
from enum import Enum
from typing import Any, Mapping

from pydantic import Field

import tuning_knobs as pricing_config
from pricing_engine import QuoteInputs

from .classification import DrawingDocumentClass
from .confirmation_contract import (
    ConfirmationFieldProposal,
    CustomerConfirmationContract,
)
from .models import FieldStatus, MeasurementUnit, ScalarValue, StrictModel
from .value_normalization import to_inches


class ConfigurationValueOrigin(str, Enum):
    DRAWING = "drawing"
    CUSTOMER = "customer"


class FieldAttentionKind(str, Enum):
    MISSING_REQUIRED = "missing_required"
    INVALID = "invalid"
    CONFIRMATION_REQUIRED = "confirmation_required"
    UNSUPPORTED = "unsupported"
    OPTIONAL = "optional"


class AssistedQuoteStatus(str, Enum):
    SELECTION_REQUIRED = "selection_required"
    MANUAL_CONFIGURATION = "manual_configuration"
    INCOMPLETE = "incomplete"
    NEEDS_CONFIRMATION = "needs_confirmation"
    READY_FOR_PRICING = "ready_for_pricing"


class CanonicalFormAvailability(StrictModel):
    materials: list[str]
    thicknesses_by_material: dict[str, list[float]]
    tolerance_options_in: list[float]
    lead_times_days: list[int]
    max_paddle_dia_in: float = Field(gt=0)
    max_bore_dia_in: float = Field(gt=0)
    max_handle_label_chars: int = Field(gt=0)


class CanonicalFieldValue(StrictModel):
    value: ScalarValue
    origin: ConfigurationValueOrigin
    extraction_field: str | None = None


class FieldAttention(StrictModel):
    canonical_field: str
    label: str
    kind: FieldAttentionKind
    message: str
    blocks_readiness: bool


class AssistedQuoteSession(StrictModel):
    schema_version: str = "1.0"
    source_document: str | None = None
    source_sha256: str | None = None
    document_class: DrawingDocumentClass | None = None
    candidate_count: int | None = Field(default=None, ge=0)
    selected_candidate_id: str | None = None
    selection_required: bool = False
    proposals: list[ConfirmationFieldProposal] = Field(default_factory=list)
    configuration: dict[str, CanonicalFieldValue] = Field(default_factory=dict)
    rejected_extraction_fields: list[str] = Field(default_factory=list)
    confirmation_fingerprint: str | None = None
    pricing_invoked: bool = False
    checkout_invoked: bool = False
    order_created: bool = False


class CanonicalConfigurationReview(StrictModel):
    status: AssistedQuoteStatus
    attention: list[FieldAttention]
    configuration: dict[str, Any]
    missing_required_fields: list[str]
    invalid_fields: list[str]
    unsupported_fields: list[str]
    confirmation_required_fields: list[str]
    confirmation_current: bool


class PricingHandoffPreview(StrictModel):
    schema_version: str = "1.0"
    destination: str = (
        "QuoteRequest -> QuoteInputs -> existing API-authoritative pricing"
    )
    quote_request: dict[str, Any]
    pricing_invoked: bool = False
    checkout_invoked: bool = False
    order_created: bool = False


FIELD_LABELS = {
    "quantity": "Quantity",
    "material": "Material",
    "thickness": "Plate thickness",
    "handle_width": "Handle width",
    "handle_length_from_bore": "Handle length from bore center",
    "paddle_dia": "Plate outside diameter",
    "bore_dia": "Bore diameter",
    "bore_tolerance": "Bore tolerance",
    "chamfer": "Chamfer",
    "ships_in_days": "Lead time",
    "handle_label": "Handle marking",
    "chamfer_width": "Chamfer width",
}

_DIMENSION_FIELDS = {
    "outside_diameter",
    "bore_diameter",
    "thickness",
    "bore_tolerance_plus",
    "bore_tolerance_minus",
    "chamfer_width",
}

_DIRECT_EXTRACTION_MAPPING = {
    "outside_diameter": "paddle_dia",
    "bore_diameter": "bore_dia",
    "thickness": "thickness",
    "material": "material",
    "quantity": "quantity",
    "chamfer_present": "chamfer",
    "chamfer_width": "chamfer_width",
    "marking_text": "handle_label",
}

_NON_USABLE_STATUSES = {
    FieldStatus.NOT_DETECTED.value,
    FieldStatus.AMBIGUOUS.value,
    FieldStatus.UNSUPPORTED.value,
    FieldStatus.CONFLICT_DETECTED.value,
    FieldStatus.UNREADABLE.value,
}


def local_form_availability() -> CanonicalFormAvailability:
    """Expose product availability without calling pricing or an API."""

    return CanonicalFormAvailability(
        materials=sorted(pricing_config.PRICE_PER_SQ_IN),
        thicknesses_by_material={
            material: sorted(float(value) for value in thicknesses)
            for material, thicknesses in pricing_config.PRICE_PER_SQ_IN.items()
        },
        tolerance_options_in=sorted(
            float(value) for value in pricing_config.INSPECTION_MINS_BY_TOL
        ),
        lead_times_days=sorted(
            int(value) for value in pricing_config.LEAD_TIME_MULTIPLIER
        ),
        max_paddle_dia_in=float(pricing_config.MAX_PADDLE_DIA_IN),
        max_bore_dia_in=float(pricing_config.MAX_BORE_DIA_IN),
        max_handle_label_chars=int(pricing_config.MAX_HANDLE_LABEL_CHARS),
    )


def availability_from_active_config(
    active_config: Mapping[str, Any],
) -> CanonicalFormAvailability:
    """Validate the actual public /config/active response for assisted review."""

    materials = [str(value) for value in active_config.get("materials") or []]
    thicknesses = {
        str(material): sorted(float(value) for value in values)
        for material, values in (
            active_config.get("thicknesses_by_material") or {}
        ).items()
        if str(material) in materials
    }
    lead_times = sorted(
        int(value) for value in active_config.get("lead_times_days") or []
    )
    tolerances = sorted(
        float(value) for value in active_config.get("tolerance_options_in") or []
    )
    if not materials:
        raise ValueError("active configuration has no enabled materials")
    if any(not thicknesses.get(material) for material in materials):
        raise ValueError(
            "active configuration is missing thicknesses for an enabled material"
        )
    if not lead_times:
        raise ValueError("active configuration has no enabled lead times")
    if not tolerances:
        raise ValueError("active configuration has no tolerance options")
    return CanonicalFormAvailability(
        materials=materials,
        thicknesses_by_material=thicknesses,
        tolerance_options_in=tolerances,
        lead_times_days=lead_times,
        max_paddle_dia_in=float(active_config["max_paddle_dia_in"]),
        max_bore_dia_in=float(active_config["max_bore_dia_in"]),
        max_handle_label_chars=int(active_config["max_handle_label_chars"]),
    )


def canonical_required_fields(*, chamfer: bool | None = None) -> list[str]:
    """Derive required fields from the real QuoteInputs model plus UI dependencies."""

    fields = [
        name
        for name, model_field in QuoteInputs.model_fields.items()
        if model_field.is_required()
    ]
    if chamfer is True:
        fields.append("chamfer_width")
    return fields


def _field_status(value: FieldStatus | str) -> str:
    return value.value if isinstance(value, FieldStatus) else str(value)


def _normalized_proposal_value(
    proposal: ConfirmationFieldProposal,
) -> ScalarValue | None:
    value = proposal.proposed_value
    if proposal.extraction_field in _DIMENSION_FIELDS and isinstance(
        value, (int, float)
    ):
        return round(to_inches(float(value), proposal.normalized_unit), 9)
    return value


def _proposal_is_usable(proposal: ConfirmationFieldProposal) -> bool:
    return (
        proposal.proposed_value is not None
        and not proposal.unsupported
        and _field_status(proposal.validation_status) not in _NON_USABLE_STATUSES
    )


def _supported_tolerance(
    proposals: list[ConfirmationFieldProposal],
    availability: CanonicalFormAvailability,
) -> float | None:
    indexed = {proposal.extraction_field: proposal for proposal in proposals}
    plus = indexed.get("bore_tolerance_plus")
    minus = indexed.get("bore_tolerance_minus")
    if (
        not plus
        or not minus
        or not _proposal_is_usable(plus)
        or not _proposal_is_usable(minus)
    ):
        return None
    plus_value = _normalized_proposal_value(plus)
    minus_value = _normalized_proposal_value(minus)
    if not isinstance(plus_value, (int, float)) or not isinstance(
        minus_value, (int, float)
    ):
        return None
    if not math.isclose(float(plus_value), float(minus_value), abs_tol=1e-9):
        return None
    return next(
        (
            value
            for value in availability.tolerance_options_in
            if math.isclose(value, float(plus_value), abs_tol=1e-9)
        ),
        None,
    )


def _proposal_values(
    proposals: list[ConfirmationFieldProposal],
    availability: CanonicalFormAvailability,
) -> dict[str, CanonicalFieldValue]:
    output: dict[str, CanonicalFieldValue] = {}
    for proposal in proposals:
        canonical = _DIRECT_EXTRACTION_MAPPING.get(proposal.extraction_field)
        if canonical is None or not _proposal_is_usable(proposal):
            continue
        value = _normalized_proposal_value(proposal)
        if value is None:
            continue
        if canonical == "material" and str(value) not in availability.materials:
            continue
        if canonical == "thickness" and not any(
            any(math.isclose(float(value), option, abs_tol=1e-9) for option in options)
            for options in availability.thicknesses_by_material.values()
        ):
            continue
        output[canonical] = CanonicalFieldValue(
            value=value,
            origin=ConfigurationValueOrigin.DRAWING,
            extraction_field=proposal.extraction_field,
        )
    tolerance = _supported_tolerance(proposals, availability)
    if tolerance is not None:
        output["bore_tolerance"] = CanonicalFieldValue(
            value=tolerance,
            origin=ConfigurationValueOrigin.DRAWING,
            extraction_field="bore_tolerance_plus+bore_tolerance_minus",
        )
    return output


def build_assisted_quote_session(
    contract: CustomerConfirmationContract,
    *,
    availability: CanonicalFormAvailability | None = None,
) -> AssistedQuoteSession:
    """Map usable proposals into editable state; ambiguous/unsupported values stay evidence-only."""

    product = availability or local_form_availability()
    return AssistedQuoteSession(
        source_document=contract.source_document,
        source_sha256=contract.source_sha256,
        document_class=contract.document_class,
        candidate_count=contract.candidate_count,
        selected_candidate_id=contract.selected_candidate_id,
        selection_required=contract.selection_required,
        proposals=contract.proposals,
        configuration=_proposal_values(contract.proposals, product),
    )


def build_manual_quote_session(
    *,
    source_document: str | None = None,
    source_sha256: str | None = None,
    document_class: DrawingDocumentClass | None = None,
) -> AssistedQuoteSession:
    """Create a normal manual path for unreadable, reference, or unsupported uploads."""

    return AssistedQuoteSession(
        source_document=source_document,
        source_sha256=source_sha256,
        document_class=document_class,
    )


def set_customer_value(
    session: AssistedQuoteSession,
    canonical_field: str,
    value: ScalarValue | None,
) -> AssistedQuoteSession:
    if canonical_field not in QuoteInputs.model_fields:
        raise ValueError(f"unknown canonical QuoteInputs field: {canonical_field}")
    configuration = dict(session.configuration)
    if value is None or (isinstance(value, str) and not value.strip()):
        configuration.pop(canonical_field, None)
    else:
        configuration[canonical_field] = CanonicalFieldValue(
            value=value,
            origin=ConfigurationValueOrigin.CUSTOMER,
        )
    return session.model_copy(
        update={
            "configuration": configuration,
            "confirmation_fingerprint": None,
        }
    )


def reject_drawing_proposal(
    session: AssistedQuoteSession,
    extraction_field: str,
) -> AssistedQuoteSession:
    matches = [
        proposal
        for proposal in session.proposals
        if proposal.extraction_field == extraction_field
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate extraction field: {extraction_field}")
    configuration = {
        name: state
        for name, state in session.configuration.items()
        if not (
            state.origin == ConfigurationValueOrigin.DRAWING
            and state.extraction_field
            and extraction_field in state.extraction_field.split("+")
        )
    }
    rejected = list(
        dict.fromkeys([*session.rejected_extraction_fields, extraction_field])
    )
    return session.model_copy(
        update={
            "configuration": configuration,
            "rejected_extraction_fields": rejected,
            "confirmation_fingerprint": None,
        }
    )


def _plain_configuration(session: AssistedQuoteSession) -> dict[str, Any]:
    values = {name: state.value for name, state in session.configuration.items()}
    if values.get("chamfer") is False:
        values["chamfer_width"] = None
    if not str(values.get("handle_label") or "").strip():
        values["handle_label"] = "No label"
    return values


def _configuration_fingerprint(values: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(values), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validation_errors(
    values: Mapping[str, Any],
    availability: CanonicalFormAvailability,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    number_fields = {
        "thickness",
        "handle_width",
        "handle_length_from_bore",
        "paddle_dia",
        "bore_dia",
        "bore_tolerance",
    }
    for field in number_fields:
        if field in values and values[field] is not None:
            try:
                if float(values[field]) <= 0:
                    errors[field] = f"{FIELD_LABELS[field]} must be greater than zero."
            except (TypeError, ValueError):
                errors[field] = f"{FIELD_LABELS[field]} must be numeric."

    quantity = values.get("quantity")
    if quantity is not None and (
        not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1
    ):
        errors["quantity"] = "Quantity must be a whole number of at least one."

    material = values.get("material")
    if material is not None and material not in availability.materials:
        errors["material"] = "The selected material is not available for instant quote."

    thickness = values.get("thickness")
    if material in availability.thicknesses_by_material and thickness is not None:
        if not any(
            math.isclose(float(thickness), option, abs_tol=1e-9)
            for option in availability.thicknesses_by_material[str(material)]
        ):
            errors["thickness"] = (
                "The selected thickness is not available for this material."
            )

    paddle = values.get("paddle_dia")
    bore = values.get("bore_dia")
    if isinstance(paddle, (int, float)) and paddle > availability.max_paddle_dia_in:
        errors["paddle_dia"] = (
            "Plate outside diameter exceeds the instant-quote maximum."
        )
    if isinstance(bore, (int, float)) and bore > availability.max_bore_dia_in:
        errors["bore_dia"] = "Bore diameter exceeds the instant-quote maximum."
    if (
        isinstance(paddle, (int, float))
        and isinstance(bore, (int, float))
        and bore >= paddle
    ):
        errors["bore_dia"] = (
            "Bore diameter must be smaller than the plate outside diameter."
        )

    handle_length = values.get("handle_length_from_bore")
    if (
        isinstance(handle_length, (int, float))
        and isinstance(paddle, (int, float))
        and handle_length <= paddle / 2.0
    ):
        errors["handle_length_from_bore"] = (
            "Handle length from bore center must extend beyond the plate radius."
        )

    tolerance = values.get("bore_tolerance")
    if tolerance is not None and not any(
        math.isclose(float(tolerance), option, abs_tol=1e-9)
        for option in availability.tolerance_options_in
    ):
        errors["bore_tolerance"] = "The selected bore tolerance is not supported."

    lead_time = values.get("ships_in_days")
    if lead_time is not None and lead_time not in availability.lead_times_days:
        errors["ships_in_days"] = "The selected lead time is not currently available."

    chamfer = values.get("chamfer")
    if chamfer is not None and not isinstance(chamfer, bool):
        errors["chamfer"] = "Chamfer must be explicitly selected or cleared."
    if chamfer is True:
        chamfer_width = values.get("chamfer_width")
        if chamfer_width is not None:
            try:
                if float(chamfer_width) <= 0:
                    errors["chamfer_width"] = "Chamfer width must be greater than zero."
            except (TypeError, ValueError):
                errors["chamfer_width"] = "Chamfer width must be numeric."

    label = values.get("handle_label")
    if label is not None and len(str(label)) > availability.max_handle_label_chars:
        errors["handle_label"] = (
            f"Handle marking must be {availability.max_handle_label_chars} characters or fewer."
        )
    elif label is not None and not re.fullmatch(
        r"[A-Za-z0-9 .,_/#()+\-:=]+", str(label)
    ):
        errors["handle_label"] = (
            "Handle marking contains characters the existing quote request does not accept."
        )
    return errors


def review_assisted_quote(
    session: AssistedQuoteSession,
    *,
    availability: CanonicalFormAvailability | None = None,
) -> CanonicalConfigurationReview:
    product = availability or local_form_availability()
    values = _plain_configuration(session)
    required = canonical_required_fields(chamfer=values.get("chamfer"))
    missing = [
        field
        for field in required
        if field not in values or values[field] is None or values[field] == ""
    ]
    errors = _validation_errors(values, product)
    unsupported_proposals = [
        proposal
        for proposal in session.proposals
        if proposal.unsupported
        and proposal.extraction_field not in session.rejected_extraction_fields
    ]
    unsupported_fields = sorted(
        {
            proposal.canonical_field or proposal.extraction_field
            for proposal in unsupported_proposals
        }
    )
    drawing_fields = sorted(
        name
        for name, state in session.configuration.items()
        if state.origin == ConfigurationValueOrigin.DRAWING
    )
    fingerprint = _configuration_fingerprint(values)
    confirmation_current = session.confirmation_fingerprint == fingerprint

    attention: list[FieldAttention] = []
    for field in missing:
        attention.append(
            FieldAttention(
                canonical_field=field,
                label=FIELD_LABELS.get(field, field),
                kind=FieldAttentionKind.MISSING_REQUIRED,
                message="Needs your input.",
                blocks_readiness=True,
            )
        )
    for field, message in errors.items():
        attention.append(
            FieldAttention(
                canonical_field=field,
                label=FIELD_LABELS.get(field, field),
                kind=FieldAttentionKind.INVALID,
                message=message,
                blocks_readiness=True,
            )
        )
    for proposal in unsupported_proposals:
        field = proposal.canonical_field or proposal.extraction_field
        attention.append(
            FieldAttention(
                canonical_field=field,
                label=FIELD_LABELS.get(field, field),
                kind=FieldAttentionKind.UNSUPPORTED,
                message=(
                    f"Drawing appears to specify {proposal.raw_text or proposal.proposed_value!s}; "
                    "the instant-quote configuration does not support it."
                ),
                blocks_readiness=False,
            )
        )
    if not confirmation_current:
        for field in drawing_fields:
            attention.append(
                FieldAttention(
                    canonical_field=field,
                    label=FIELD_LABELS.get(field, field),
                    kind=FieldAttentionKind.CONFIRMATION_REQUIRED,
                    message="Prefilled from drawing; review before confirming.",
                    blocks_readiness=False,
                )
            )

    if session.selection_required:
        status = AssistedQuoteStatus.SELECTION_REQUIRED
    elif missing or errors:
        status = AssistedQuoteStatus.INCOMPLETE
    elif not confirmation_current:
        status = AssistedQuoteStatus.NEEDS_CONFIRMATION
    else:
        status = AssistedQuoteStatus.READY_FOR_PRICING
    if not session.proposals and status == AssistedQuoteStatus.INCOMPLETE:
        status = AssistedQuoteStatus.MANUAL_CONFIGURATION
    return CanonicalConfigurationReview(
        status=status,
        attention=attention,
        configuration=values,
        missing_required_fields=missing,
        invalid_fields=sorted(errors),
        unsupported_fields=unsupported_fields,
        confirmation_required_fields=drawing_fields if not confirmation_current else [],
        confirmation_current=confirmation_current,
    )


def confirm_configuration(
    session: AssistedQuoteSession,
    *,
    availability: CanonicalFormAvailability | None = None,
) -> AssistedQuoteSession:
    product = availability or local_form_availability()
    review = review_assisted_quote(session, availability=product)
    if session.selection_required:
        raise ValueError("a plate candidate must be selected before confirmation")
    if review.missing_required_fields or review.invalid_fields:
        raise ValueError("configuration must be complete and valid before confirmation")
    values = review.configuration
    QuoteInputs(**values)
    return session.model_copy(
        update={"confirmation_fingerprint": _configuration_fingerprint(values)}
    )


def build_pricing_handoff_preview(
    session: AssistedQuoteSession,
    *,
    availability: CanonicalFormAvailability | None = None,
) -> PricingHandoffPreview:
    product = availability or local_form_availability()
    review = review_assisted_quote(session, availability=product)
    if review.status != AssistedQuoteStatus.READY_FOR_PRICING:
        raise ValueError("customer-confirmed valid configuration is required")
    validated = QuoteInputs(**review.configuration)
    return PricingHandoffPreview(quote_request=validated.model_dump())
