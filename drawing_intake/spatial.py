from __future__ import annotations

import math

from pydantic import Field

from .models import CoordinateUnit, StrictModel
from .ocr import OcrTokenObservation


class SpatialTextLine(StrictModel):
    region_id: str
    page_number: int = Field(ge=1)
    engine_pass: str
    line_key: str
    raw_text: str
    normalized_text: str
    source_coordinate_unit: CoordinateUnit
    bbox: tuple[float, float, float, float]
    token_ids: list[str]
    tokens: list[OcrTokenObservation]


def bbox_distance(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    horizontal = max(left[0] - right[2], right[0] - left[2], 0.0)
    vertical = max(left[1] - right[3], right[1] - left[3], 0.0)
    return math.hypot(horizontal, vertical)


def vertical_overlap_ratio(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    overlap = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    minimum_height = min(left[3] - left[1], right[3] - right[1])
    return overlap / minimum_height if minimum_height > 0 else 0.0


def same_visual_line(
    left: OcrTokenObservation,
    right: OcrTokenObservation,
) -> bool:
    return (
        left.region_id == right.region_id
        and left.page_number == right.page_number
        and left.engine_pass == right.engine_pass
        and (
            left.line_key == right.line_key
            or vertical_overlap_ratio(left.source_bbox, right.source_bbox) >= 0.5
        )
    )


def build_spatial_lines(tokens: list[OcrTokenObservation]) -> list[SpatialTextLine]:
    grouped: dict[tuple[str, int, str, str], list[OcrTokenObservation]] = {}
    for token in tokens:
        key = (token.region_id, token.page_number, token.engine_pass, token.line_key)
        grouped.setdefault(key, []).append(token)

    lines = []
    for (region_id, page_number, engine_pass, line_key), members in grouped.items():
        ordered = sorted(members, key=lambda item: item.source_bbox[0])
        lines.append(
            SpatialTextLine(
                region_id=region_id,
                page_number=page_number,
                engine_pass=engine_pass,
                line_key=line_key,
                raw_text=" ".join(token.raw_text for token in ordered),
                normalized_text=" ".join(token.interpreted_text for token in ordered),
                source_coordinate_unit=ordered[0].source_coordinate_unit,
                bbox=(
                    min(token.source_bbox[0] for token in ordered),
                    min(token.source_bbox[1] for token in ordered),
                    max(token.source_bbox[2] for token in ordered),
                    max(token.source_bbox[3] for token in ordered),
                ),
                token_ids=[token.token_id for token in ordered],
                tokens=ordered,
            )
        )
    return sorted(
        lines, key=lambda item: (item.page_number, item.bbox[1], item.bbox[0])
    )


def nearest_same_region_token(
    anchor: OcrTokenObservation,
    candidates: list[OcrTokenObservation],
    *,
    maximum_distance: float,
    require_same_line: bool = False,
) -> OcrTokenObservation | None:
    eligible = [
        candidate
        for candidate in candidates
        if candidate.region_id == anchor.region_id
        and candidate.page_number == anchor.page_number
        and candidate.token_id != anchor.token_id
        and (not require_same_line or same_visual_line(anchor, candidate))
        and bbox_distance(anchor.source_bbox, candidate.source_bbox) <= maximum_distance
    ]
    return min(
        eligible,
        key=lambda candidate: bbox_distance(anchor.source_bbox, candidate.source_bbox),
        default=None,
    )
