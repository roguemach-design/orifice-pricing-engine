from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .deterministic import EvidenceClassification, interpret_precomputed_region
from .documents import normalize_document
from .engineering_text import (
    parse_material,
    parse_measurement,
    parse_quantity,
    parse_tolerance,
)
from .models import FieldStatus, MeasurementUnit, StrictModel
from .ocr import TesseractLocalOcrEngine
from .pipeline import DrawingIntakePipeline
from .providers import NativeTextExtractionProvider
from .regions import derive_candidate_regions
from .rendering import render_region_png
from .spatial import build_spatial_lines
from .structure import assess_document_structure
from .value_normalization import to_inches


class RegionTruth(StrictModel):
    region_id: str
    fields: dict[str, float | int | str | bool]


class DocumentRegionTruth(StrictModel):
    source_filename: str
    regions: list[RegionTruth]


class PrivateRegionGroundTruth(StrictModel):
    ground_truth_version: str
    source_group_id: str
    classification: Literal["derived_real_region"]
    documents: list[DocumentRegionTruth]


class StageFieldResult(StrictModel):
    field_name: str
    native_status: FieldStatus
    ocr_observed_expected_value: bool
    deterministic_status: FieldStatus
    deterministic_evidence: EvidenceClassification
    deterministic_value_correct: bool


class RegionStageResult(StrictModel):
    source_filename: str
    source_group_id: str
    region_id: str
    fields: list[StageFieldResult]
    correct_field_count: int = Field(ge=0)
    total_field_count: int = Field(ge=0)
    render_seconds: float = Field(ge=0)
    ocr_seconds: float = Field(ge=0)
    interpretation_seconds: float = Field(ge=0)


class FieldStageAggregate(StrictModel):
    total: int = Field(ge=0)
    native_detected: int = Field(ge=0)
    ocr_observed: int = Field(ge=0)
    deterministic_correct: int = Field(ge=0)
    deterministic_incorrect: int = Field(ge=0)
    deterministic_ambiguous: int = Field(ge=0)
    deterministic_not_detected: int = Field(ge=0)


class DpiExperimentResult(StrictModel):
    dpi: int
    width: int
    height: int
    png_size_bytes: int
    uncompressed_bytes: int
    render_seconds: float
    ocr_seconds: float
    token_count: int
    correct_critical_fields: int
    total_critical_fields: int


class PerformanceAggregate(StrictModel):
    normalization_seconds: float = Field(ge=0)
    structure_seconds: float = Field(ge=0)
    rendering_seconds: float = Field(ge=0)
    ocr_seconds: float = Field(ge=0)
    interpretation_seconds: float = Field(ge=0)
    total_region_seconds: float = Field(ge=0)
    mean_region_seconds: float = Field(ge=0)


class DeterministicBenchmarkReport(StrictModel):
    source_group_count: int
    document_count: int
    derived_region_count: int
    whole_document_safe_count: int
    regions: list[RegionStageResult]
    field_aggregate: dict[str, FieldStageAggregate]
    dpi_experiment: list[DpiExperimentResult]
    performance: PerformanceAggregate


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and math.isclose(
            float(actual), float(expected), rel_tol=0.0, abs_tol=1e-6
        )
    return actual == expected


def _ocr_observed_expected(field_name, expected, ocr_result) -> bool:
    lines = build_spatial_lines(ocr_result.tokens)
    if field_name in {"outside_diameter", "bore_diameter", "thickness"}:
        for token in ocr_result.tokens:
            parsed = parse_measurement(
                token.raw_text,
                thickness_context=field_name == "thickness",
            )
            if parsed and _equal(to_inches(parsed.value, parsed.unit), expected):
                return True
        return False
    if field_name == "material":
        return any(_equal(parse_material(line.raw_text), expected) for line in lines)
    if field_name == "quantity":
        return any(_equal(parse_quantity(line.raw_text), expected) for line in lines)
    if field_name == "global_units":
        for token in ocr_result.tokens:
            parsed = parse_measurement(token.raw_text)
            if parsed and parsed.explicit_unit and parsed.unit == expected:
                return True
        return False
    if field_name in {"bore_tolerance_plus", "bore_tolerance_minus"}:
        side = "plus" if field_name.endswith("plus") else "minus"
        for line in lines:
            parsed = parse_tolerance(line.raw_text, default_unit=MeasurementUnit.INCH)
            if parsed and _equal(getattr(parsed, side), expected):
                return True
        return False
    return False


def _candidate_populated(candidate) -> bool:
    return any(
        value is not None
        for key, value in candidate.model_dump().items()
        if key not in {"source_fields", "missing_required_fields"}
    )


def _aggregate(regions: list[RegionStageResult]) -> dict[str, FieldStageAggregate]:
    names = sorted({field.field_name for region in regions for field in region.fields})
    output = {}
    for name in names:
        fields = [
            field
            for region in regions
            for field in region.fields
            if field.field_name == name
        ]
        output[name] = FieldStageAggregate(
            total=len(fields),
            native_detected=sum(
                field.native_status == FieldStatus.DETECTED for field in fields
            ),
            ocr_observed=sum(field.ocr_observed_expected_value for field in fields),
            deterministic_correct=sum(
                field.deterministic_value_correct for field in fields
            ),
            deterministic_incorrect=sum(
                field.deterministic_status
                in {FieldStatus.DETECTED, FieldStatus.LOW_CONFIDENCE}
                and not field.deterministic_value_correct
                for field in fields
            ),
            deterministic_ambiguous=sum(
                field.deterministic_status == FieldStatus.AMBIGUOUS for field in fields
            ),
            deterministic_not_detected=sum(
                field.deterministic_status == FieldStatus.NOT_DETECTED
                for field in fields
            ),
        )
    return output


def run_deterministic_benchmark(
    private_root: str | Path,
    ground_truth_path: str | Path,
) -> DeterministicBenchmarkReport:
    private_root = Path(private_root)
    truth = PrivateRegionGroundTruth.model_validate_json(
        Path(ground_truth_path).read_text(encoding="utf-8")
    )
    ocr_engine = TesseractLocalOcrEngine()
    pipeline = DrawingIntakePipeline(NativeTextExtractionProvider())
    region_results = []
    normalization_seconds = 0.0
    structure_seconds = 0.0
    whole_document_safe = 0
    first_experiment = None

    for document_truth in truth.documents:
        source_path = private_root / document_truth.source_filename
        started = time.perf_counter()
        document = normalize_document(source_path.read_bytes(), source_path.name)
        normalization_seconds += time.perf_counter() - started
        started = time.perf_counter()
        structure = assess_document_structure(document)
        regions = derive_candidate_regions(
            document,
            structure,
            source_group_id=truth.source_group_id,
        )
        structure_seconds += time.perf_counter() - started
        whole = pipeline.process(source_path.read_bytes(), source_path.name)
        if (
            whole.structure.status == "multiple_candidates"
            and not _candidate_populated(whole.validation.canonical_candidate)
            and "unsupported_multi_part_sheet"
            in {issue.code for issue in whole.validation.issues}
        ):
            whole_document_safe += 1

        by_id = {region.region_id: region for region in regions}
        native = NativeTextExtractionProvider().extract_drawing(document)
        for region_truth in document_truth.regions:
            region = by_id[region_truth.region_id]
            rendered = render_region_png(document, region, dpi=300)
            ocr = ocr_engine.recognize(rendered)
            started = time.perf_counter()
            recognized_fields, _ = interpret_precomputed_region(document, region, ocr)
            interpretation_seconds = time.perf_counter() - started
            fields = []
            for field_name, expected in region_truth.fields.items():
                actual = recognized_fields[field_name]
                fields.append(
                    StageFieldResult(
                        field_name=field_name,
                        native_status=getattr(native.fields, field_name).status,
                        ocr_observed_expected_value=_ocr_observed_expected(
                            field_name, expected, ocr
                        ),
                        deterministic_status=actual.status,
                        deterministic_evidence=actual.evidence_classification,
                        deterministic_value_correct=_equal(actual.value, expected),
                    )
                )
            region_results.append(
                RegionStageResult(
                    source_filename=document_truth.source_filename,
                    source_group_id=truth.source_group_id,
                    region_id=region.region_id,
                    fields=fields,
                    correct_field_count=sum(
                        field.deterministic_value_correct for field in fields
                    ),
                    total_field_count=len(fields),
                    render_seconds=rendered.render_seconds,
                    ocr_seconds=ocr.ocr_seconds,
                    interpretation_seconds=interpretation_seconds,
                )
            )
            if first_experiment is None:
                first_experiment = (document, region, region_truth)

    dpi_results = []
    if first_experiment is not None:
        document, region, region_truth = first_experiment
        critical = {
            key: value
            for key, value in region_truth.fields.items()
            if key
            in {
                "outside_diameter",
                "bore_diameter",
                "thickness",
                "material",
                "global_units",
                "bore_tolerance_plus",
                "bore_tolerance_minus",
            }
        }
        for dpi in (300, 400, 600):
            rendered = render_region_png(document, region, dpi=dpi)
            ocr = ocr_engine.recognize(rendered)
            trial_fields, _ = interpret_precomputed_region(document, region, ocr)
            dpi_results.append(
                DpiExperimentResult(
                    dpi=dpi,
                    width=rendered.width,
                    height=rendered.height,
                    png_size_bytes=rendered.png_size_bytes,
                    uncompressed_bytes=rendered.uncompressed_grayscale_bytes,
                    render_seconds=rendered.render_seconds,
                    ocr_seconds=ocr.ocr_seconds,
                    token_count=len(ocr.tokens),
                    correct_critical_fields=sum(
                        _equal(trial_fields[name].value, expected)
                        for name, expected in critical.items()
                    ),
                    total_critical_fields=len(critical),
                )
            )

    rendering_total = sum(region.render_seconds for region in region_results)
    ocr_total = sum(region.ocr_seconds for region in region_results)
    interpretation_total = sum(
        region.interpretation_seconds for region in region_results
    )
    region_total = rendering_total + ocr_total + interpretation_total
    return DeterministicBenchmarkReport(
        source_group_count=1,
        document_count=len(truth.documents),
        derived_region_count=len(region_results),
        whole_document_safe_count=whole_document_safe,
        regions=region_results,
        field_aggregate=_aggregate(region_results),
        dpi_experiment=dpi_results,
        performance=PerformanceAggregate(
            normalization_seconds=normalization_seconds,
            structure_seconds=structure_seconds,
            rendering_seconds=rendering_total,
            ocr_seconds=ocr_total,
            interpretation_seconds=interpretation_total,
            total_region_seconds=region_total,
            mean_region_seconds=(
                (region_total / len(region_results)) if region_results else 0.0
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark local deterministic recognition on private derived regions."
    )
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    args = parser.parse_args()
    report = run_deterministic_benchmark(args.private_root, args.ground_truth)
    print(json.dumps(report.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
