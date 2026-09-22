from __future__ import annotations

import math

from .documents import NormalizedDocument, VectorProfileHint
from .models import (
    CandidateRegionHint,
    CoordinateUnit,
    DocumentStatus,
    DocumentStructureAssessment,
)


def _cluster_profile_hints(
    hints: list[VectorProfileHint],
    *,
    center_tolerance: float,
) -> list[list[VectorProfileHint]]:
    clusters: list[list[VectorProfileHint]] = []
    for hint in sorted(
        hints, key=lambda item: (item.center[1], item.center[0], -item.width)
    ):
        for cluster in clusters:
            center_x = sum(item.center[0] for item in cluster) / len(cluster)
            center_y = sum(item.center[1] for item in cluster) / len(cluster)
            if math.dist(hint.center, (center_x, center_y)) <= center_tolerance:
                cluster.append(hint)
                break
        else:
            clusters.append([hint])
    return clusters


def _candidate_clusters(document: NormalizedDocument):
    candidates = []
    for page in document.pages:
        tolerance = min(page.width, page.height) * 0.0125
        for cluster in _cluster_profile_hints(
            page.vector_profile_hints,
            center_tolerance=tolerance,
        ):
            distinct_sizes = {
                (round(item.width, 1), round(item.height, 1)) for item in cluster
            }
            if len(cluster) < 2 or len(distinct_sizes) < 2:
                continue
            candidates.append((page.page_number, cluster))
    return candidates


def assess_document_structure(
    document: NormalizedDocument,
) -> DocumentStructureAssessment:
    """Conservative preflight: detect repeated concentric plate-like profiles."""

    candidates = _candidate_clusters(document)
    regions = []
    for page_number, cluster in candidates:
        regions.append(
            CandidateRegionHint(
                page_number=page_number,
                bbox=(
                    min(item.bbox[0] for item in cluster),
                    min(item.bbox[1] for item in cluster),
                    max(item.bbox[2] for item in cluster),
                    max(item.bbox[3] for item in cluster),
                ),
                coordinate_unit=CoordinateUnit.PDF_POINT,
                detection_method="repeated_concentric_vector_profiles",
            )
        )

    if len(regions) > 1:
        return DocumentStructureAssessment(
            status=DocumentStatus.MULTIPLE_CANDIDATES,
            candidate_region_count=len(regions),
            candidate_regions=regions,
            abstention_reason="unsupported_multi_part_sheet_requires_part_selection",
        )
    if len(regions) == 1:
        return DocumentStructureAssessment(
            status=DocumentStatus.SINGLE_CANDIDATE,
            candidate_region_count=1,
            candidate_regions=regions,
        )
    return DocumentStructureAssessment(
        status=DocumentStatus.UNKNOWN,
        candidate_region_count=None,
        abstention_reason="candidate_count_not_determined",
    )
