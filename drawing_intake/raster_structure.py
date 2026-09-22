from __future__ import annotations

import io
import math
from statistics import mean

from PIL import Image, ImageOps

from .models import (
    CandidateRegionHint,
    DocumentStatus,
    DocumentStructureAssessment,
)
from .rendering import RenderedRegion


def _longest_ink_run(values: list[bool], *, allowed_gap: int = 2) -> int:
    best = current = gap = 0
    for value in values:
        if value:
            current += 1
            gap = 0
        elif current and gap < allowed_gap:
            current += 1
            gap += 1
        else:
            best = max(best, current - gap)
            current = gap = 0
    return max(best, current - gap)


def _cluster_centers(values: list[int], *, maximum_gap: int = 2) -> list[int]:
    groups: list[list[int]] = []
    for value in values:
        if groups and value <= groups[-1][-1] + maximum_gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [round(mean(group)) for group in groups]


def _has_ink_near(
    pixels,
    width: int,
    height: int,
    x: int,
    y: int,
    *,
    radius: int = 1,
) -> bool:
    for sample_y in range(max(0, y - radius), min(height, y + radius + 1)):
        for sample_x in range(max(0, x - radius), min(width, x + radius + 1)):
            if pixels[sample_x, sample_y] < 170:
                return True
    return False


def _circle_score(
    pixels,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    radius: int,
) -> float:
    samples = 32
    hits = 0
    for index in range(samples):
        angle = (math.tau * index) / samples
        x = round(center_x + radius * math.cos(angle))
        y = round(center_y + radius * math.sin(angle))
        if not (0 <= x < width and 0 <= y < height):
            return 0.0
        hits += _has_ink_near(pixels, width, height, x, y)
    return hits / samples


def _radius_bands(scores: list[tuple[int, float]]) -> list[list[tuple[int, float]]]:
    groups: list[list[tuple[int, float]]] = []
    for radius, score in scores:
        if groups and radius <= groups[-1][-1][0] + 2:
            groups[-1].append((radius, score))
        else:
            groups.append([(radius, score)])
    return groups


def detect_raster_plate_structure(
    rendered: RenderedRegion,
) -> DocumentStructureAssessment:
    """Find concentric plate profiles in a raster using inspectable shape rules.

    Candidate centers must be supported by crossing long centerline-like ink runs
    and two separated circular perimeter bands. No OCR words, company names,
    drawing identifiers, or product-catalog limits participate in this detector.
    """

    image = ImageOps.autocontrast(
        Image.open(io.BytesIO(rendered.png_bytes)).convert("L")
    )
    width, height = image.size
    pixels = image.load()
    row_centers = _cluster_centers(
        [
            y
            for y in range(height)
            if _longest_ink_run([pixels[x, y] < 170 for x in range(width)])
            >= width * 0.12
        ]
    )
    column_centers = _cluster_centers(
        [
            x
            for x in range(width)
            if _longest_ink_run([pixels[x, y] < 170 for y in range(height)])
            >= height * 0.15
        ]
    )

    smallest_side = min(width, height)
    minimum_radius = max(10, round(smallest_side * 0.025))
    maximum_radius = max(minimum_radius + 1, round(smallest_side * 0.20))
    minimum_outer_radius = smallest_side * 0.095
    candidates: list[CandidateRegionHint] = []
    accepted_centers: list[tuple[int, int]] = []
    for center_x in column_centers:
        for center_y in row_centers:
            if (
                center_x < maximum_radius
                or center_x > width - maximum_radius
                or center_y < maximum_radius
                or center_y > height - maximum_radius
            ):
                continue
            strong = [
                (radius, score)
                for radius in range(minimum_radius, maximum_radius + 1)
                if (
                    score := _circle_score(
                        pixels, width, height, center_x, center_y, radius
                    )
                )
                >= 0.40
            ]
            bands = _radius_bands(strong)
            if len(bands) < 2:
                continue
            representative_radii = [
                max(group, key=lambda item: item[1])[0] for group in bands
            ]
            representative_scores = [
                max(score for _, score in group) for group in bands
            ]
            outer_radius = max(representative_radii)
            inner_radii = [
                radius
                for radius, score in zip(
                    representative_radii, representative_scores, strict=True
                )
                if radius <= outer_radius * 0.82 and score >= 0.60
            ]
            if outer_radius < minimum_outer_radius or not inner_radii:
                continue
            if any(
                math.dist((center_x, center_y), accepted) <= outer_radius * 0.25
                for accepted in accepted_centers
            ):
                continue
            accepted_centers.append((center_x, center_y))
            source_bbox = rendered.transform.pixel_bbox_to_pdf(
                (
                    center_x - outer_radius,
                    center_y - outer_radius,
                    center_x + outer_radius,
                    center_y + outer_radius,
                )
            )
            candidates.append(
                CandidateRegionHint(
                    page_number=rendered.region.page_number,
                    bbox=source_bbox,
                    coordinate_unit=rendered.region.coordinate_unit,
                    detection_method=(
                        "raster_centerline_plus_two_concentric_perimeters_v1"
                    ),
                )
            )

    candidates.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
    if not candidates:
        return DocumentStructureAssessment(
            status=DocumentStatus.UNKNOWN,
            candidate_region_count=0,
            abstention_reason="no_raster_concentric_plate_profiles",
        )
    return DocumentStructureAssessment(
        status=(
            DocumentStatus.SINGLE_CANDIDATE
            if len(candidates) == 1
            else DocumentStatus.MULTIPLE_CANDIDATES
        ),
        candidate_region_count=len(candidates),
        candidate_regions=candidates,
    )
