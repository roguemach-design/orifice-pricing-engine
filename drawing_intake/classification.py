from __future__ import annotations

import re
from enum import Enum

from pydantic import Field

from .documents import NormalizedDocument
from .models import DocumentStructureAssessment, StrictModel


class DrawingDocumentClass(str, Enum):
    SINGLE_PLATE_DRAWING = "single_plate_drawing"
    MULTI_PLATE_DRAWING = "multi_plate_drawing"
    TABLE_DRIVEN_PLATE_SCHEDULE = "table_driven_plate_schedule"
    REFERENCE_VENDOR_DATASHEET = "reference_vendor_datasheet"
    AMBIGUOUS_DOCUMENT = "ambiguous_document"
    UNSUPPORTED_DOCUMENT = "unsupported_document"


class DocumentClassificationResult(StrictModel):
    document_class: DrawingDocumentClass
    quote_specific: bool
    candidate_count: int | None = Field(default=None, ge=0)
    evidence_rules: list[str] = Field(default_factory=list)
    reason: str


def classify_drawing_document(
    document: NormalizedDocument,
    structure: DocumentStructureAssessment,
    *,
    observed_text: str = "",
    detected_table_rows: int = 0,
) -> DocumentClassificationResult:
    """Classify from document structure and generic engineering phrases.

    Company names and drawing identifiers are intentionally not inputs.
    """

    text = " ".join(
        " ".join(re.sub(r"[^A-Z0-9.]+", " ", value.upper()).split())
        for value in (observed_text, *(page.text for page in document.pages))
    )
    rules: list[str] = []

    product_headings = sum(
        phrase in text
        for phrase in ("PADDLE ORIFICE PLATE", "UNIVERSAL TYPE ORIFICE PLATE")
    )
    variable_legend = bool(
        re.search(r"\bD\s+(?:IS|=).*\b(?:BORE|DIAMETER|THICKNESS)\b", text)
        or ("ORIFICE BORE DIAMETER" in text and "PLATE THICKNESS" in text)
    )
    catalog_language = any(
        phrase in text
        for phrase in ("CAT NO", "CATALOG", "ORDERING INFORMATION", "SIZE SELECTION")
    )
    if product_headings >= 2:
        rules.append("multiple_generic_product_type_headings")
    if variable_legend:
        rules.append("symbolic_dimension_variable_legend")
    if catalog_language:
        rules.append("catalog_or_ordering_language")
    if (product_headings >= 2 and variable_legend) or (
        variable_legend and catalog_language and detected_table_rows >= 2
    ):
        return DocumentClassificationResult(
            document_class=DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET,
            quote_specific=False,
            candidate_count=None,
            evidence_rules=rules,
            reason="Generic product geometry/variables and selection data do not identify one ordered plate.",
        )

    schedule_headers = sum(
        phrase in text
        for phrase in ("ORIFICE PLATE DIM", "TAG NO", "BORE", "QTY", "QUANTITY")
    )
    if detected_table_rows >= 2 and schedule_headers >= 3:
        return DocumentClassificationResult(
            document_class=DrawingDocumentClass.TABLE_DRIVEN_PLATE_SCHEDULE,
            quote_specific=True,
            candidate_count=detected_table_rows,
            evidence_rules=[
                "ruled_multirow_table",
                "plate_schedule_semantic_headers",
            ],
            reason="A plate schedule contains multiple explicit configuration rows.",
        )

    if structure.status == "multiple_candidates":
        return DocumentClassificationResult(
            document_class=DrawingDocumentClass.MULTI_PLATE_DRAWING,
            quote_specific=True,
            candidate_count=structure.candidate_region_count,
            evidence_rules=["multiple_concentric_plate_profile_regions"],
            reason="Multiple dimensioned plate-like profile regions require selection.",
        )
    if structure.status == "single_candidate":
        return DocumentClassificationResult(
            document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
            quote_specific=True,
            candidate_count=1,
            evidence_rules=["single_concentric_plate_profile_region"],
            reason="One dimensioned plate-like profile region was found.",
        )
    return DocumentClassificationResult(
        document_class=DrawingDocumentClass.AMBIGUOUS_DOCUMENT,
        quote_specific=False,
        candidate_count=None,
        evidence_rules=rules,
        reason="Evidence is insufficient to identify a unique quote-specific plate drawing.",
    )
