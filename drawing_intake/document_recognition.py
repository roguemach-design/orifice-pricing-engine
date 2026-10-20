from __future__ import annotations

import time
import re

from pydantic import Field

from .classification import (
    DocumentClassificationResult,
    DrawingDocumentClass,
    classify_drawing_document,
)
from .documents import NormalizedDocument
from .models import DocumentStructureAssessment, StrictModel
from .ocr import TesseractLocalOcrEngine, recover_plus_minus_glyphs
from .page_observations import observe_page_locally
from .raster_structure import detect_raster_plate_structure
from .structure import assess_document_structure
from .table_schedule import TableScheduleResult, parse_plate_schedule
from .spatial import build_spatial_lines


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


_IDENTIFIER_LABEL = re.compile(
    r"\b(?:DRAWING|DWG|PART|CONTRACT)\s*(?:NO\.?|NUMBER)(?!\w)|\bTEST\s*ID\b",
    re.IGNORECASE,
)


def _labeled_document_identifier(ocr) -> bool:
    """Require an identifier value bound to a generic drawing/part label."""

    for engine_pass in {token.engine_pass for token in ocr.tokens}:
        lines = build_spatial_lines(
            [token for token in ocr.tokens if token.engine_pass == engine_pass]
        )
        for label in lines:
            match = _IDENTIFIER_LABEL.search(label.raw_text)
            if not match:
                continue
            value_lines = [label, *lines]
            for value_line in value_lines:
                if value_line is label:
                    value = label.raw_text[match.end() :].strip(" :#\t")
                else:
                    label_height = max(1, label.bbox[3] - label.bbox[1])
                    x_gap = value_line.bbox[0] - label.bbox[2]
                    vertical_overlap = max(
                        0,
                        min(value_line.bbox[3], label.bbox[3])
                        - max(value_line.bbox[1], label.bbox[1]),
                    )
                    same_row = (
                        0 <= x_gap <= label_height * 15
                        and vertical_overlap
                        >= min(label_height, value_line.bbox[3] - value_line.bbox[1])
                        * 0.5
                    )
                    below_label = (
                        0 <= value_line.bbox[1] - label.bbox[3] <= label_height * 2
                        and abs(value_line.bbox[0] - label.bbox[0]) <= label_height * 6
                    )
                    if not (same_row or below_label):
                        continue
                    value = value_line.raw_text.strip()
                if re.fullmatch(
                    r"[A-Z0-9][A-Z0-9._/-]{2,39}", value, re.IGNORECASE
                ) and any(char.isdigit() for char in value):
                    return True
    return False


def recognize_document_structure(
    document: NormalizedDocument,
    *,
    ocr_engine: TesseractLocalOcrEngine | None = None,
) -> DeterministicDocumentRecognitionResult:
    """Classify a whole document without creating a plate quote candidate."""

    started = time.perf_counter()
    engine = ocr_engine or TesseractLocalOcrEngine()
    structure = assess_document_structure(document)
    preliminary_reference: DocumentClassificationResult | None = None
    preliminary_classification_seconds = 0.0

    def decisive_reference(ocr) -> bool:
        nonlocal preliminary_reference, preliminary_classification_seconds
        classification_started = time.perf_counter()
        candidate = classify_drawing_document(
            document,
            structure,
            observed_text=" ".join(token.interpreted_text for token in ocr.tokens),
        )
        preliminary_classification_seconds = (
            time.perf_counter() - classification_started
        )
        if candidate.document_class == DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET:
            preliminary_reference = candidate
            return True
        return False

    ocr_started = time.perf_counter()
    ocr, rotation, rendered = observe_page_locally(
        document,
        ocr_engine=engine,
        decisive_initial_observation=decisive_reference,
    )
    if preliminary_reference is not None:
        # This is the existing two-part generic reference rule, independent of
        # geometry and schedule rows. No quote candidates or field readings are
        # produced; preserve the manual configuration without further OCR.
        return DeterministicDocumentRecognitionResult(
            structure=structure,
            classification=preliminary_reference,
            page_rotation_degrees=rotation,
            ocr_token_count=len(ocr.tokens),
            timings=DocumentRecognitionTimings(
                classification_seconds=preliminary_classification_seconds,
                rendering_and_ocr_seconds=time.perf_counter() - ocr_started,
                table_interpretation_seconds=0.0,
                total_seconds=time.perf_counter() - started,
            ),
        )
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
        labeled_document_identifier=_labeled_document_identifier(ocr),
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
