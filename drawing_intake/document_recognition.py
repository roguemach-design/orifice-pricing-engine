from __future__ import annotations

import time

from pydantic import Field

from .classification import DocumentClassificationResult, classify_drawing_document
from .documents import NormalizedDocument
from .models import DocumentStructureAssessment, StrictModel
from .ocr import TesseractLocalOcrEngine, recover_plus_minus_glyphs
from .page_observations import observe_page_locally
from .raster_structure import detect_raster_plate_structure
from .structure import assess_document_structure
from .table_schedule import TableScheduleResult, parse_plate_schedule


class DocumentRecognitionTimings(StrictModel):
    classification_seconds: float = Field(ge=0)
    rendering_and_ocr_seconds: float = Field(ge=0)
    table_interpretation_seconds: float = Field(ge=0)
    targeted_table_ocr_seconds: float = Field(default=0.0, ge=0)
    total_seconds: float = Field(ge=0)


class DeterministicDocumentRecognitionResult(StrictModel):
    structure: DocumentStructureAssessment
    classification: DocumentClassificationResult
    table_schedule: TableScheduleResult | None = None
    page_rotation_degrees: int
    ocr_token_count: int = Field(ge=0)
    canonical_candidate_created: bool = False
    timings: DocumentRecognitionTimings


def recognize_document_structure(
    document: NormalizedDocument,
    *,
    ocr_engine: TesseractLocalOcrEngine | None = None,
) -> DeterministicDocumentRecognitionResult:
    """Classify a whole document without creating a plate quote candidate."""

    started = time.perf_counter()
    engine = ocr_engine or TesseractLocalOcrEngine()
    structure = assess_document_structure(document)
    ocr_started = time.perf_counter()
    ocr, rotation, rendered = observe_page_locally(document, ocr_engine=engine)
    ocr = recover_plus_minus_glyphs(ocr, rendered)
    if structure.status == "unknown":
        raster_structure = detect_raster_plate_structure(rendered)
        if raster_structure.status != "unknown":
            structure = raster_structure
    rendering_and_ocr_seconds = time.perf_counter() - ocr_started
    table_started = time.perf_counter()
    schedule = parse_plate_schedule(
        rendered,
        ocr,
        document=document,
        ocr_engine=engine,
    )
    observed_text = " ".join(token.interpreted_text for token in ocr.tokens)
    table_seconds = time.perf_counter() - table_started
    classification_started = time.perf_counter()
    classification = classify_drawing_document(
        document,
        structure,
        observed_text=observed_text,
        detected_table_rows=len(schedule.candidates),
    )
    classification_seconds = time.perf_counter() - classification_started
    if classification.document_class not in {
        "table_driven_plate_schedule",
        "reference_vendor_datasheet",
    }:
        schedule_result = None
    else:
        schedule_result = schedule
    return DeterministicDocumentRecognitionResult(
        structure=structure,
        classification=classification,
        table_schedule=schedule_result,
        page_rotation_degrees=rotation,
        ocr_token_count=len(ocr.tokens),
        canonical_candidate_created=False,
        timings=DocumentRecognitionTimings(
            classification_seconds=classification_seconds,
            rendering_and_ocr_seconds=rendering_and_ocr_seconds,
            table_interpretation_seconds=table_seconds,
            targeted_table_ocr_seconds=schedule.targeted_ocr_seconds,
            total_seconds=time.perf_counter() - started,
        ),
    )
