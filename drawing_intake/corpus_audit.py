from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from .classification import DrawingDocumentClass
from .deterministic import (
    DeterministicRegionRecognizer,
    EvidenceClassification,
    FieldRecognitionResult,
)
from .document_recognition import recognize_document_structure
from .documents import normalize_document
from .models import CRITICAL_FIELDS, StrictModel
from .reconciliation_workflow import assess_reconciliation_entry
from .regions import derive_candidate_regions


class AuditRegionTruth(StrictModel):
    region_id: str
    fields: dict[str, float | int | str | bool]


class AuditDocumentTruth(StrictModel):
    source_group_id: str
    source_filename: str
    classification: Literal[
        "real_document", "derived_real_region", "reference_vendor_datasheet"
    ]
    expected_document_class: DrawingDocumentClass
    expected_candidate_count: int | None = Field(default=None, ge=0)
    expected_quote_specific: bool
    recognition_dpi: int = Field(default=300, gt=0)
    regions: list[AuditRegionTruth] = Field(default_factory=list)


class Phase1DCorpusManifest(StrictModel):
    manifest_version: Literal["1.0"] = "1.0"
    documents: list[AuditDocumentTruth]


class AuditFieldResult(StrictModel):
    field_name: str
    expected_value: float | int | str | bool
    detected_value: float | int | str | bool | None = None
    value_correct: bool
    status: str
    evidence_classification: EvidenceClassification
    wrong_authoritative: bool


class AuditRegionResult(StrictModel):
    region_id: str
    fields: list[AuditFieldResult]
    processing_seconds: float = Field(ge=0)


class AuditDocumentResult(StrictModel):
    source_group_id: str
    classification: str
    expected_classification: str
    classification_correct: bool
    candidate_count: int | None = None
    expected_candidate_count: int | None = None
    quote_specific: bool
    quote_specific_correct: bool
    reconciliation_entry_status: str
    canonical_candidate_created: bool
    regions: list[AuditRegionResult] = Field(default_factory=list)
    processing_seconds: float = Field(ge=0)


class Phase1DCorpusAuditReport(StrictModel):
    source_group_count: int = Field(ge=0)
    document_count: int = Field(ge=0)
    documents: list[AuditDocumentResult]
    wrong_critical_authoritative_count: int = Field(ge=0)
    reference_false_quote_count: int = Field(ge=0)


def _equal(actual, expected) -> bool:
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and math.isclose(
            float(actual), float(expected), rel_tol=0.0, abs_tol=1e-6
        )
    return actual == expected


def score_field_result(
    field_name: str,
    expected: float | int | str | bool,
    observed: FieldRecognitionResult,
) -> AuditFieldResult:
    correct = _equal(observed.value, expected)
    authoritative = observed.evidence_classification in {
        EvidenceClassification.STRONG,
        EvidenceClassification.VERIFIED,
    }
    return AuditFieldResult(
        field_name=field_name,
        expected_value=expected,
        detected_value=observed.value,
        value_correct=correct,
        status=str(observed.status),
        evidence_classification=observed.evidence_classification,
        wrong_authoritative=(
            field_name in CRITICAL_FIELDS
            and observed.value is not None
            and not correct
            and authoritative
        ),
    )


def run_phase1d_corpus_audit(
    private_root: str | Path,
    manifest_path: str | Path,
) -> Phase1DCorpusAuditReport:
    private_root = Path(private_root)
    manifest = Phase1DCorpusManifest.model_validate_json(
        Path(manifest_path).read_text(encoding="utf-8")
    )
    results: list[AuditDocumentResult] = []
    for truth in manifest.documents:
        started = time.perf_counter()
        path = private_root / truth.source_filename
        document = normalize_document(path.read_bytes(), path.name)
        recognized = recognize_document_structure(document)
        gate = assess_reconciliation_entry(recognized)
        region_results = []
        if truth.regions:
            regions = {
                region.region_id: region
                for region in derive_candidate_regions(
                    document,
                    recognized.structure,
                    source_group_id=truth.source_group_id,
                )
            }
            recognizer = DeterministicRegionRecognizer(dpi=truth.recognition_dpi)
            for region_truth in truth.regions:
                region_started = time.perf_counter()
                region = regions[region_truth.region_id]
                output = recognizer.recognize(document, region)
                region_results.append(
                    AuditRegionResult(
                        region_id=region_truth.region_id,
                        fields=[
                            score_field_result(
                                field_name,
                                expected,
                                output.field_results[field_name],
                            )
                            for field_name, expected in region_truth.fields.items()
                        ],
                        processing_seconds=time.perf_counter() - region_started,
                    )
                )
        classification = recognized.classification
        results.append(
            AuditDocumentResult(
                source_group_id=truth.source_group_id,
                classification=str(classification.document_class),
                expected_classification=str(truth.expected_document_class),
                classification_correct=(
                    classification.document_class == truth.expected_document_class
                ),
                candidate_count=classification.candidate_count,
                expected_candidate_count=truth.expected_candidate_count,
                quote_specific=classification.quote_specific,
                quote_specific_correct=(
                    classification.quote_specific == truth.expected_quote_specific
                ),
                reconciliation_entry_status=str(gate.status),
                canonical_candidate_created=recognized.canonical_candidate_created,
                regions=region_results,
                processing_seconds=time.perf_counter() - started,
            )
        )
    fields = [
        field
        for document in results
        for region in document.regions
        for field in region.fields
    ]
    return Phase1DCorpusAuditReport(
        source_group_count=len(
            {document.source_group_id for document in manifest.documents}
        ),
        document_count=len(results),
        documents=results,
        wrong_critical_authoritative_count=sum(
            field.wrong_authoritative for field in fields
        ),
        reference_false_quote_count=sum(
            truth.classification == "reference_vendor_datasheet"
            and (
                result.quote_specific
                or result.reconciliation_entry_status != "not_quote_specific"
                or result.canonical_candidate_created
            )
            for truth, result in zip(manifest.documents, results, strict=True)
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit deterministic recognition by independent source group."
    )
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    report = run_phase1d_corpus_audit(args.private_root, args.manifest)
    print(json.dumps(report.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
