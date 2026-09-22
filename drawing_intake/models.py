from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class FieldStatus(str, Enum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    CONFLICT_DETECTED = "conflict_detected"
    LOW_CONFIDENCE = "low_confidence"
    UNREADABLE = "unreadable"


class ValidationState(str, Enum):
    NOT_CHECKED = "not_checked"
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"


class MeasurementUnit(str, Enum):
    INCH = "in"
    MILLIMETER = "mm"
    DEGREE = "deg"
    COUNT = "count"


class CoordinateUnit(str, Enum):
    PDF_POINT = "pdf_point"
    PIXEL = "pixel"


class DocumentStatus(str, Enum):
    SINGLE_CANDIDATE = "single_candidate"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    UNKNOWN = "unknown"
    UNREADABLE = "unreadable"


class CandidateRegionHint(StrictModel):
    page_number: int = Field(ge=1)
    bbox: tuple[float, float, float, float]
    coordinate_unit: CoordinateUnit
    detection_method: str


class DocumentStructureAssessment(StrictModel):
    status: DocumentStatus
    candidate_region_count: int | None = Field(default=None, ge=0)
    candidate_regions: list[CandidateRegionHint] = Field(default_factory=list)
    abstention_reason: str | None = None


class SourceEvidence(StrictModel):
    page_number: int = Field(ge=1)
    raw_text: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    coordinate_unit: CoordinateUnit | None = None
    extraction_method: str


ScalarValue = float | int | str | bool


class ExtractedField(StrictModel):
    value: ScalarValue | None = None
    normalized_unit: MeasurementUnit | None = None
    raw_text: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: FieldStatus = FieldStatus.NOT_DETECTED
    evidence: list[SourceEvidence] = Field(default_factory=list)
    validation_state: ValidationState = ValidationState.NOT_CHECKED
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_status_value_consistency(self) -> "ExtractedField":
        if self.status == FieldStatus.DETECTED and self.value is None:
            raise ValueError("detected fields require a value")
        if (
            self.status in {FieldStatus.NOT_DETECTED, FieldStatus.UNREADABLE}
            and self.value is not None
        ):
            raise ValueError(f"{self.status} fields must not contain a value")
        return self


class NumericField(ExtractedField):
    value: float | None = None


class IntegerField(ExtractedField):
    value: int | None = None


class BooleanField(ExtractedField):
    value: bool | None = None


class StringField(ExtractedField):
    value: str | None = None


class UnitField(ExtractedField):
    value: Literal["in", "mm"] | None = None


class DrawingFields(StrictModel):
    outside_diameter: NumericField = Field(default_factory=NumericField)
    bore_diameter: NumericField = Field(default_factory=NumericField)
    thickness: NumericField = Field(default_factory=NumericField)
    material: StringField = Field(default_factory=StringField)
    quantity: IntegerField = Field(default_factory=IntegerField)
    global_units: UnitField = Field(default_factory=UnitField)
    bore_tolerance_plus: NumericField = Field(default_factory=NumericField)
    bore_tolerance_minus: NumericField = Field(default_factory=NumericField)
    general_dimensional_tolerance: NumericField = Field(default_factory=NumericField)
    chamfer_present: BooleanField = Field(default_factory=BooleanField)
    chamfer_width: NumericField = Field(default_factory=NumericField)
    chamfer_depth: NumericField = Field(default_factory=NumericField)
    chamfer_angle: NumericField = Field(default_factory=NumericField)
    marking_text: StringField = Field(default_factory=StringField)
    customer_part_number: StringField = Field(default_factory=StringField)
    drawing_number: StringField = Field(default_factory=StringField)
    revision: StringField = Field(default_factory=StringField)


class ProviderDataHandling(StrictModel):
    external_service: bool
    retention: str
    sends_document_content: bool


class DocumentReference(StrictModel):
    filename: str
    media_type: str
    sha256: str
    page_count: int = Field(ge=1)


class DrawingExtractionResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    document: DocumentReference
    provider_name: str
    provider_data_handling: ProviderDataHandling
    fields: DrawingFields
    document_warnings: list[str] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ValidationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class ValidationIssue(StrictModel):
    code: str
    message: str
    severity: ValidationSeverity
    field_names: list[str]


class CanonicalConfigurationCandidate(StrictModel):
    """Partial object using the exact existing QuoteInputs field names."""

    quantity: int | None = None
    material: str | None = None
    thickness: float | None = None
    handle_width: float | None = None
    handle_length_from_bore: float | None = None
    paddle_dia: float | None = None
    bore_dia: float | None = None
    bore_tolerance: float | None = None
    chamfer: bool | None = None
    ships_in_days: int | None = None
    handle_label: str | None = None
    chamfer_width: float | None = None
    source_fields: dict[str, str] = Field(default_factory=dict)
    missing_required_fields: list[str] = Field(default_factory=list)


class DomainValidationResult(StrictModel):
    extraction: DrawingExtractionResult
    issues: list[ValidationIssue] = Field(default_factory=list)
    field_outcomes: dict[str, FieldStatus] = Field(default_factory=dict)
    canonical_candidate: CanonicalConfigurationCandidate

    @property
    def valid_for_candidate(self) -> bool:
        return not any(
            issue.severity == ValidationSeverity.ERROR for issue in self.issues
        )


class ComparisonStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    EXTRACTION_UNKNOWN = "extraction_unknown"
    UNSUPPORTED = "unsupported"
    NOT_COMPARABLE = "not_comparable"


class FieldComparison(StrictModel):
    extraction_field: str
    canonical_field: str | None
    status: ComparisonStatus
    customer_value: Any = None
    drawing_value: Any = None
    drawing_unit: MeasurementUnit | None = None
    message: str | None = None


class ReconciliationResult(StrictModel):
    comparisons: list[FieldComparison]


CRITICAL_FIELDS = frozenset(
    {
        "outside_diameter",
        "bore_diameter",
        "thickness",
        "material",
        "global_units",
        "bore_tolerance_plus",
        "bore_tolerance_minus",
    }
)
