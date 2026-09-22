from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from enum import Enum

from pydantic import Field

from .documents import NormalizedDocument
from .engineering_text import (
    ParsedMeasurement,
    ParsedTolerance,
    ToleranceKind,
    normalize_engineering_text,
    parse_chamfer_notation,
    parse_material,
    parse_measurement,
    parse_quantity,
    parse_tolerance,
)
from .geometry import RegionGeometryEvidence, analyze_region_geometry
from .models import (
    BooleanField,
    DocumentReference,
    DomainValidationResult,
    DrawingExtractionResult,
    DrawingFields,
    FieldStatus,
    IntegerField,
    MeasurementUnit,
    NumericField,
    ProviderDataHandling,
    SourceEvidence,
    StrictModel,
    StringField,
    UnitField,
)
from .ocr import (
    LocalOcrResult,
    OcrTokenObservation,
    TesseractLocalOcrEngine,
    recover_plus_minus_glyphs,
)
from .regions import DerivedDrawingRegion
from .rendering import render_region_png
from .spatial import SpatialTextLine, bbox_distance, build_spatial_lines
from .validation import validate_extraction
from .value_normalization import to_inches


class EvidenceClassification(str, Enum):
    VERIFIED = "verified"
    STRONG = "strong"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    AMBIGUOUS = "ambiguous"
    NOT_DETECTED = "not_detected"
    UNSUPPORTED = "unsupported"


class RecognitionEvidence(StrictModel):
    rule_id: str
    description: str
    source: SourceEvidence | None = None
    token_ids: list[str] = Field(default_factory=list)


class FieldRecognitionResult(StrictModel):
    field_name: str
    value: float | int | str | bool | None = None
    normalized_unit: MeasurementUnit | None = None
    raw_text: str | None = None
    status: FieldStatus
    evidence_classification: EvidenceClassification
    evidence: list[RecognitionEvidence] = Field(default_factory=list)
    candidate_values: list[float | int | str | bool] = Field(default_factory=list)
    abstention_reason: str | None = None
    normalization_rules: list[str] = Field(default_factory=list)


class RecognitionTimings(StrictModel):
    rendering_seconds: float = Field(ge=0)
    ocr_seconds: float = Field(ge=0)
    targeted_ocr_seconds: float = Field(default=0, ge=0)
    interpretation_seconds: float = Field(ge=0)
    total_seconds: float = Field(ge=0)


class DeterministicRecognitionResult(StrictModel):
    region: DerivedDrawingRegion
    rendered_width: int
    rendered_height: int
    rendered_png_size_bytes: int
    rendered_uncompressed_bytes: int
    ocr_token_count: int
    geometry: RegionGeometryEvidence
    field_results: dict[str, FieldRecognitionResult]
    extraction: DrawingExtractionResult
    validation: DomainValidationResult
    timings: RecognitionTimings


@dataclass(frozen=True)
class _NumericCandidate:
    value: float
    unit: MeasurementUnit | None
    raw_text: str
    source: SourceEvidence
    token_ids: tuple[str, ...]
    engine_pass: str
    normalization_rules: tuple[str, ...]


def _normalized_label(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_engineering_text(raw).normalized_text)


def _source_for_tokens(
    tokens: list[OcrTokenObservation], raw_text: str
) -> SourceEvidence:
    return SourceEvidence(
        page_number=tokens[0].page_number,
        raw_text=raw_text,
        bbox=(
            min(token.source_bbox[0] for token in tokens),
            min(token.source_bbox[1] for token in tokens),
            max(token.source_bbox[2] for token in tokens),
            max(token.source_bbox[3] for token in tokens),
        ),
        coordinate_unit=tokens[0].source_coordinate_unit,
        extraction_method="tesseract_local+deterministic_rules_v1",
    )


def _nearby_tokens(
    anchor: OcrTokenObservation,
    tokens: list[OcrTokenObservation],
    *,
    maximum_distance: float = 36.0,
) -> list[OcrTokenObservation]:
    anchor_center_y = (anchor.source_bbox[1] + anchor.source_bbox[3]) / 2.0
    anchor_height = anchor.source_bbox[3] - anchor.source_bbox[1]
    output = []
    for token in tokens:
        if (
            token.region_id != anchor.region_id
            or token.page_number != anchor.page_number
            or token.engine_pass != anchor.engine_pass
            or token.token_id == anchor.token_id
        ):
            continue
        token_center_y = (token.source_bbox[1] + token.source_bbox[3]) / 2.0
        token_height = token.source_bbox[3] - token.source_bbox[1]
        if abs(token_center_y - anchor_center_y) > max(
            14.0, anchor_height + token_height
        ):
            continue
        if bbox_distance(anchor.source_bbox, token.source_bbox) <= maximum_distance:
            output.append(token)
    return output


def _adjacent_numeric_candidates(
    tokens: list[OcrTokenObservation],
    *,
    labels: set[str],
    thickness_context: bool = False,
    require_explicit_unit: bool = False,
    excluded_neighbor_labels: set[str] | None = None,
) -> list[_NumericCandidate]:
    candidates: list[_NumericCandidate] = []
    for label in tokens:
        if _normalized_label(label.interpreted_text) not in labels:
            continue
        nearby = _nearby_tokens(label, tokens)
        sign_tokens = [
            token
            for token in nearby
            if token.interpreted_text.strip() in {"+", "-", "±", "£", "+/-", "+-"}
        ]
        excluded_tokens = [
            token
            for token in nearby
            if _normalized_label(token.interpreted_text)
            in (excluded_neighbor_labels or set())
        ]
        parsed: list[tuple[OcrTokenObservation, ParsedMeasurement]] = []
        for token in nearby:
            measurement = parse_measurement(
                token.interpreted_text,
                thickness_context=thickness_context,
            )
            if measurement is None or measurement.value <= 0:
                continue
            if require_explicit_unit and not measurement.explicit_unit:
                adjacent_units = [
                    unit_token
                    for unit_token in nearby
                    if _normalized_label(unit_token.interpreted_text)
                    in {"IN", "INCH", "MM"}
                    and bbox_distance(token.source_bbox, unit_token.source_bbox) <= 16.0
                ]
                if not adjacent_units:
                    continue
                unit_label = _normalized_label(adjacent_units[0].interpreted_text)
                measurement = measurement.model_copy(
                    update={
                        "unit": (
                            MeasurementUnit.MILLIMETER
                            if unit_label == "MM"
                            else MeasurementUnit.INCH
                        ),
                        "explicit_unit": True,
                    }
                )
            if any(
                bbox_distance(token.source_bbox, sign.source_bbox) <= 8.0
                for sign in sign_tokens
            ):
                continue
            token_center_y = (token.source_bbox[1] + token.source_bbox[3]) / 2.0
            label_center_y = (label.source_bbox[1] + label.source_bbox[3]) / 2.0
            if any(
                bbox_distance(token.source_bbox, excluded.source_bbox) <= 20.0
                and abs(
                    token_center_y
                    - (excluded.source_bbox[1] + excluded.source_bbox[3]) / 2.0
                )
                < abs(token_center_y - label_center_y)
                for excluded in excluded_tokens
            ):
                continue
            parsed.append((token, measurement))
        if not parsed:
            continue
        token, measurement = min(
            parsed,
            key=lambda item: (
                abs(
                    (label.source_bbox[1] + label.source_bbox[3]) / 2.0
                    - (item[0].source_bbox[1] + item[0].source_bbox[3]) / 2.0
                ),
                bbox_distance(label.source_bbox, item[0].source_bbox),
            ),
        )
        raw_text = f"{token.raw_text} {label.raw_text}"
        candidates.append(
            _NumericCandidate(
                value=measurement.value,
                unit=measurement.unit,
                raw_text=raw_text,
                source=_source_for_tokens([token, label], raw_text),
                token_ids=(token.token_id, label.token_id),
                engine_pass=label.engine_pass,
                normalization_rules=tuple(
                    dict.fromkeys(
                        [*token.normalization_rules, *measurement.normalization_rules]
                    )
                ),
            )
        )
    return candidates


def _normalized_candidate_value(candidate: _NumericCandidate) -> float:
    return to_inches(candidate.value, candidate.unit)


def _resolve_numeric_field(
    field_name: str,
    candidates: list[_NumericCandidate],
    *,
    geometry_support: bool = False,
) -> FieldRecognitionResult:
    if not candidates:
        return FieldRecognitionResult(
            field_name=field_name,
            status=FieldStatus.NOT_DETECTED,
            evidence_classification=EvidenceClassification.NOT_DETECTED,
            abstention_reason="no_adjacent_labeled_dimension",
        )
    grouped: dict[float, list[_NumericCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(round(_normalized_candidate_value(candidate), 6), []).append(
            candidate
        )
    competing_values = sorted(grouped)
    resolved_competition = False
    if len(grouped) > 1:
        scored = []
        for value, matches in grouped.items():
            passes = {candidate.engine_pass for candidate in matches}
            location_centers: list[tuple[float, float]] = []
            for candidate in matches:
                if candidate.source.bbox is None:
                    continue
                center = (
                    (candidate.source.bbox[0] + candidate.source.bbox[2]) / 2.0,
                    (candidate.source.bbox[1] + candidate.source.bbox[3]) / 2.0,
                )
                if not any(
                    math.dist(center, existing) <= 8.0 for existing in location_centers
                ):
                    location_centers.append(center)
            score = len(passes) * 2 + len(location_centers)
            scored.append((score, len(passes), value, matches))
        scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
        if len(scored) >= 2 and scored[0][0] >= scored[1][0] + 2 and scored[0][1] >= 2:
            _, _, selected_value, selected_matches = scored[0]
            grouped = {selected_value: selected_matches}
            resolved_competition = True
        else:
            evidence = [
                RecognitionEvidence(
                    rule_id=f"{field_name}_labeled_candidate",
                    description="A labeled dimension candidate was found in the selected region.",
                    source=candidate.source,
                    token_ids=list(candidate.token_ids),
                )
                for candidate in candidates
            ]
            return FieldRecognitionResult(
                field_name=field_name,
                status=FieldStatus.AMBIGUOUS,
                evidence_classification=EvidenceClassification.AMBIGUOUS,
                evidence=evidence,
                candidate_values=competing_values,
                abstention_reason="multiple_equally_supported_labeled_candidates",
            )

    value_in_inches, matching = next(iter(grouped.items()))
    representative = matching[0]
    passes = {candidate.engine_pass for candidate in matching}
    base_passes = {item for item in passes if not item.startswith("target.")}
    normalization_rules = sorted(
        {rule for candidate in matching for rule in candidate.normalization_rules}
    )
    value_repair_rules = [
        rule
        for rule in normalization_rules
        if rule not in {"targeted_callout_ocr", "otsu_threshold_preprocessing"}
    ]
    evidence = [
        RecognitionEvidence(
            rule_id=f"{field_name}_adjacent_label",
            description="Dimension token is spatially adjacent to the field label.",
            source=representative.source,
            token_ids=list(representative.token_ids),
        )
    ]
    if len(base_passes) >= 2:
        evidence.append(
            RecognitionEvidence(
                rule_id="independent_ocr_layout_modes_agree",
                description="Two deterministic Tesseract layout modes produced the same value.",
            )
        )
    if geometry_support:
        evidence.append(
            RecognitionEvidence(
                rule_id="concentric_plate_geometry_present",
                description="The selected region contains concentric plate profiles.",
            )
        )
    if resolved_competition:
        evidence.append(
            RecognitionEvidence(
                rule_id="dominant_repeated_labeled_candidate",
                description="One value had materially stronger repeated OCR and spatial support than competing readings.",
            )
        )
    if value_repair_rules or resolved_competition:
        classification = EvidenceClassification.REQUIRES_CONFIRMATION
        status = FieldStatus.LOW_CONFIDENCE
    elif len(base_passes) >= 2 and geometry_support:
        classification = EvidenceClassification.STRONG
        status = FieldStatus.DETECTED
    else:
        classification = EvidenceClassification.REQUIRES_CONFIRMATION
        status = FieldStatus.LOW_CONFIDENCE
    return FieldRecognitionResult(
        field_name=field_name,
        value=value_in_inches,
        normalized_unit=MeasurementUnit.INCH,
        raw_text=representative.raw_text,
        status=status,
        evidence_classification=classification,
        evidence=evidence,
        candidate_values=[value_in_inches],
        normalization_rules=normalization_rules,
    )


def _line_source(line: SpatialTextLine) -> SourceEvidence:
    return SourceEvidence(
        page_number=line.page_number,
        raw_text=line.raw_text,
        bbox=line.bbox,
        coordinate_unit=line.source_coordinate_unit,
        extraction_method="tesseract_local+deterministic_rules_v1",
    )


def _resolve_material(lines: list[SpatialTextLine]) -> FieldRecognitionResult:
    observations = [(line, parse_material(line.normalized_text)) for line in lines]
    observations = [(line, value) for line, value in observations if value is not None]
    values = sorted({value for _, value in observations})
    if not values:
        return FieldRecognitionResult(
            field_name="material",
            status=FieldStatus.NOT_DETECTED,
            evidence_classification=EvidenceClassification.NOT_DETECTED,
            abstention_reason="no_recognized_material_phrase",
        )
    if len(values) > 1:
        return FieldRecognitionResult(
            field_name="material",
            status=FieldStatus.AMBIGUOUS,
            evidence_classification=EvidenceClassification.AMBIGUOUS,
            candidate_values=values,
            abstention_reason="multiple_material_phrases",
            evidence=[
                RecognitionEvidence(
                    rule_id="material_phrase",
                    description="A recognized material phrase was found.",
                    source=_line_source(line),
                    token_ids=line.token_ids,
                )
                for line, _ in observations
            ],
        )
    value = values[0]
    matching = [(line, found) for line, found in observations if found == value]
    passes = {line.engine_pass for line, _ in matching}
    classification = (
        EvidenceClassification.STRONG
        if len(passes) >= 2
        else EvidenceClassification.REQUIRES_CONFIRMATION
    )
    line = matching[0][0]
    return FieldRecognitionResult(
        field_name="material",
        value=value,
        raw_text=line.raw_text,
        status=(
            FieldStatus.DETECTED
            if classification == EvidenceClassification.STRONG
            else FieldStatus.LOW_CONFIDENCE
        ),
        evidence_classification=classification,
        evidence=[
            RecognitionEvidence(
                rule_id="material_phrase",
                description="Material grade and family occur in one selected-region line.",
                source=_line_source(line),
                token_ids=line.token_ids,
            )
        ],
        candidate_values=[value],
    )


def _resolve_units(tokens: list[OcrTokenObservation]) -> FieldRecognitionResult:
    inch_sources = []
    metric_sources = []
    for token in tokens:
        measurement = parse_measurement(token.interpreted_text)
        if measurement is None or not measurement.explicit_unit:
            continue
        if measurement.unit == MeasurementUnit.INCH:
            inch_sources.append(token)
        elif measurement.unit == MeasurementUnit.MILLIMETER:
            metric_sources.append(token)
    for token in tokens:
        label = _normalized_label(token.interpreted_text)
        if label not in {"IN", "INCH", "MM"}:
            continue
        nearby = _nearby_tokens(token, tokens, maximum_distance=16.0)
        if not any(parse_measurement(candidate.raw_text) for candidate in nearby):
            continue
        if label == "MM":
            metric_sources.append(token)
        else:
            inch_sources.append(token)
    if inch_sources and metric_sources:
        return FieldRecognitionResult(
            field_name="global_units",
            status=FieldStatus.AMBIGUOUS,
            evidence_classification=EvidenceClassification.AMBIGUOUS,
            candidate_values=["in", "mm"],
            abstention_reason="conflicting_explicit_dimension_units",
        )
    sources = inch_sources or metric_sources
    if not sources:
        return FieldRecognitionResult(
            field_name="global_units",
            status=FieldStatus.NOT_DETECTED,
            evidence_classification=EvidenceClassification.NOT_DETECTED,
            abstention_reason="no_explicit_dimension_units",
        )
    unit = MeasurementUnit.INCH if inch_sources else MeasurementUnit.MILLIMETER
    distinct_passes = {token.engine_pass for token in sources}
    classification = (
        EvidenceClassification.STRONG
        if len(sources) >= 2 and len(distinct_passes) >= 2
        else EvidenceClassification.REQUIRES_CONFIRMATION
    )
    return FieldRecognitionResult(
        field_name="global_units",
        value=unit.value,
        normalized_unit=unit,
        raw_text=sources[0].raw_text,
        status=(
            FieldStatus.DETECTED
            if classification == EvidenceClassification.STRONG
            else FieldStatus.LOW_CONFIDENCE
        ),
        evidence_classification=classification,
        evidence=[
            RecognitionEvidence(
                rule_id="repeated_explicit_dimension_unit",
                description="Explicit dimension-unit marks repeat inside the selected region.",
                source=_source_for_tokens([sources[0]], sources[0].raw_text),
                token_ids=[sources[0].token_id],
            )
        ],
        candidate_values=[unit.value],
    )


def _resolve_tolerance(
    lines: list[SpatialTextLine],
    bore: FieldRecognitionResult,
) -> tuple[FieldRecognitionResult, FieldRecognitionResult]:
    candidates: list[tuple[SpatialTextLine, ParsedTolerance]] = []
    for line in lines:
        if (
            "BORE"
            not in normalize_engineering_text(line.normalized_text).normalized_text
        ):
            continue
        parsed = parse_tolerance(
            line.normalized_text, default_unit=MeasurementUnit.INCH
        )
        if parsed is None:
            continue
        magnitudes = [
            value for value in (parsed.plus, parsed.minus) if value is not None
        ]
        if any(value < 0 for value in magnitudes):
            continue
        if bore.value is not None and any(
            value >= float(bore.value) for value in magnitudes
        ):
            continue
        candidates.append((line, parsed))

    pairs = {
        (
            round(parsed.plus, 6) if parsed.plus is not None else None,
            round(parsed.minus, 6) if parsed.minus is not None else None,
            parsed.kind,
        )
        for _, parsed in candidates
    }
    if not candidates:
        missing = lambda name: FieldRecognitionResult(
            field_name=name,
            status=FieldStatus.NOT_DETECTED,
            evidence_classification=EvidenceClassification.NOT_DETECTED,
            abstention_reason="no_coherent_bore_tolerance",
        )
        return missing("bore_tolerance_plus"), missing("bore_tolerance_minus")
    syntax_disagreement = len(pairs) > 1

    def result(name: str, side: str) -> FieldRecognitionResult:
        side_values = sorted(
            {
                round(getattr(parsed, side), 6)
                for _, parsed in candidates
                if getattr(parsed, side) is not None
            }
        )
        side_missing = any(getattr(parsed, side) is None for _, parsed in candidates)
        if len(side_values) > 1 or (side_values and side_missing):
            return FieldRecognitionResult(
                field_name=name,
                status=FieldStatus.AMBIGUOUS,
                evidence_classification=EvidenceClassification.AMBIGUOUS,
                candidate_values=side_values,
                abstention_reason=(
                    "tolerance_side_incompletely_observed"
                    if len(side_values) == 1 and side_missing
                    else "multiple_distinct_bore_tolerances"
                ),
            )
        if not side_values:
            return FieldRecognitionResult(
                field_name=name,
                status=FieldStatus.NOT_DETECTED,
                evidence_classification=EvidenceClassification.NOT_DETECTED,
                abstention_reason="tolerance_side_not_present",
            )
        value = side_values[0]
        line, parsed = next(
            (line, parsed)
            for line, parsed in candidates
            if getattr(parsed, side) is not None
            and round(getattr(parsed, side), 6) == value
        )
        token_rules = sorted(
            {rule for token in line.tokens for rule in token.normalization_rules}
        )
        uses_repair = bool(parsed.normalization_rules or token_rules)
        classification = (
            EvidenceClassification.REQUIRES_CONFIRMATION
            if uses_repair
            or parsed.kind == ToleranceKind.UNILATERAL
            or syntax_disagreement
            else EvidenceClassification.STRONG
        )
        evidence = [
            RecognitionEvidence(
                rule_id="bore_labeled_tolerance_grammar",
                description="Tolerance grammar occurs on a BORE-labeled line.",
                source=_line_source(line),
                token_ids=line.token_ids,
            )
        ]
        return FieldRecognitionResult(
            field_name=name,
            value=value,
            normalized_unit=parsed.unit or MeasurementUnit.INCH,
            raw_text=line.raw_text,
            status=(
                FieldStatus.DETECTED
                if classification == EvidenceClassification.STRONG
                else FieldStatus.LOW_CONFIDENCE
            ),
            evidence_classification=classification,
            evidence=evidence,
            candidate_values=[value],
            normalization_rules=[*parsed.normalization_rules, *token_rules],
        )

    return result("bore_tolerance_plus", "plus"), result(
        "bore_tolerance_minus", "minus"
    )


def _resolve_quantity(lines: list[SpatialTextLine]) -> FieldRecognitionResult:
    observations = []
    for line in lines:
        normalized = normalize_engineering_text(line.normalized_text).normalized_text
        if not re.search(
            r"\b(?:QTY|QUANTITY|REQD|REQUIRED|NO\.?\s*REQ(?:\.?\s*'?D)?)\b",
            normalized,
        ):
            continue
        quantity = parse_quantity(line.normalized_text)
        if quantity is not None:
            observations.append((line, quantity))
    values = sorted({value for _, value in observations})
    if not values:
        return FieldRecognitionResult(
            field_name="quantity",
            status=FieldStatus.NOT_DETECTED,
            evidence_classification=EvidenceClassification.NOT_DETECTED,
            abstention_reason="no_quantity_label_value_pair",
        )
    if len(values) > 1:
        return FieldRecognitionResult(
            field_name="quantity",
            status=FieldStatus.AMBIGUOUS,
            evidence_classification=EvidenceClassification.AMBIGUOUS,
            candidate_values=values,
            abstention_reason="multiple_quantity_values",
        )
    line, value = observations[0]
    passes = {
        candidate.engine_pass for candidate, found in observations if found == value
    }
    base_passes = {item for item in passes if not item.startswith("target.")}
    classification = (
        EvidenceClassification.STRONG
        if len(base_passes) >= 2
        else EvidenceClassification.REQUIRES_CONFIRMATION
    )
    return FieldRecognitionResult(
        field_name="quantity",
        value=value,
        normalized_unit=MeasurementUnit.COUNT,
        raw_text=line.raw_text,
        status=(
            FieldStatus.DETECTED
            if classification == EvidenceClassification.STRONG
            else FieldStatus.LOW_CONFIDENCE
        ),
        evidence_classification=classification,
        evidence=[
            RecognitionEvidence(
                rule_id="quantity_label_value_pair",
                description="Quantity word or number occurs on a quantity-labeled line.",
                source=_line_source(line),
                token_ids=line.token_ids,
            )
        ],
        candidate_values=[value],
    )


def _resolve_chamfer(
    lines: list[SpatialTextLine],
) -> tuple[FieldRecognitionResult, FieldRecognitionResult, FieldRecognitionResult]:
    candidates = []
    for line in lines:
        parsed = parse_chamfer_notation(
            line.normalized_text, default_unit=MeasurementUnit.INCH
        )
        if parsed:
            candidates.append((line, parsed))
    if not candidates:
        missing = lambda name: FieldRecognitionResult(
            field_name=name,
            status=FieldStatus.NOT_DETECTED,
            evidence_classification=EvidenceClassification.NOT_DETECTED,
            abstention_reason="no_explicit_chamfer_notation",
        )
        return (
            missing("chamfer_present"),
            missing("chamfer_width"),
            missing("chamfer_angle"),
        )
    distinct = {
        (round(parsed.width_or_depth, 6), round(parsed.angle_degrees, 6))
        for _, parsed in candidates
    }
    if len(distinct) > 1:
        ambiguous = lambda name: FieldRecognitionResult(
            field_name=name,
            status=FieldStatus.AMBIGUOUS,
            evidence_classification=EvidenceClassification.AMBIGUOUS,
            abstention_reason="multiple_chamfer_notations",
        )
        return (
            ambiguous("chamfer_present"),
            ambiguous("chamfer_width"),
            ambiguous("chamfer_angle"),
        )
    line, parsed = candidates[0]
    evidence = [
        RecognitionEvidence(
            rule_id="explicit_chamfer_width_angle_notation",
            description="A width/depth by angle chamfer notation was parsed.",
            source=_line_source(line),
            token_ids=line.token_ids,
        )
    ]
    common = dict(
        raw_text=line.raw_text,
        status=FieldStatus.LOW_CONFIDENCE,
        evidence_classification=EvidenceClassification.REQUIRES_CONFIRMATION,
        evidence=evidence,
    )
    return (
        FieldRecognitionResult(
            field_name="chamfer_present", value=True, candidate_values=[True], **common
        ),
        FieldRecognitionResult(
            field_name="chamfer_width",
            value=parsed.width_or_depth,
            normalized_unit=parsed.dimension_unit,
            candidate_values=[parsed.width_or_depth],
            **common,
        ),
        FieldRecognitionResult(
            field_name="chamfer_angle",
            value=parsed.angle_degrees,
            normalized_unit=MeasurementUnit.DEGREE,
            candidate_values=[parsed.angle_degrees],
            **common,
        ),
    )


def _resolve_marking(lines: list[SpatialTextLine]) -> FieldRecognitionResult:
    candidates = [
        line
        for line in lines
        if "STAMP" in normalize_engineering_text(line.normalized_text).normalized_text
    ]
    if not candidates:
        return FieldRecognitionResult(
            field_name="marking_text",
            status=FieldStatus.NOT_DETECTED,
            evidence_classification=EvidenceClassification.NOT_DETECTED,
            abstention_reason="no_marking_instruction",
        )
    unique = {line.raw_text for line in candidates}
    if len(unique) > 2:
        return FieldRecognitionResult(
            field_name="marking_text",
            status=FieldStatus.AMBIGUOUS,
            evidence_classification=EvidenceClassification.AMBIGUOUS,
            candidate_values=sorted(unique),
            abstention_reason="multiple_marking_instruction_readings",
        )
    line = candidates[0]
    return FieldRecognitionResult(
        field_name="marking_text",
        value=line.raw_text,
        raw_text=line.raw_text,
        status=FieldStatus.LOW_CONFIDENCE,
        evidence_classification=EvidenceClassification.REQUIRES_CONFIRMATION,
        evidence=[
            RecognitionEvidence(
                rule_id="marking_instruction_line",
                description="A STAMP instruction was found but requires human scoping.",
                source=_line_source(line),
                token_ids=line.token_ids,
            )
        ],
        candidate_values=[line.raw_text],
    )


def _document_metadata_results(
    document: NormalizedDocument,
) -> tuple[FieldRecognitionResult, FieldRecognitionResult]:
    drawing_candidates = []
    for page in document.pages:
        labels = [
            block
            for block in page.text_blocks
            if "DRAWING NUMBER" in block.text.upper()
            and block.bbox[2] - block.bbox[0] <= page.width * 0.5
        ]
        for label in labels:
            for block in page.text_blocks:
                if block.bbox[1] < label.bbox[1] or block.bbox[1] - label.bbox[3] > 35:
                    continue
                numbers = re.findall(r"\b\d{6,20}\b", block.text)
                for number in numbers:
                    drawing_candidates.append((page.page_number, label, block, number))
    distinct = {candidate[3] for candidate in drawing_candidates}
    if len(distinct) == 1:
        page_number, _, block, value = min(
            drawing_candidates, key=lambda candidate: candidate[2].bbox[1]
        )
        drawing = FieldRecognitionResult(
            field_name="drawing_number",
            value=value,
            raw_text=block.text,
            status=FieldStatus.DETECTED,
            evidence_classification=EvidenceClassification.STRONG,
            evidence=[
                RecognitionEvidence(
                    rule_id="native_titleblock_label_proximity",
                    description="A long numeric identifier is directly below a native Drawing Number label.",
                    source=SourceEvidence(
                        page_number=page_number,
                        raw_text=block.text,
                        bbox=block.bbox,
                        coordinate_unit="pdf_point",
                        extraction_method="native_pdf_spatial_metadata_v1",
                    ),
                )
            ],
            candidate_values=[value],
        )
    else:
        drawing = FieldRecognitionResult(
            field_name="drawing_number",
            status=(FieldStatus.AMBIGUOUS if distinct else FieldStatus.NOT_DETECTED),
            evidence_classification=(
                EvidenceClassification.AMBIGUOUS
                if distinct
                else EvidenceClassification.NOT_DETECTED
            ),
            candidate_values=sorted(distinct),
            abstention_reason=(
                "multiple_titleblock_identifiers"
                if distinct
                else "no_titleblock_drawing_number"
            ),
        )

    revision = FieldRecognitionResult(
        field_name="revision",
        status=FieldStatus.NOT_DETECTED,
        evidence_classification=EvidenceClassification.NOT_DETECTED,
        abstention_reason="no_revision_bound_to_drawing_number",
    )
    if drawing.value is not None:
        for page_number, _, block, value in drawing_candidates:
            if value != drawing.value:
                continue
            tail = block.text.split(value, 1)[1].strip().split()
            if tail and re.fullmatch(r"[A-Z0-9-]{1,3}", tail[0], re.IGNORECASE):
                revision_value = tail[0]
                revision = FieldRecognitionResult(
                    field_name="revision",
                    value=revision_value,
                    raw_text=block.text,
                    status=FieldStatus.DETECTED,
                    evidence_classification=EvidenceClassification.STRONG,
                    evidence=[
                        RecognitionEvidence(
                            rule_id="native_revision_adjacent_to_drawing_number",
                            description="Revision token immediately follows the bound drawing number.",
                            source=SourceEvidence(
                                page_number=page_number,
                                raw_text=block.text,
                                bbox=block.bbox,
                                coordinate_unit="pdf_point",
                                extraction_method="native_pdf_spatial_metadata_v1",
                            ),
                        )
                    ],
                    candidate_values=[revision_value],
                )
                break
    return drawing, revision


def _promote_dimension_relationship(
    bore: FieldRecognitionResult,
    outside: FieldRecognitionResult,
) -> None:
    if bore.value is None or outside.value is None:
        return
    if not isinstance(bore.value, (int, float)) or not isinstance(
        outside.value, (int, float)
    ):
        return
    evidence = RecognitionEvidence(
        rule_id="bore_less_than_od_role_consistency",
        description="The labeled bore is smaller than the labeled outside diameter.",
    )
    if float(bore.value) < float(outside.value):
        bore.evidence.append(evidence)
        outside.evidence.append(evidence)
        if bore.evidence_classification == EvidenceClassification.STRONG:
            bore.evidence_classification = EvidenceClassification.VERIFIED.value
        if outside.evidence_classification == EvidenceClassification.STRONG:
            outside.evidence_classification = EvidenceClassification.VERIFIED.value
    else:
        for result in (bore, outside):
            result.evidence_classification = (
                EvidenceClassification.REQUIRES_CONFIRMATION.value
            )
            result.abstention_reason = "bore_od_relationship_conflict"


def _field_status(result: FieldRecognitionResult) -> FieldStatus:
    return FieldStatus(result.status)


def _numeric_field(result: FieldRecognitionResult) -> NumericField:
    return NumericField(
        value=float(result.value) if isinstance(result.value, (int, float)) else None,
        normalized_unit=result.normalized_unit,
        raw_text=result.raw_text,
        confidence=None,
        status=_field_status(result),
        evidence=[item.source for item in result.evidence if item.source is not None],
        warnings=[
            f"deterministic_evidence:{result.evidence_classification}",
            *result.normalization_rules,
            *([result.abstention_reason] if result.abstention_reason else []),
        ],
    )


def _string_field(result: FieldRecognitionResult) -> StringField:
    return StringField(
        value=str(result.value) if result.value is not None else None,
        raw_text=result.raw_text,
        confidence=None,
        status=_field_status(result),
        evidence=[item.source for item in result.evidence if item.source is not None],
        warnings=[
            f"deterministic_evidence:{result.evidence_classification}",
            *([result.abstention_reason] if result.abstention_reason else []),
        ],
    )


def _interpret_region(
    document: NormalizedDocument,
    region: DerivedDrawingRegion,
    ocr: LocalOcrResult,
    geometry: RegionGeometryEvidence,
) -> tuple[dict[str, FieldRecognitionResult], DrawingExtractionResult]:
    tokens = [token for token in ocr.tokens if token.region_id == region.region_id]
    base_tokens = [
        token for token in tokens if not token.engine_pass.startswith("target.")
    ]

    def scoped(purpose: str) -> list[OcrTokenObservation]:
        return [
            token
            for token in tokens
            if not token.engine_pass.startswith("target.")
            or token.engine_pass.startswith(f"target.{purpose}.")
        ]

    base_lines = build_spatial_lines(base_tokens)
    bore_tokens = scoped("bore")
    outside_tokens = scoped("outside")
    thickness_tokens = scoped("thickness")
    bore = _resolve_numeric_field(
        "bore_diameter",
        _adjacent_numeric_candidates(
            bore_tokens,
            labels={"BORE"},
            excluded_neighbor_labels={"BETA"},
        ),
        geometry_support=geometry.has_inner_outer_profiles,
    )
    outside = _resolve_numeric_field(
        "outside_diameter",
        _adjacent_numeric_candidates(outside_tokens, labels={"DIA", "OD"}),
        geometry_support=geometry.has_inner_outer_profiles,
    )
    thickness = _resolve_numeric_field(
        "thickness",
        _adjacent_numeric_candidates(
            thickness_tokens,
            labels={"THK", "THICK", "THICKNESS"},
            thickness_context=True,
            require_explicit_unit=True,
        ),
    )
    _promote_dimension_relationship(bore, outside)
    tolerance_plus, tolerance_minus = _resolve_tolerance(
        build_spatial_lines(bore_tokens), bore
    )
    material = _resolve_material(base_lines)
    units = _resolve_units(base_tokens)
    quantity = _resolve_quantity(build_spatial_lines(scoped("quantity")))
    chamfer_present, chamfer_width, chamfer_angle = _resolve_chamfer(base_lines)
    marking = _resolve_marking(base_lines)
    drawing_number, revision = _document_metadata_results(document)

    not_detected = lambda name, reason: FieldRecognitionResult(
        field_name=name,
        status=FieldStatus.NOT_DETECTED,
        evidence_classification=EvidenceClassification.NOT_DETECTED,
        abstention_reason=reason,
    )
    results = {
        result.field_name: result
        for result in (
            outside,
            bore,
            thickness,
            material,
            quantity,
            units,
            tolerance_plus,
            tolerance_minus,
            not_detected(
                "general_dimensional_tolerance", "no_general_tolerance_detector"
            ),
            chamfer_present,
            chamfer_width,
            not_detected("chamfer_depth", "no_explicit_chamfer_depth"),
            chamfer_angle,
            marking,
            not_detected("customer_part_number", "no_unambiguous_customer_part_number"),
            drawing_number,
            revision,
        )
    }

    fields = DrawingFields(
        outside_diameter=_numeric_field(outside),
        bore_diameter=_numeric_field(bore),
        thickness=_numeric_field(thickness),
        material=_string_field(material),
        quantity=IntegerField(
            value=int(quantity.value) if isinstance(quantity.value, int) else None,
            normalized_unit=quantity.normalized_unit,
            raw_text=quantity.raw_text,
            status=_field_status(quantity),
            evidence=[
                item.source for item in quantity.evidence if item.source is not None
            ],
            warnings=[f"deterministic_evidence:{quantity.evidence_classification}"],
        ),
        global_units=UnitField(
            value=(
                str(units.value)
                if units.value
                in {MeasurementUnit.INCH, MeasurementUnit.MILLIMETER, "in", "mm"}
                else None
            ),
            normalized_unit=units.normalized_unit,
            raw_text=units.raw_text,
            status=_field_status(units),
            evidence=[
                item.source for item in units.evidence if item.source is not None
            ],
            warnings=[f"deterministic_evidence:{units.evidence_classification}"],
        ),
        bore_tolerance_plus=_numeric_field(tolerance_plus),
        bore_tolerance_minus=_numeric_field(tolerance_minus),
        chamfer_present=BooleanField(
            value=(
                bool(chamfer_present.value)
                if isinstance(chamfer_present.value, bool)
                else None
            ),
            raw_text=chamfer_present.raw_text,
            status=_field_status(chamfer_present),
            evidence=[
                item.source
                for item in chamfer_present.evidence
                if item.source is not None
            ],
            warnings=[
                f"deterministic_evidence:{chamfer_present.evidence_classification}"
            ],
        ),
        chamfer_width=_numeric_field(chamfer_width),
        chamfer_angle=_numeric_field(chamfer_angle),
        marking_text=_string_field(marking),
        customer_part_number=_string_field(results["customer_part_number"]),
        drawing_number=_string_field(drawing_number),
        revision=_string_field(revision),
    )
    extraction = DrawingExtractionResult(
        document=DocumentReference(
            filename=document.filename,
            media_type=document.media_type,
            sha256=document.sha256,
            page_count=len(document.pages),
        ),
        provider_name="deterministic_local_region_v1",
        provider_data_handling=ProviderDataHandling(
            external_service=False,
            retention="in_memory_only",
            sends_document_content=False,
        ),
        fields=fields,
        document_warnings=[
            f"Recognition is scoped to selected region {region.region_id}; human confirmation remains required for critical manufacturing fields."
        ],
    )
    return results, extraction


class DeterministicRegionRecognizer:
    def __init__(
        self,
        *,
        ocr_engine: TesseractLocalOcrEngine | None = None,
        dpi: int = 300,
    ) -> None:
        self.ocr_engine = ocr_engine or TesseractLocalOcrEngine()
        self.dpi = dpi

    def recognize(
        self,
        document: NormalizedDocument,
        region: DerivedDrawingRegion,
    ) -> DeterministicRecognitionResult:
        started = time.perf_counter()
        rendered = render_region_png(document, region, dpi=self.dpi)
        ocr = recover_plus_minus_glyphs(self.ocr_engine.recognize(rendered), rendered)
        base_ocr_seconds = ocr.ocr_seconds
        geometry = analyze_region_geometry(document, region)
        interpretation_started = time.perf_counter()
        field_results, extraction = _interpret_region(document, region, ocr, geometry)
        interpretation_seconds = time.perf_counter() - interpretation_started
        from .targeted_ocr import augment_unresolved_callouts

        ocr, targeted_seconds = augment_unresolved_callouts(
            document,
            region,
            ocr,
            field_results,
            self.ocr_engine,
        )
        if targeted_seconds:
            interpretation_started = time.perf_counter()
            field_results, extraction = _interpret_region(
                document, region, ocr, geometry
            )
            interpretation_seconds += time.perf_counter() - interpretation_started
        return DeterministicRecognitionResult(
            region=region,
            rendered_width=rendered.width,
            rendered_height=rendered.height,
            rendered_png_size_bytes=rendered.png_size_bytes,
            rendered_uncompressed_bytes=rendered.uncompressed_grayscale_bytes,
            ocr_token_count=len(ocr.tokens),
            geometry=geometry,
            field_results=field_results,
            extraction=extraction,
            validation=validate_extraction(extraction),
            timings=RecognitionTimings(
                rendering_seconds=rendered.render_seconds,
                ocr_seconds=base_ocr_seconds,
                targeted_ocr_seconds=targeted_seconds,
                interpretation_seconds=interpretation_seconds,
                total_seconds=time.perf_counter() - started,
            ),
        )


def interpret_precomputed_region(
    document: NormalizedDocument,
    region: DerivedDrawingRegion,
    ocr: LocalOcrResult,
) -> tuple[dict[str, FieldRecognitionResult], DrawingExtractionResult]:
    """Test/benchmark entry point that keeps OCR independent from interpretation."""

    return _interpret_region(
        document,
        region,
        ocr,
        analyze_region_geometry(document, region),
    )
