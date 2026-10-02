from __future__ import annotations

import math

from pydantic import Field

from .documents import NormalizedDocument, VectorProfileHint
from .models import StrictModel
from .regions import DerivedDrawingRegion


class RegionGeometryEvidence(StrictModel):
    region_id: str
    profile_count: int = Field(ge=0)
    concentric_profile_count: int = Field(ge=0)
    has_inner_outer_profiles: bool
    common_center: tuple[float, float] | None = None
    inner_profile_bbox: tuple[float, float, float, float] | None = None
    outer_profile_bbox: tuple[float, float, float, float] | None = None
    evidence_rules: list[str] = Field(default_factory=list)


def _inside(
    center: tuple[float, float], bbox: tuple[float, float, float, float]
) -> bool:
    return bbox[0] <= center[0] <= bbox[2] and bbox[1] <= center[1] <= bbox[3]


def analyze_region_geometry(
    document: NormalizedDocument,
    region: DerivedDrawingRegion,
) -> RegionGeometryEvidence:
    page = document.pages[region.page_number - 1]
    candidate_center = (
        (region.candidate_bbox[0] + region.candidate_bbox[2]) / 2.0,
        (region.candidate_bbox[1] + region.candidate_bbox[3]) / 2.0,
    )
    center_tolerance = min(page.width, page.height) * 0.0125
    profiles: list[VectorProfileHint] = []
    for profile in page.vector_profile_hints:
        if not _inside(profile.center, region.source_bbox):
            continue
        if math.dist(profile.center, candidate_center) <= center_tolerance:
            profiles.append(profile)
    profiles.sort(key=lambda item: item.width * item.height)
    has_pair = len(profiles) >= 2
    rules = []
    if has_pair:
        rules.append("concentric_inner_outer_vector_profiles")
    if len(profiles) >= 3:
        rules.append("three_nested_plate_profiles")
    return RegionGeometryEvidence(
        region_id=region.region_id,
        profile_count=len(profiles),
        concentric_profile_count=len(profiles),
        has_inner_outer_profiles=has_pair,
        common_center=candidate_center if profiles else None,
        inner_profile_bbox=profiles[0].bbox if profiles else None,
        outer_profile_bbox=profiles[-1].bbox if profiles else None,
        evidence_rules=rules,
    )
