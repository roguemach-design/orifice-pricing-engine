import io
import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError
from reportlab.lib.pagesizes import letter
from reportlab.lib.pagesizes import landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from drawing_intake.benchmark import run_benchmark
from drawing_intake.corpus import (
    CorpusClassification,
    CorpusEntry,
    CorpusManifest,
    GroundTruthCompletionStatus,
    load_manifest,
    run_real_corpus_safety_benchmark,
    summarize_manifest,
)
from drawing_intake.documents import (
    PageContentKind,
    PageOrientation,
    normalize_document,
    render_page_png,
)
from drawing_intake.models import (
    DocumentReference,
    DrawingExtractionResult,
    DrawingFields,
    FieldStatus,
    MeasurementUnit,
    NumericField,
    ProviderDataHandling,
)
from drawing_intake.pipeline import DrawingIntakePipeline
from drawing_intake.providers import (
    ExtractionProviderError,
    NativeTextExtractionProvider,
    StructuredModelExtractionProvider,
)
from drawing_intake.reconciliation import compare_extraction_to_configuration
from drawing_intake.validation import validate_extraction
from drawing_intake.verification import (
    CriticalFieldVerification,
    VerificationAgreement,
    VerificationResult,
    reconcile_independent_verification,
)

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "drawing_corpus" / "synthetic"
REAL_MANIFEST = ROOT / "drawing_corpus" / "real" / "manifest.json"


def extraction_from_fixture(filename: str):
    path = SYNTHETIC / filename
    document = normalize_document(path.read_bytes(), path.name)
    return document, NativeTextExtractionProvider().extract_drawing(document)


def minimal_extraction(fields: DrawingFields) -> DrawingExtractionResult:
    return DrawingExtractionResult(
        document=DocumentReference(
            filename="test.pdf",
            media_type="application/pdf",
            sha256="0" * 64,
            page_count=1,
        ),
        provider_name="test",
        provider_data_handling=ProviderDataHandling(
            external_service=False,
            retention="none",
            sends_document_content=False,
        ),
        fields=fields,
    )


def detected_number(
    value: float, unit: MeasurementUnit = MeasurementUnit.INCH
) -> NumericField:
    return NumericField(
        value=value,
        normalized_unit=unit,
        confidence=0.99,
        status=FieldStatus.DETECTED,
    )


def multi_part_pdf(*, rotation: int = 0) -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=landscape(letter))
    if rotation:
        pdf.setPageRotation(rotation)
    pdf.drawString(40, 550, "OUTSIDE DIAMETER: 8 IN")
    for center_x in (180, 500):
        for radius in (35, 25):
            pdf.circle(center_x, 300, radius, stroke=1, fill=0)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def test_schema_rejects_detected_field_without_value_and_extra_fields():
    with pytest.raises(ValidationError):
        NumericField(status=FieldStatus.DETECTED, value=None)
    with pytest.raises(ValidationError):
        DrawingFields(unexpected="nope")


def test_native_pdf_text_layer_and_source_coordinates_are_preserved():
    document, extraction = extraction_from_fixture("clean_digital.pdf")

    assert document.has_text_layer is True
    assert document.pages[0].content_kind == PageContentKind.NATIVE_TEXT
    evidence = extraction.fields.bore_diameter.evidence[0]
    assert evidence.page_number == 1
    assert evidence.raw_text == "BORE DIAMETER: 2.375 IN"
    assert evidence.bbox is not None
    assert render_page_png(document, 1, dpi=72).startswith(b"\x89PNG")
    assert "source_bytes" not in document.model_dump()


def test_image_only_pdf_is_detected_and_native_provider_abstains(tmp_path):
    png = tmp_path / "scan.png"
    Image.new("RGB", (200, 100), "white").save(png)
    pdf_buffer = io.BytesIO()
    pdf = canvas.Canvas(pdf_buffer, pagesize=letter)
    pdf.drawImage(ImageReader(str(png)), 72, 600, width=200, height=100)
    pdf.showPage()
    pdf.save()

    document = normalize_document(pdf_buffer.getvalue(), "scan.pdf")
    extraction = NativeTextExtractionProvider().extract_drawing(document)

    assert document.pages[0].content_kind == PageContentKind.IMAGE_ONLY
    assert extraction.fields.bore_diameter.status == FieldStatus.NOT_DETECTED
    assert extraction.document_warnings == [
        "No native text layer; OCR or vision provider required."
    ]


def test_rotated_pdf_with_partial_text_layer_preserves_rotation_and_abstains():
    document = normalize_document(multi_part_pdf(rotation=270), "rotated.pdf")
    extraction = NativeTextExtractionProvider().extract_drawing(document)

    assert document.pages[0].rotation_degrees == 270
    assert document.pages[0].orientation == PageOrientation.LANDSCAPE
    assert document.pages[0].content_kind == PageContentKind.NATIVE_TEXT
    assert extraction.fields.outside_diameter.status == FieldStatus.NOT_DETECTED


def test_multi_part_preflight_never_promotes_one_detected_value_to_candidate():
    result = DrawingIntakePipeline(NativeTextExtractionProvider()).process(
        multi_part_pdf(), "multi-part.pdf"
    )

    assert result.structure.status == "multiple_candidates"
    assert result.structure.candidate_region_count == 2
    assert (
        result.validation.extraction.fields.outside_diameter.status
        == FieldStatus.DETECTED
    )
    assert result.validation.canonical_candidate.paddle_dia is None
    assert result.validation.canonical_candidate.source_fields == {}
    assert "unsupported_multi_part_sheet" in {
        issue.code for issue in result.validation.issues
    }


def test_missing_and_ambiguous_fields_abstain_instead_of_guessing():
    _, missing = extraction_from_fixture("missing_field.pdf")
    _, ambiguous = extraction_from_fixture("ambiguous_conflict.pdf")

    assert missing.fields.thickness.status == FieldStatus.NOT_DETECTED
    assert missing.fields.thickness.value is None
    assert ambiguous.fields.bore_diameter.status == FieldStatus.AMBIGUOUS
    assert ambiguous.fields.bore_diameter.value is None
    assert len(ambiguous.fields.bore_diameter.evidence) == 2


def test_metric_dimensions_and_material_normalize_into_canonical_candidate():
    _, extraction = extraction_from_fixture("metric_normalization.pdf")
    validation = validate_extraction(extraction)
    candidate = validation.canonical_candidate

    assert candidate.paddle_dia == pytest.approx(8.0)
    assert candidate.bore_dia == pytest.approx(2.0)
    assert candidate.thickness == pytest.approx(0.25)
    assert candidate.bore_tolerance == pytest.approx(0.005)
    assert candidate.material == "316"


def test_structured_provider_rejects_malformed_or_incomplete_model_output():
    document, _ = extraction_from_fixture("clean_digital.pdf")
    handling = ProviderDataHandling(
        external_service=True,
        retention="provider_configured",
        sends_document_content=True,
    )
    provider = StructuredModelExtractionProvider(
        provider_name="mock-model",
        completion=lambda prompt, schema, doc: "I think the bore is 2.375 inches.",
        data_handling=handling,
    )
    with pytest.raises(ExtractionProviderError, match="strict schema validation"):
        provider.extract_drawing(document)

    provider = StructuredModelExtractionProvider(
        provider_name="mock-model",
        completion=lambda prompt, schema, doc: "{}",
        data_handling=handling,
    )
    with pytest.raises(ExtractionProviderError, match="strict schema validation"):
        provider.extract_drawing(document)

    provider = StructuredModelExtractionProvider(
        provider_name="mock-model",
        completion=lambda prompt, schema, doc: json.dumps(
            {"outside_diameter": {"status": "detected"}}
        ),
        data_handling=handling,
    )
    with pytest.raises(ExtractionProviderError, match="strict schema validation"):
        provider.extract_drawing(document)


def test_domain_validation_flags_unsupported_values_without_substitution():
    _, extraction = extraction_from_fixture("unsupported_value.pdf")
    result = validate_extraction(extraction)

    assert extraction.fields.outside_diameter.value == 60.0
    assert result.field_outcomes["outside_diameter"] == FieldStatus.UNSUPPORTED
    assert result.field_outcomes["material"] == FieldStatus.UNSUPPORTED
    assert result.canonical_candidate.paddle_dia is None
    assert result.canonical_candidate.material is None
    assert {issue.code for issue in result.issues} == {
        "outside_diameter_out_of_envelope",
        "unsupported_material",
    }


def test_domain_validation_rejects_bore_equal_to_or_greater_than_od():
    extraction = minimal_extraction(
        DrawingFields(
            outside_diameter=detected_number(3.0),
            bore_diameter=detected_number(3.0),
        )
    )
    result = validate_extraction(extraction)

    assert "bore_not_smaller_than_od" in {issue.code for issue in result.issues}
    assert result.field_outcomes["bore_diameter"] == FieldStatus.CONFLICT_DETECTED
    assert result.canonical_candidate.bore_dia is None


def test_asymmetric_tolerance_is_retained_but_not_mapped_to_symmetric_canonical_field():
    extraction = minimal_extraction(
        DrawingFields(
            bore_tolerance_plus=detected_number(0.002),
            bore_tolerance_minus=detected_number(0.0),
        )
    )
    result = validate_extraction(extraction)

    assert extraction.fields.bore_tolerance_plus.value == 0.002
    assert extraction.fields.bore_tolerance_minus.value == 0.0
    assert result.canonical_candidate.bore_tolerance is None
    assert "asymmetric_tolerance_not_canonical" in {
        issue.code for issue in result.issues
    }


def test_reconciliation_reports_match_mismatch_unknown_and_preserves_values():
    _, extraction = extraction_from_fixture("missing_field.pdf")
    validation = validate_extraction(extraction)
    customer = {
        "paddle_dia": 6.0,
        "bore_dia": 1.625,
        "material": "304",
        "chamfer": False,
    }
    before = dict(customer)
    result = compare_extraction_to_configuration(validation, customer)
    by_field = {item.extraction_field: item for item in result.comparisons}

    assert by_field["outside_diameter"].status == "match"
    assert by_field["bore_diameter"].status == "mismatch"
    assert by_field["bore_diameter"].customer_value == 1.625
    assert by_field["bore_diameter"].drawing_value == 1.5
    assert by_field["thickness"].status == "extraction_unknown"
    assert customer == before


def test_reconciliation_marks_out_of_envelope_drawing_value_unsupported():
    _, extraction = extraction_from_fixture("unsupported_value.pdf")
    validation = validate_extraction(extraction)
    result = compare_extraction_to_configuration(validation, {"paddle_dia": 48.0})
    comparison = next(
        item
        for item in result.comparisons
        if item.extraction_field == "outside_diameter"
    )

    assert comparison.status == "unsupported"
    assert comparison.customer_value == 48.0
    assert comparison.drawing_value == 60.0


def test_reconciliation_reports_metric_values_in_canonical_inches():
    _, extraction = extraction_from_fixture("metric_normalization.pdf")
    result = compare_extraction_to_configuration(
        validate_extraction(extraction), {"paddle_dia": 8.0}
    )
    comparison = next(
        item
        for item in result.comparisons
        if item.extraction_field == "outside_diameter"
    )

    assert comparison.status == "match"
    assert comparison.drawing_value == pytest.approx(8.0)
    assert comparison.drawing_unit == MeasurementUnit.INCH


def test_independent_verification_reconciliation_distinguishes_agreement_and_disagreement():
    _, extraction = extraction_from_fixture("clean_digital.pdf")
    verification = VerificationResult(
        provider_name="independent-test-verifier",
        fields=[
            CriticalFieldVerification(
                field_name="outside_diameter",
                independently_read=detected_number(8.0),
            ),
            CriticalFieldVerification(
                field_name="bore_diameter",
                independently_read=detected_number(2.5),
            ),
        ],
    )
    result = reconcile_independent_verification(extraction, verification)
    by_field = {item.field_name: item.status for item in result.comparisons}

    assert by_field["outside_diameter"] == VerificationAgreement.AGREE
    assert by_field["bore_diameter"] == VerificationAgreement.DISAGREE
    assert by_field["material"] == VerificationAgreement.UNCERTAIN


def test_synthetic_benchmark_harness_scores_all_five_test_categories():
    report = run_benchmark(
        SYNTHETIC,
        NativeTextExtractionProvider(),
        high_confidence_threshold=0.95,
    )

    assert len(report.documents) == 5
    assert all(document.synthetic for document in report.documents)
    assert report.aggregate["detection_correct"].rate == 1.0
    assert report.aggregate["correct_abstention"].correct == 2
    assert report.dangerous_high_confidence_errors == 0
    unsupported = next(
        document
        for document in report.documents
        if document.document_id == "synthetic-unsupported-value"
    )
    assert unsupported.actual_validation_codes == unsupported.expected_validation_codes


def test_tracked_real_manifest_groups_related_versions_as_one_source():
    manifest = load_manifest(REAL_MANIFEST)
    accounting = summarize_manifest(manifest)

    assert accounting.real_document_count == 2
    assert accounting.independent_source_group_count == 1
    assert accounting.derived_real_region_count == 0
    assert {entry.classification for entry in manifest.entries} == {
        CorpusClassification.REAL_DOCUMENT
    }


def test_derived_region_requires_provenance_and_is_not_an_independent_document():
    with pytest.raises(ValidationError, match="source_page and source_bbox"):
        CorpusEntry(
            corpus_id="derived-1",
            source_group_id="group-1",
            local_reference="crop.png",
            classification=CorpusClassification.DERIVED_REAL_REGION,
            page_count=1,
            multi_part=False,
            expected_production_behavior="benchmark_only",
            ground_truth_status=GroundTruthCompletionStatus.PER_REGION_PENDING,
            ground_truth_reference="derived.json",
        )


def test_real_document_safety_benchmark_keeps_derived_accounting_separate(tmp_path):
    private_root = tmp_path / "private"
    metadata_root = tmp_path / "real"
    private_root.mkdir()
    metadata_root.mkdir()
    source_bytes = multi_part_pdf()
    for filename in ("version-a.pdf", "version-b.pdf"):
        (private_root / filename).write_bytes(source_bytes)

    entries = []
    for suffix, filename in (("a", "version-a.pdf"), ("b", "version-b.pdf")):
        truth_name = f"version-{suffix}.json"
        (metadata_root / truth_name).write_text(
            json.dumps(
                {
                    "ground_truth_version": "1.0",
                    "corpus_id": f"real-{suffix}",
                    "drawing_number": "test-drawing",
                    "revision": suffix.upper(),
                    "page_count": 1,
                    "multi_part": True,
                    "visible_plate_region_count": 2,
                    "expected_document_status": "multiple_candidates",
                    "expected_production_behavior": "abstain_requires_part_selection",
                    "expected_abstention_reason": "unsupported_multi_part_sheet_requires_part_selection",
                }
            ),
            encoding="utf-8",
        )
        entries.append(
            CorpusEntry(
                corpus_id=f"real-{suffix}",
                source_group_id="test-drawing",
                local_reference=filename,
                classification=CorpusClassification.REAL_DOCUMENT,
                page_count=1,
                multi_part=True,
                revision=suffix.upper(),
                expected_production_behavior="abstain_requires_part_selection",
                ground_truth_status=GroundTruthCompletionStatus.DOCUMENT_LEVEL_COMPLETE,
                ground_truth_reference=truth_name,
            )
        )
    entries.extend(
        [
            CorpusEntry(
                corpus_id="derived-a-1",
                source_group_id="test-drawing",
                local_reference="crop.png",
                classification=CorpusClassification.DERIVED_REAL_REGION,
                page_count=1,
                multi_part=False,
                expected_production_behavior="benchmark_only",
                ground_truth_status=GroundTruthCompletionStatus.PER_REGION_PENDING,
                ground_truth_reference="derived.json",
                source_page=1,
                source_bbox=(0, 0, 100, 100),
            ),
            CorpusEntry(
                corpus_id="synthetic-1",
                source_group_id="synthetic-1",
                local_reference="synthetic.pdf",
                classification=CorpusClassification.SYNTHETIC_FIXTURE,
                page_count=1,
                multi_part=False,
                expected_production_behavior="software_test_only",
                ground_truth_status=GroundTruthCompletionStatus.COMPLETE,
                ground_truth_reference="synthetic.json",
            ),
        ]
    )
    manifest_path = metadata_root / "manifest.json"
    manifest_path.write_text(
        CorpusManifest(corpus_version="test", entries=entries).model_dump_json(),
        encoding="utf-8",
    )

    report = run_real_corpus_safety_benchmark(manifest_path, private_root)

    assert report.accounting.real_document_count == 2
    assert report.accounting.independent_source_group_count == 1
    assert report.accounting.derived_real_region_count == 1
    assert report.accounting.synthetic_fixture_count == 1
    assert report.document_level_safe_count == 2
    assert all(
        not result.canonical_candidate_populated
        for result in report.document_level_results
    )
    assert report.derived_region_view.entry_count == 1
    assert report.derived_region_view.independent_source_group_count == 0
    assert (
        report.derived_region_view.status
        == "not_run_requires_explicit_region_benchmark"
    )
