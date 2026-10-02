"""Isolated drawing-intake research spike for O-Plates."""

from .assisted_intake import (
    AssistedDocumentReview,
    ProcessedAssistedUpload,
    inspect_assisted_upload,
    manual_session_for_upload,
    select_assisted_candidate,
)
from .assisted_quote import (
    AssistedQuoteSession,
    CanonicalConfigurationReview,
    PricingHandoffPreview,
    build_assisted_quote_session,
    build_pricing_handoff_preview,
    confirm_configuration,
    review_assisted_quote,
    set_customer_value,
    availability_from_active_config,
)
from .classification import DocumentClassificationResult, DrawingDocumentClass
from .confirmation_contract import (
    CustomerConfirmationContract,
    build_customer_confirmation_contract,
)
from .deterministic import DeterministicRecognitionResult, DeterministicRegionRecognizer
from .document_recognition import (
    DeterministicDocumentRecognitionResult,
    recognize_document_structure,
)
from .models import DrawingExtractionResult, DrawingFields
from .pipeline import DrawingIntakePipeline, DrawingPipelineResult
from .regions import DerivedDrawingRegion
from .reconciliation_workflow import (
    ReconciliationEntryAssessment,
    ReconciliationReview,
    assess_reconciliation_entry,
    reconcile_selected_region,
)

__all__ = [
    "AssistedDocumentReview",
    "AssistedQuoteSession",
    "CanonicalConfigurationReview",
    "ProcessedAssistedUpload",
    "PricingHandoffPreview",
    "build_assisted_quote_session",
    "build_pricing_handoff_preview",
    "confirm_configuration",
    "inspect_assisted_upload",
    "manual_session_for_upload",
    "review_assisted_quote",
    "select_assisted_candidate",
    "set_customer_value",
    "availability_from_active_config",
    "DrawingExtractionResult",
    "CustomerConfirmationContract",
    "build_customer_confirmation_contract",
    "DrawingDocumentClass",
    "DocumentClassificationResult",
    "DrawingFields",
    "DrawingIntakePipeline",
    "DrawingPipelineResult",
    "DerivedDrawingRegion",
    "DeterministicRecognitionResult",
    "DeterministicRegionRecognizer",
    "DeterministicDocumentRecognitionResult",
    "recognize_document_structure",
    "ReconciliationEntryAssessment",
    "ReconciliationReview",
    "assess_reconciliation_entry",
    "reconcile_selected_region",
]
