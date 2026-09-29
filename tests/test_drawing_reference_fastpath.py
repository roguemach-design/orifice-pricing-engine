"""Generic reference preflight: abstain before unnecessary geometry and table work."""

import io
from pathlib import Path

import pytest
from PIL import Image

from drawing_intake import document_recognition as recognition
from drawing_intake.assisted_intake import inspect_assisted_upload
from drawing_intake.classification import DrawingDocumentClass
from drawing_intake.documents import normalize_document
from drawing_intake.ocr import (
    LocalOcrResult,
    OcrTokenObservation,
    TesseractLocalOcrEngine,
)


def _image() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (500, 700), "white").save(output, format="PNG")
    return output.getvalue()


class StubOcr:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def recognize(self, rendered, *, pass_prefix=""):
        self.calls += 1
        # Many short table tokens trigger the ordinary sideways-orientation
        # probe. The decisive reference evidence must stop that probe.
        words = [*self.text.split(), *(["0"] * 80)]
        return LocalOcrResult(
            engine="synthetic_local_observation",
            engine_version="test",
            region_id=rendered.region.region_id,
            dpi=rendered.dpi,
            page_segmentation_modes=[6],
            tokens=[
                OcrTokenObservation(
                    token_id=f"token-{index}",
                    region_id=rendered.region.region_id,
                    page_number=1,
                    raw_text=word,
                    pixel_bbox=(10, 10, 20, 20),
                    source_bbox=rendered.transform.pixel_bbox_to_pdf((10, 10, 20, 20)),
                    engine="stub",
                    engine_pass=f"{pass_prefix}psm6",
                    line_key="line-1",
                )
                for index, word in enumerate(words)
            ],
            ocr_seconds=0.0,
        )


def test_generic_reference_exits_before_rotation_geometry_and_table(monkeypatch):
    document = normalize_document(_image(), "generic-reference.png")
    engine = StubOcr(
        "PADDLE ORIFICE PLATE UNIVERSAL TYPE ORIFICE PLATE "
        "D IS ORIFICE BORE DIAMETER CATALOG SIZE SELECTION"
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Reference preflight must skip candidate geometry and table work")

    monkeypatch.setattr(recognition, "detect_raster_plate_structure", unexpected)
    monkeypatch.setattr(recognition, "parse_plate_schedule", unexpected)
    result = recognition.recognize_document_structure(document, ocr_engine=engine)

    assert engine.calls == 1
    assert (
        result.classification.document_class
        == DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET
    )
    assert not result.classification.quote_specific
    assert result.classification.candidate_count is None
    assert result.page_rotation_degrees == 0
    assert result.table_schedule is None
    assert result.timings.table_interpretation_seconds == 0
    assert not result.canonical_candidate_created


def test_one_part_with_specification_table_keeps_normal_geometry_path(monkeypatch):
    document = normalize_document(_image(), "unique-part.png")
    engine = StubOcr(
        "PADDLE ORIFICE PLATE DRAWING NO 12345 OUTSIDE DIAMETER "
        "BORE DIAMETER MATERIAL QUANTITY"
    )
    geometry_calls = []
    table_calls = []
    original_geometry = recognition.detect_raster_plate_structure
    original_table = recognition.parse_plate_schedule

    def geometry(rendered):
        geometry_calls.append(rendered.region.region_id)
        return original_geometry(rendered)

    def table(*args, **kwargs):
        table_calls.append(True)
        return original_table(*args, **kwargs)

    monkeypatch.setattr(recognition, "detect_raster_plate_structure", geometry)
    monkeypatch.setattr(recognition, "parse_plate_schedule", table)
    result = recognition.recognize_document_structure(document, ocr_engine=engine)

    assert geometry_calls
    assert table_calls
    assert (
        result.classification.document_class
        != DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET
    )


def test_private_reference_image_abstains_under_local_owner_limit(monkeypatch):
    source = Path(
        "drawing_corpus/private/phase1e_library/"
        "AVCO_Paddle_Universal_Orifice_Plate_Datasheet.jpg"
    )
    if not source.is_file():
        pytest.skip("Private reference image is not present in this environment")
    calls = []
    original = TesseractLocalOcrEngine.recognize

    def counted(self, *args, **kwargs):
        calls.append(True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(TesseractLocalOcrEngine, "recognize", counted)
    review = inspect_assisted_upload(
        source.read_bytes(), source.name, "image/jpeg"
    ).review

    assert len(calls) == 1
    assert review.document_class == DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET
    assert not review.quote_specific
    assert review.candidates == []
    assert review.manual_configuration_available
    # Broad smoke limit, not a production guarantee or timing benchmark.
    assert review.processing_seconds < 60
