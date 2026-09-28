from __future__ import annotations

import io
import math
from statistics import mean

import numpy as np
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


def _broken_centerline_profiles(
    image: Image.Image,
) -> list[tuple[int, int, int]]:
    """Find paired concentric contours when dashed centerlines have no long runs.

    A coarse dilated image proposes centers. Every proposal is checked again
    against the original-resolution ink with two distinct circular perimeters.
    This deliberately abstains on weak arcs and straight ruled-table edges.
    """

    width, height = image.size
    scale = max(1, math.ceil(max(width, height) / 650))
    coarse = image.resize(
        (round(width / scale), round(height / scale)), Image.Resampling.BILINEAR
    )
    ink = np.asarray(coarse) < 230
    coarse_height, coarse_width = ink.shape
    padded = np.pad(ink, 2)
    thick = np.zeros_like(ink)
    for dy in range(5):
        for dx in range(5):
            thick |= padded[dy : dy + coarse_height, dx : dx + coarse_width]

    minimum_radius = max(10, round(min(coarse_width, coarse_height) * 0.025))
    maximum_radius = round(min(coarse_width, coarse_height) * 0.20)
    if maximum_radius <= minimum_radius:
        return []
    xs = np.arange(maximum_radius, coarse_width - maximum_radius, 3)
    ys = np.arange(maximum_radius, coarse_height - maximum_radius, 3)
    if not len(xs) or not len(ys):
        return []
    xx, yy = np.meshgrid(xs, ys)
    centers = np.column_stack((xx.ravel(), yy.ravel()))
    angles = np.arange(32) * math.tau / 32
    cosine, sine = np.cos(angles), np.sin(angles)
    radii = np.arange(minimum_radius, maximum_radius + 1, 2)
    scores = np.empty((len(centers), len(radii)), dtype=np.float32)
    for index, radius in enumerate(radii):
        sample_x = np.rint(centers[:, 0, None] + radius * cosine).astype(int)
        sample_y = np.rint(centers[:, 1, None] + radius * sine).astype(int)
        scores[:, index] = np.mean(thick[sample_y, sample_x], axis=1)

    proposals: list[tuple[float, int, int, int, int]] = []
    minimum_outer = min(coarse_width, coarse_height) * 0.095
    for center, row in zip(centers, scores, strict=True):
        good = np.flatnonzero(row >= 0.85)
        for outer_index in reversed(good):
            outer = int(radii[outer_index])
            if outer < minimum_outer:
                continue
            inner_indices = good[radii[good] <= outer * 0.82]
            if len(inner_indices):
                inner_index = inner_indices[np.argmax(row[inner_indices])]
                proposals.append(
                    (
                        float(min(row[outer_index], row[inner_index])),
                        int(center[0]),
                        int(center[1]),
                        outer,
                        int(radii[inner_index]),
                    )
                )
                break
    proposals.sort(reverse=True)

    # Refine only spatially distinct, high-quality proposals. A title block
    # often yields coarse circle-like votes but fails the original-pixel check.
    retained: list[tuple[float, int, int, int, int]] = []
    for proposal in proposals:
        _, x, y, outer, _ = proposal
        if any(
            math.dist((x, y), (other[1], other[2])) <= outer * 0.25
            for other in retained
        ):
            continue
        retained.append(proposal)
        if len(retained) == 60:
            break

    original = np.asarray(image) < 170
    full_pad = np.pad(original, 1)
    full_ink = np.zeros_like(original)
    for dy in range(3):
        for dx in range(3):
            full_ink |= full_pad[dy : dy + height, dx : dx + width]
    found: list[tuple[int, int, int]] = []
    offsets = np.arange(-scale - 2, scale + 3, 2)
    for _, coarse_x, coarse_y, outer, inner in retained:
        dx, dy = np.meshgrid(offsets, offsets)
        trial_x = (coarse_x * scale + dx.ravel()).astype(int)
        trial_y = (coarse_y * scale + dy.ravel()).astype(int)

        def best_radius(base: int) -> tuple[np.ndarray, np.ndarray]:
            best = np.zeros(len(trial_x))
            chosen = np.zeros(len(trial_x), dtype=int)
            for radius in range(
                max(1, base * scale - 2 * scale),
                base * scale + 2 * scale + 1,
            ):
                sample_x = np.rint(trial_x[:, None] + radius * cosine).astype(int)
                sample_y = np.rint(trial_y[:, None] + radius * sine).astype(int)
                if (
                    sample_x.min() < 0
                    or sample_x.max() >= width
                    or sample_y.min() < 0
                    or sample_y.max() >= height
                ):
                    continue
                score = np.mean(full_ink[sample_y, sample_x], axis=1)
                improved = score > best
                best[improved] = score[improved]
                chosen[improved] = radius
            return best, chosen

        outer_scores, outer_radii = best_radius(outer)
        inner_scores, inner_radii = best_radius(inner)
        quality = np.minimum(outer_scores, inner_scores)
        valid = np.flatnonzero((quality >= 0.75) & (inner_radii <= outer_radii * 0.82))
        if not len(valid):
            continue
        winner = valid[np.argmax(quality[valid])]
        center_x, center_y, radius = (
            int(trial_x[winner]),
            int(trial_y[winner]),
            int(outer_radii[winner]),
        )
        if any(
            math.dist((center_x, center_y), (x, y)) <= max(radius, r) * 0.25
            for x, y, r in found
        ):
            continue
        found.append((center_x, center_y, radius))
    return found


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

    if not candidates:
        for center_x, center_y, outer_radius in _broken_centerline_profiles(image):
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
                    detection_method="raster_two_concentric_perimeters_without_centerline_v1",
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
