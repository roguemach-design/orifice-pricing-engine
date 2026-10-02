from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .document_recognition import recognize_document_structure
from .documents import normalize_document
from .models import (
    DocumentReference,
    DrawingExtractionResult,
    DrawingFields,
    FieldStatus,
    IntegerField,
    MeasurementUnit,
    NumericField,
    ProviderDataHandling,
    StrictModel,
    StringField,
    UnitField,
)
from .table_schedule import TableFieldObservation
from .validation import validate_extraction

VerificationStatus = Literal["verified", "provisional", "missing", "unresolved"]


class ScheduleAdjudication(StrictModel):
    status: Literal["independently_verified", "provisional"]
    method: str
    recognizer_output_used_as_truth: bool
    human_verification_required: list[str] = Field(default_factory=list)


class ScheduleDocumentTruthField(StrictModel):
    value: float | int | str | bool | None = None
    raw_text: str | None = None
    page_number: int = Field(ge=1)
    bbox: tuple[float, float, float, float]
    coordinate_unit: str
    verification_status: VerificationStatus
    note: str | None = None


class ScheduleTruthRow(StrictModel):
    row_index: int = Field(ge=1)
    fields: dict[str, float | int | str | bool | None]
    raw_text: dict[str, str] = Field(default_factory=dict)
    source_bboxes: dict[str, tuple[float, float, float, float]]
    verification_status_by_field: dict[str, VerificationStatus] = Field(
        default_factory=dict
    )


class PrivateScheduleGroundTruth(StrictModel):
    ground_truth_version: str
    source_group_id: str
    source_filename: str
    source_sha256: str
    classification: Literal["real_document"]
    expected_document_class: Literal["table_driven_plate_schedule"]
    page_number: int = Field(ge=1)
    row_count: int = Field(ge=0)
    distinct_configuration_count: int = Field(ge=0)
    adjudication: ScheduleAdjudication
    document_fields: dict[str, ScheduleDocumentTruthField]
    rows: list[ScheduleTruthRow]


class ScheduleFieldScore(StrictModel):
    row_index: int = Field(ge=1)
    field_name: str
    verification_status: VerificationStatus
    expected_value: float | int | str | bool | None = None
    observed_value: float | int | str | bool | None = None
    observed_status: FieldStatus
    correct: bool
    incorrect_confident: bool = False
    incorrect_confirmation_only: bool = False
    source_page: int = Field(ge=1)
    source_bbox: tuple[float, float, float, float]


class ScheduleFieldAggregate(StrictModel):
    verified_total: int = Field(ge=0)
    verified_correct: int = Field(ge=0)
    verified_incorrect: int = Field(ge=0)
    verified_ambiguous_or_missing: int = Field(ge=0)
    provisional_total: int = Field(ge=0)
    provisional_correct: int = Field(ge=0)


class ScheduleRowSupport(StrictModel):
    row_index: int = Field(ge=1)
    unsupported_fields: list[str] = Field(default_factory=list)
    supported_by_current_catalog: bool


class ScheduleBenchmarkReport(StrictModel):
    source_group_id: str
    source_sha256_matches: bool
    classification_correct: bool
    expected_rows: int = Field(ge=0)
    detected_rows: int = Field(ge=0)
    row_detection_correct: bool
    distinct_ground_truth_configurations: int = Field(ge=0)
    required_columns_detected: dict[str, bool]
    field_scores: list[ScheduleFieldScore]
    field_aggregate: dict[str, ScheduleFieldAggregate]
    row_support: list[ScheduleRowSupport]
    incorrect_confident_count: int = Field(ge=0)
    incorrect_confirmation_only_count: int = Field(ge=0)
    wrong_critical_authoritative_count: int = Field(ge=0)
    verified_ground_truth_field_count: int = Field(ge=0)
    provisional_ground_truth_field_count: int = Field(ge=0)
    unresolved_ground_truth_items: list[str] = Field(default_factory=list)
    explicit_row_selection_required: bool
    canonical_candidate_created: bool
    pricing_invoked: bool = False
    normalization_seconds: float = Field(ge=0)
    classification_seconds: float = Field(ge=0)
    rendering_and_ocr_seconds: float = Field(ge=0)
    table_interpretation_seconds: float = Field(ge=0)
    targeted_table_ocr_seconds: float = Field(ge=0)
    total_recognition_seconds: float = Field(ge=0)


_CRITICAL_SCHEDULE_FIELDS = {
    "outside_diameter",
    "bore_diameter",
    "thickness",
    "material",
    "global_units",
    "bore_tolerance_plus",
    "bore_tolerance_minus",
}


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and math.isclose(
            float(actual), float(expected), rel_tol=0.0, abs_tol=1e-6
        )
    return actual == expected


def _status(observation: TableFieldObservation | None) -> FieldStatus:
    return (
        FieldStatus.NOT_DETECTED
        if observation is None
        else FieldStatus(observation.status)
    )


def _row_support(
    truth: PrivateScheduleGroundTruth, row: ScheduleTruthRow
) -> ScheduleRowSupport:
    material = truth.document_fields["material"]
    units = MeasurementUnit(truth.document_fields["global_units"].value)

    def numeric(name: str) -> NumericField:
        return NumericField(
            value=float(row.fields[name]),
            normalized_unit=units,
            status=FieldStatus.DETECTED,
        )

    extraction = DrawingExtractionResult(
        document=DocumentReference(
            filename=truth.source_filename,
            media_type="application/pdf",
            sha256=truth.source_sha256,
            page_count=1,
        ),
        provider_name="phase1e_verified_ground_truth_support_audit",
        provider_data_handling=ProviderDataHandling(
            external_service=False,
            retention="private_ground_truth_only",
            sends_document_content=False,
        ),
        fields=DrawingFields(
            outside_diameter=numeric("outside_diameter"),
            bore_diameter=numeric("bore_diameter"),
            thickness=numeric("thickness"),
            material=StringField(
                value=str(material.value), status=FieldStatus.DETECTED
            ),
            quantity=IntegerField(
                value=int(row.fields["quantity"]),
                normalized_unit=MeasurementUnit.COUNT,
                status=FieldStatus.DETECTED,
            ),
            global_units=UnitField(
                value=units.value,
                normalized_unit=units,
                status=FieldStatus.DETECTED,
            ),
            bore_tolerance_plus=numeric("bore_tolerance_plus"),
            bore_tolerance_minus=numeric("bore_tolerance_minus"),
        ),
    )
    validation = validate_extraction(extraction)
    unsupported = sorted(validation.field_outcomes)
    return ScheduleRowSupport(
        row_index=row.row_index,
        unsupported_fields=unsupported,
        supported_by_current_catalog=not unsupported,
    )


def _aggregate(scores: list[ScheduleFieldScore]) -> dict[str, ScheduleFieldAggregate]:
    output: dict[str, ScheduleFieldAggregate] = {}
    for name in sorted({score.field_name for score in scores}):
        fields = [score for score in scores if score.field_name == name]
        verified = [
            score for score in fields if score.verification_status == "verified"
        ]
        provisional = [
            score for score in fields if score.verification_status == "provisional"
        ]
        output[name] = ScheduleFieldAggregate(
            verified_total=len(verified),
            verified_correct=sum(score.correct for score in verified),
            verified_incorrect=sum(
                score.observed_value is not None and not score.correct
                for score in verified
            ),
            verified_ambiguous_or_missing=sum(
                score.observed_value is None and not score.correct for score in verified
            ),
            provisional_total=len(provisional),
            provisional_correct=sum(score.correct for score in provisional),
        )
    return output


def run_schedule_benchmark(
    source_path: str | Path,
    ground_truth_path: str | Path,
) -> ScheduleBenchmarkReport:
    source_path = Path(source_path)
    truth = PrivateScheduleGroundTruth.model_validate_json(
        Path(ground_truth_path).read_text(encoding="utf-8")
    )
    normalization_started = time.perf_counter()
    document = normalize_document(source_path.read_bytes(), source_path.name)
    normalization_seconds = time.perf_counter() - normalization_started
    recognized = recognize_document_structure(document)
    schedule = recognized.table_schedule
    candidates = schedule.candidates if schedule is not None else []
    by_row = {candidate.row_index: candidate for candidate in candidates}
    scores: list[ScheduleFieldScore] = []

    for truth_row in truth.rows:
        candidate = by_row.get(truth_row.row_index)
        expected_fields = dict(truth_row.fields)
        for name in ("material", "global_units"):
            expected_fields[name] = truth.document_fields[name].value
        for name, expected in expected_fields.items():
            observation = getattr(candidate, name, None) if candidate else None
            observed = observation.value if observation is not None else None
            verification_status = truth_row.verification_status_by_field.get(
                name,
                (
                    truth.document_fields[name].verification_status
                    if name in truth.document_fields
                    else "verified"
                ),
            )
            status = _status(observation)
            correct = _equal(observed, expected)
            bbox = (
                truth.document_fields[name].bbox
                if name in truth.document_fields
                else truth_row.source_bboxes[name]
            )
            scores.append(
                ScheduleFieldScore(
                    row_index=truth_row.row_index,
                    field_name=name,
                    verification_status=verification_status,
                    expected_value=expected,
                    observed_value=observed,
                    observed_status=status,
                    correct=correct,
                    incorrect_confident=(
                        observed is not None
                        and not correct
                        and status == FieldStatus.DETECTED
                    ),
                    incorrect_confirmation_only=(
                        observed is not None
                        and not correct
                        and status == FieldStatus.LOW_CONFIDENCE
                    ),
                    source_page=truth.page_number,
                    source_bbox=bbox,
                )
            )

    required = (
        "tag",
        "quantity",
        "outside_diameter",
        "thickness",
        "bore_diameter",
        "bore_tolerance_plus",
        "bore_tolerance_minus",
        "material",
        "global_units",
    )
    missing_column_reason = {
        "bore_tolerance_plus": "no_tolerance_column",
        "bore_tolerance_minus": "no_tolerance_column",
    }
    columns = {}
    for name in required:
        observations = [getattr(candidate, name) for candidate in candidates]
        if name in {"material", "global_units"}:
            columns[name] = any(item.value is not None for item in observations)
        else:
            no_column = missing_column_reason.get(name, f"no_{name}_column")
            columns[name] = any(item.reason != no_column for item in observations)
    wrong_authoritative = sum(
        score.field_name in _CRITICAL_SCHEDULE_FIELDS and score.incorrect_confident
        for score in scores
    )
    return ScheduleBenchmarkReport(
        source_group_id=truth.source_group_id,
        source_sha256_matches=document.sha256 == truth.source_sha256,
        classification_correct=(
            recognized.classification.document_class == truth.expected_document_class
        ),
        expected_rows=truth.row_count,
        detected_rows=len(candidates),
        row_detection_correct=len(candidates) == truth.row_count,
        distinct_ground_truth_configurations=truth.distinct_configuration_count,
        required_columns_detected=columns,
        field_scores=scores,
        field_aggregate=_aggregate(scores),
        row_support=[_row_support(truth, row) for row in truth.rows],
        incorrect_confident_count=sum(score.incorrect_confident for score in scores),
        incorrect_confirmation_only_count=sum(
            score.incorrect_confirmation_only for score in scores
        ),
        wrong_critical_authoritative_count=wrong_authoritative,
        verified_ground_truth_field_count=sum(
            score.verification_status == "verified" for score in scores
        ),
        provisional_ground_truth_field_count=sum(
            score.verification_status == "provisional" for score in scores
        ),
        unresolved_ground_truth_items=truth.adjudication.human_verification_required,
        explicit_row_selection_required=(
            recognized.classification.candidate_count != 1
        ),
        canonical_candidate_created=recognized.canonical_candidate_created
        or bool(schedule and schedule.quote_candidate_created),
        pricing_invoked=False,
        normalization_seconds=normalization_seconds,
        classification_seconds=recognized.timings.classification_seconds,
        rendering_and_ocr_seconds=recognized.timings.rendering_and_ocr_seconds,
        table_interpretation_seconds=recognized.timings.table_interpretation_seconds,
        targeted_table_ocr_seconds=(
            schedule.targeted_ocr_seconds if schedule is not None else 0.0
        ),
        total_recognition_seconds=recognized.timings.total_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark a private, adjudicated ruled plate schedule."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    args = parser.parse_args()
    report = run_schedule_benchmark(args.source, args.ground_truth)
    print(json.dumps(report.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
