from __future__ import annotations

from statistics import median
from typing import Literal

from pydantic import Field

from .documents import NormalizedDocument, NormalizedPage
from .models import (
    CandidateRegionHint,
    CoordinateUnit,
    DocumentStructureAssessment,
    StrictModel,
)


class DerivedDrawingRegion(StrictModel):
    classification: Literal["derived_real_region"] = "derived_real_region"
    region_id: str
    source_group_id: str
    source_filename: str
    page_number: int = Field(ge=1)
    source_bbox: tuple[float, float, float, float]
    candidate_bbox: tuple[float, float, float, float]
    coordinate_unit: CoordinateUnit = CoordinateUnit.PDF_POINT
    derivation_method: str = "neighbor_partitioned_candidate_region_v1"


def _center(region: CandidateRegionHint) -> tuple[float, float]:
    x0, y0, x1, y1 = region.bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _cluster_rows(
    regions: list[CandidateRegionHint],
) -> list[list[CandidateRegionHint]]:
    if not regions:
        return []
    heights = [region.bbox[3] - region.bbox[1] for region in regions]
    tolerance = max(median(heights) * 0.75, 8.0)
    rows: list[list[CandidateRegionHint]] = []
    for region in sorted(
        regions, key=lambda item: (_center(item)[1], _center(item)[0])
    ):
        center_y = _center(region)[1]
        for row in rows:
            row_y = sum(_center(item)[1] for item in row) / len(row)
            if abs(center_y - row_y) <= tolerance:
                row.append(region)
                break
        else:
            rows.append([region])
    return [sorted(row, key=lambda item: _center(item)[0]) for row in rows]


def _horizontal_bounds(
    row: list[CandidateRegionHint],
    column: int,
    page: NormalizedPage,
) -> tuple[float, float]:
    centers = [_center(region)[0] for region in row]
    current = centers[column]
    candidate_width = row[column].bbox[2] - row[column].bbox[0]
    if column > 0:
        left = (centers[column - 1] + current) / 2.0
    elif len(centers) > 1:
        left = current - (centers[1] - current) / 2.0
    else:
        left = current - candidate_width * 2.0
    if column + 1 < len(centers):
        right = (current + centers[column + 1]) / 2.0
    elif len(centers) > 1:
        right = current + (current - centers[column - 1]) / 2.0
    else:
        right = current + candidate_width * 2.0
    return max(0.0, left), min(page.width, right)


def _vertical_bounds(
    rows: list[list[CandidateRegionHint]],
    row_index: int,
    page: NormalizedPage,
) -> tuple[float, float]:
    row_centers = [sum(_center(region)[1] for region in row) / len(row) for row in rows]
    current = row_centers[row_index]
    candidate_height = median(
        region.bbox[3] - region.bbox[1] for region in rows[row_index]
    )
    if row_index > 0:
        top = (row_centers[row_index - 1] + current) / 2.0
    elif len(row_centers) > 1:
        top = current - (row_centers[1] - current) / 2.0
    else:
        top = current - candidate_height * 1.5
    if row_index + 1 < len(row_centers):
        bottom = (current + row_centers[row_index + 1]) / 2.0
    elif len(row_centers) > 1:
        bottom = current + (current - row_centers[row_index - 1]) * 0.65
    else:
        bottom = current + candidate_height * 3.0
    return max(0.0, top), min(page.height, bottom)


def derive_candidate_regions(
    document: NormalizedDocument,
    structure: DocumentStructureAssessment,
    *,
    source_group_id: str,
) -> list[DerivedDrawingRegion]:
    """Expand plate-profile hints into non-overlapping, neighbor-derived detail cells."""

    output: list[DerivedDrawingRegion] = []
    by_page: dict[int, list[CandidateRegionHint]] = {}
    for candidate in structure.candidate_regions:
        by_page.setdefault(candidate.page_number, []).append(candidate)

    for page_number, candidates in sorted(by_page.items()):
        page = document.pages[page_number - 1]
        rows = _cluster_rows(candidates)
        for row_index, row in enumerate(rows):
            top, bottom = _vertical_bounds(rows, row_index, page)
            for column_index, candidate in enumerate(row):
                left, right = _horizontal_bounds(row, column_index, page)
                output.append(
                    DerivedDrawingRegion(
                        region_id=(
                            f"p{page_number}-r{row_index + 1}-c{column_index + 1}"
                        ),
                        source_group_id=source_group_id,
                        source_filename=document.filename,
                        page_number=page_number,
                        source_bbox=(left, top, right, bottom),
                        candidate_bbox=candidate.bbox,
                        coordinate_unit=candidate.coordinate_unit,
                    )
                )
    return output
