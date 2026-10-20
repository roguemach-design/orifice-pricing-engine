from __future__ import annotations

import argparse
from enum import Enum
from pathlib import Path

from pydantic import Field, model_validator

from .models import DocumentStatus, StrictModel
from .pipeline import DrawingIntakePipeline
from .providers import NativeTextExtractionProvider


class CorpusClassification(str, Enum):
    REAL_DOCUMENT = "real_document"
    DERIVED_REAL_REGION = "derived_real_region"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class GroundTruthCompletionStatus(str, Enum):
    DOCUMENT_LEVEL_COMPLETE = "document_level_complete"
    PER_REGION_PENDING = "per_region_pending"
    COMPLETE = "complete"


class CorpusEntry(StrictModel):
    corpus_id: str
    source_group_id: str
    local_reference: str
    classification: CorpusClassification
    page_count: int = Field(ge=1)
    multi_part: bool
    revision: str | None = None
    expected_production_behavior: str
    ground_truth_status: GroundTruthCompletionStatus
    ground_truth_reference: str
    source_page: int | None = Field(default=None, ge=1)
    source_bbox: tuple[float, float, float, float] | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_region_provenance(self) -> "CorpusEntry":
        if self.classification == CorpusClassification.DERIVED_REAL_REGION:
            if self.source_page is None or self.source_bbox is None:
                raise ValueError(
                    "derived_real_region entries require source_page and source_bbox"
                )
        return self


class CorpusManifest(StrictModel):
    corpus_version: str
    entries: list[CorpusEntry]


class DocumentLevelGroundTruth(StrictModel):
    ground_truth_version: str
    corpus_id: str
    drawing_number: str
    revision: str | None = None
    page_count: int = Field(ge=1)
    multi_part: bool
    visible_plate_region_count: int = Field(ge=0)
    expected_document_status: DocumentStatus
    expected_production_behavior: str
    expected_abstention_reason: str | None = None


class CorpusAccounting(StrictModel):
    real_document_count: int = Field(ge=0)
    independent_source_group_count: int = Field(ge=0)
    derived_real_region_count: int = Field(ge=0)
    synthetic_fixture_count: int = Field(ge=0)


class DocumentSafetyResult(StrictModel):
    corpus_id: str
    source_group_id: str
    expected_page_count: int
    actual_page_count: int
    expected_status: DocumentStatus
    actual_status: DocumentStatus
    expected_region_count: int
    actual_region_count: int | None
    expected_abstention_reason: str | None
    actual_abstention_reason: str | None
    canonical_candidate_populated: bool
    actual_validation_codes: list[str]
    safe_behavior: bool


class DerivedRegionView(StrictModel):
    entry_count: int = Field(ge=0)
    independent_source_group_count: int = Field(ge=0)
    status: str


class RealCorpusBenchmarkReport(StrictModel):
    accounting: CorpusAccounting
    document_level_results: list[DocumentSafetyResult]
    document_level_safe_count: int = Field(ge=0)
    derived_region_view: DerivedRegionView


def load_manifest(path: str | Path) -> CorpusManifest:
    return CorpusManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def summarize_manifest(manifest: CorpusManifest) -> CorpusAccounting:
    real_documents = [
        entry
        for entry in manifest.entries
        if entry.classification == CorpusClassification.REAL_DOCUMENT
    ]
    return CorpusAccounting(
        real_document_count=len(real_documents),
        independent_source_group_count=len(
            {entry.source_group_id for entry in real_documents}
        ),
        derived_real_region_count=sum(
            entry.classification == CorpusClassification.DERIVED_REAL_REGION
            for entry in manifest.entries
        ),
        synthetic_fixture_count=sum(
            entry.classification == CorpusClassification.SYNTHETIC_FIXTURE
            for entry in manifest.entries
        ),
    )


def _resolve_local_reference(root: Path, reference: str) -> Path:
    candidate = (root / reference).resolve()
    resolved_root = root.resolve()
    if candidate.parent != resolved_root:
        raise ValueError("corpus local_reference must be a filename under private_root")
    return candidate


def _load_ground_truth(manifest_path: Path, reference: str) -> DocumentLevelGroundTruth:
    candidate = (manifest_path.parent / reference).resolve()
    if candidate.parent != manifest_path.parent.resolve():
        raise ValueError(
            "ground_truth_reference must be a filename next to the manifest"
        )
    return DocumentLevelGroundTruth.model_validate_json(
        candidate.read_text(encoding="utf-8")
    )


def _candidate_is_populated(candidate) -> bool:
    values = candidate.model_dump(exclude={"source_fields", "missing_required_fields"})
    return any(value is not None for value in values.values())


def run_real_corpus_safety_benchmark(
    manifest_path: str | Path,
    private_root: str | Path,
) -> RealCorpusBenchmarkReport:
    manifest_path = Path(manifest_path)
    private_root = Path(private_root)
    manifest = load_manifest(manifest_path)
    accounting = summarize_manifest(manifest)
    pipeline = DrawingIntakePipeline(NativeTextExtractionProvider())
    results: list[DocumentSafetyResult] = []

    for entry in manifest.entries:
        if entry.classification != CorpusClassification.REAL_DOCUMENT:
            continue
        truth = _load_ground_truth(manifest_path, entry.ground_truth_reference)
        if truth.corpus_id != entry.corpus_id:
            raise ValueError("ground truth corpus_id does not match manifest entry")
        if (
            truth.page_count != entry.page_count
            or truth.multi_part != entry.multi_part
            or truth.revision != entry.revision
        ):
            raise ValueError("ground truth metadata does not match manifest entry")
        source_path = _resolve_local_reference(private_root, entry.local_reference)
        result = pipeline.process(source_path.read_bytes(), source_path.name)
        populated = _candidate_is_populated(result.validation.canonical_candidate)
        validation_codes = sorted(issue.code for issue in result.validation.issues)
        structure_matches = (
            len(result.normalized_document.pages) == truth.page_count
            and result.structure.status == truth.expected_document_status
            and result.structure.candidate_region_count
            == truth.visible_plate_region_count
            and result.structure.abstention_reason == truth.expected_abstention_reason
        )
        if truth.expected_document_status == DocumentStatus.MULTIPLE_CANDIDATES:
            safe = (
                structure_matches
                and not populated
                and "unsupported_multi_part_sheet" in validation_codes
            )
        elif truth.expected_document_status in {
            DocumentStatus.UNKNOWN,
            DocumentStatus.UNREADABLE,
        }:
            safe = structure_matches and not populated
        else:
            safe = (
                structure_matches
                and "unsupported_multi_part_sheet" not in validation_codes
            )
        results.append(
            DocumentSafetyResult(
                corpus_id=entry.corpus_id,
                source_group_id=entry.source_group_id,
                expected_page_count=truth.page_count,
                actual_page_count=len(result.normalized_document.pages),
                expected_status=truth.expected_document_status,
                actual_status=result.structure.status,
                expected_region_count=truth.visible_plate_region_count,
                actual_region_count=result.structure.candidate_region_count,
                expected_abstention_reason=truth.expected_abstention_reason,
                actual_abstention_reason=result.structure.abstention_reason,
                canonical_candidate_populated=populated,
                actual_validation_codes=validation_codes,
                safe_behavior=safe,
            )
        )

    derived_count = accounting.derived_real_region_count
    return RealCorpusBenchmarkReport(
        accounting=accounting,
        document_level_results=results,
        document_level_safe_count=sum(result.safe_behavior for result in results),
        derived_region_view=DerivedRegionView(
            entry_count=derived_count,
            independent_source_group_count=0,
            status=(
                "not_run_no_derived_regions"
                if derived_count == 0
                else "not_run_requires_explicit_region_benchmark"
            ),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the local real-drawing document-safety benchmark."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--private-root", type=Path, required=True)
    args = parser.parse_args()
    report = run_real_corpus_safety_benchmark(args.manifest, args.private_root)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
