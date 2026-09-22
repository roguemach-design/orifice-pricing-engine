from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from pydantic import Field

from .documents import normalize_document
from .models import (
    CRITICAL_FIELDS,
    FieldStatus,
    MeasurementUnit,
    StrictModel,
)
from .providers import ExtractionProvider, NativeTextExtractionProvider
from .validation import validate_extraction
from .value_normalization import normalize_material, to_inches


class GroundTruthField(StrictModel):
    status: FieldStatus
    value: float | int | str | bool | None = None
    unit: MeasurementUnit | None = None


class GroundTruthRecord(StrictModel):
    corpus_version: str = "1.0"
    document_id: str
    synthetic: bool
    categories: list[str]
    source_document: str
    expected_fields: dict[str, GroundTruthField]
    expected_validation_codes: list[str] = Field(default_factory=list)


class FieldBenchmarkResult(StrictModel):
    field_name: str
    expected_status: FieldStatus
    actual_status: FieldStatus
    detection_correct: bool
    exact_numeric_match: bool | None = None
    normalized_numeric_match: bool | None = None
    material_match: bool | None = None
    unit_match: bool | None = None
    tolerance_match: bool | None = None
    chamfer_detection: bool | None = None
    metadata_match: bool | None = None
    correct_abstention: bool | None = None
    incorrect_confident_extraction: bool
    dangerous_high_confidence_error: bool


class DocumentBenchmarkResult(StrictModel):
    document_id: str
    synthetic: bool
    field_results: list[FieldBenchmarkResult]
    expected_validation_codes: list[str]
    actual_validation_codes: list[str]


class MetricAggregate(StrictModel):
    correct: int
    total: int
    rate: float | None


class BenchmarkReport(StrictModel):
    high_confidence_threshold: float
    documents: list[DocumentBenchmarkResult]
    aggregate: dict[str, MetricAggregate]
    dangerous_high_confidence_errors: int


DIMENSION_FIELDS = {
    "outside_diameter",
    "bore_diameter",
    "thickness",
    "bore_tolerance_plus",
    "bore_tolerance_minus",
    "general_dimensional_tolerance",
    "chamfer_width",
    "chamfer_depth",
}
METADATA_FIELDS = {"marking_text", "customer_part_number", "drawing_number", "revision"}


def _numeric_match(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    return (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
    )


def _normalized_value(
    field_name: str, value: Any, unit: MeasurementUnit | str | None
) -> Any:
    if field_name in DIMENSION_FIELDS and isinstance(value, (int, float)):
        return to_inches(float(value), unit)
    if field_name == "material" and isinstance(value, str):
        return normalize_material(value)
    return value


def _score_field(
    field_name: str,
    expected: GroundTruthField,
    actual,
    high_confidence_threshold: float,
) -> FieldBenchmarkResult:
    expected_detected = expected.status == FieldStatus.DETECTED
    actual_detected = actual.status == FieldStatus.DETECTED
    detection_correct = actual.status == expected.status
    exact_numeric_match = None
    normalized_numeric_match = None
    if (
        expected_detected
        and isinstance(expected.value, (int, float))
        and not isinstance(expected.value, bool)
    ):
        exact_numeric_match = (
            _numeric_match(actual.value, expected.value)
            and actual.normalized_unit == expected.unit
        )
        normalized_numeric_match = _numeric_match(
            _normalized_value(field_name, actual.value, actual.normalized_unit),
            _normalized_value(field_name, expected.value, expected.unit),
        )

    expected_normalized = _normalized_value(field_name, expected.value, expected.unit)
    actual_normalized = _normalized_value(
        field_name, actual.value, actual.normalized_unit
    )
    value_correct = (
        _numeric_match(actual_normalized, expected_normalized)
        if isinstance(expected_normalized, (int, float))
        and not isinstance(expected_normalized, bool)
        else actual_normalized == expected_normalized
    )
    wrong_confident = bool(
        actual_detected
        and (actual.confidence or 0.0) >= high_confidence_threshold
        and (not expected_detected or not value_correct)
    )
    return FieldBenchmarkResult(
        field_name=field_name,
        expected_status=expected.status,
        actual_status=actual.status,
        detection_correct=detection_correct,
        exact_numeric_match=exact_numeric_match,
        normalized_numeric_match=normalized_numeric_match,
        material_match=(
            value_correct if field_name == "material" and expected_detected else None
        ),
        unit_match=(
            (actual.normalized_unit == expected.unit)
            if expected_detected and expected.unit
            else None
        ),
        tolerance_match=(
            value_correct
            if field_name in {"bore_tolerance_plus", "bore_tolerance_minus"}
            and expected_detected
            else None
        ),
        chamfer_detection=(
            value_correct
            if field_name == "chamfer_present" and expected_detected
            else None
        ),
        metadata_match=(
            value_correct
            if field_name in METADATA_FIELDS and expected_detected
            else None
        ),
        correct_abstention=detection_correct if not expected_detected else None,
        incorrect_confident_extraction=wrong_confident,
        dangerous_high_confidence_error=wrong_confident
        and field_name in CRITICAL_FIELDS,
    )


def _aggregate(documents: list[DocumentBenchmarkResult]) -> dict[str, MetricAggregate]:
    metric_names = (
        "detection_correct",
        "exact_numeric_match",
        "normalized_numeric_match",
        "material_match",
        "unit_match",
        "tolerance_match",
        "chamfer_detection",
        "metadata_match",
        "correct_abstention",
    )
    output = {}
    all_fields = [field for document in documents for field in document.field_results]
    for name in metric_names:
        values = [
            getattr(field, name)
            for field in all_fields
            if getattr(field, name) is not None
        ]
        correct = sum(bool(value) for value in values)
        total = len(values)
        output[name] = MetricAggregate(
            correct=correct,
            total=total,
            rate=(correct / total) if total else None,
        )
    return output


def run_benchmark(
    corpus_directory: str | Path,
    provider: ExtractionProvider,
    *,
    high_confidence_threshold: float,
) -> BenchmarkReport:
    if not 0.0 <= high_confidence_threshold <= 1.0:
        raise ValueError("high_confidence_threshold must be between 0 and 1")
    root = Path(corpus_directory)
    results = []
    for truth_path in sorted(root.rglob("*.ground_truth.json")):
        record = GroundTruthRecord.model_validate_json(
            truth_path.read_text(encoding="utf-8")
        )
        source_path = truth_path.parent / record.source_document
        document = normalize_document(source_path.read_bytes(), source_path.name)
        extraction = provider.extract_drawing(document)
        validation = validate_extraction(extraction)
        field_results = [
            _score_field(
                field_name,
                expected,
                getattr(extraction.fields, field_name),
                high_confidence_threshold,
            )
            for field_name, expected in record.expected_fields.items()
        ]
        results.append(
            DocumentBenchmarkResult(
                document_id=record.document_id,
                synthetic=record.synthetic,
                field_results=field_results,
                expected_validation_codes=sorted(record.expected_validation_codes),
                actual_validation_codes=sorted(
                    issue.code for issue in validation.issues
                ),
            )
        )
    dhce = sum(
        field.dangerous_high_confidence_error
        for document in results
        for field in document.field_results
    )
    return BenchmarkReport(
        high_confidence_threshold=high_confidence_threshold,
        documents=results,
        aggregate=_aggregate(results),
        dangerous_high_confidence_errors=dhce,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark O-Plates drawing extraction fixtures."
    )
    parser.add_argument("corpus_directory", type=Path)
    parser.add_argument(
        "--high-confidence-threshold",
        type=float,
        required=True,
        help="Configurable DHCE threshold; no production threshold is implied.",
    )
    args = parser.parse_args()
    report = run_benchmark(
        args.corpus_directory,
        NativeTextExtractionProvider(),
        high_confidence_threshold=args.high_confidence_threshold,
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
