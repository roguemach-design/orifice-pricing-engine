"""Bounded, generic handle callout evidence for a selected plate detail.

Unlabeled dimensions need both a readable numeric token and dimension-line
topology tied to the selected plate profile. No pixel length is converted into
a manufacturing dimension: the printed number is always the proposed value.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .engineering_text import normalize_engineering_text, parse_measurement
from .models import MeasurementUnit, SourceEvidence
from .ocr import LocalOcrResult, OcrTokenObservation, TesseractLocalOcrEngine
from .regions import DerivedDrawingRegion
from .rendering import RenderedRegion, render_region_png, rotate_rendered_region
from .spatial import bbox_distance, build_spatial_lines


@dataclass(frozen=True)
class HandleObservation:
    value_in: float
    raw_text: str
    source: SourceEvidence
    token_ids: tuple[str, ...]
    engine_pass: str
    rule_id: str
    normalization_rules: tuple[str, ...]


_NUMBER_WITH_UNIT = re.compile(
    r"(?P<number>(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d*)?|\.\d+))"
    r'\s*(?P<unit>"|MM|MILLIMETERS?|IN|INCH(?:ES)?)?\s*'
)


def _measurement(
    raw: str, global_units: MeasurementUnit | None
) -> tuple[float, tuple[str, ...]] | None:
    normalized = normalize_engineering_text(raw, numeric_context=True)
    if not _NUMBER_WITH_UNIT.fullmatch(normalized.normalized_text):
        return None
    parsed = parse_measurement(raw, default_unit=global_units)
    if parsed is None or parsed.value <= 0 or parsed.unit is None:
        return None
    unit = parsed.unit
    return (
        parsed.value / 25.4 if unit == MeasurementUnit.MILLIMETER else parsed.value,
        tuple(
            dict.fromkeys(
                [*normalized.normalization_rules, *parsed.normalization_rules]
            )
        ),
    )


def _source(token: OcrTokenObservation) -> SourceEvidence:
    return SourceEvidence(
        page_number=token.page_number,
        raw_text=token.raw_text,
        bbox=token.source_bbox,
        coordinate_unit=token.source_coordinate_unit,
        extraction_method="tesseract_local+handle_dimension_topology_v1",
    )


def _profile(region: DerivedDrawingRegion) -> tuple[float, float, float] | None:
    x0, y0, x1, y1 = region.candidate_bbox
    radius = (x1 - x0) / 2.0
    if radius <= 0 or not 0.75 <= (y1 - y0) / (x1 - x0) <= 1.25:
        return None
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0, radius)


class _InkTopology:
    def __init__(self, rendered: RenderedRegion) -> None:
        self.rendered = rendered
        self.ink = (
            np.asarray(Image.open(io.BytesIO(rendered.png_bytes)).convert("L")) < 170
        )

    def x(self, source_x: float) -> int:
        transform = self.rendered.transform
        return round((source_x - transform.pdf_bbox[0]) / transform.points_per_pixel_x)

    def y(self, source_y: float) -> int:
        transform = self.rendered.transform
        return round((source_y - transform.pdf_bbox[1]) / transform.points_per_pixel_y)

    @staticmethod
    def _longest(values: np.ndarray) -> int:
        indices = np.flatnonzero(~values)
        boundaries = np.concatenate(([-1], indices, [len(values)]))
        return int(np.max(np.diff(boundaries) - 1))

    def horizontal(self, y: float, left: float, right: float) -> bool:
        x0, x1 = sorted((self.x(left), self.x(right)))
        x0, x1 = max(0, x0), min(self.ink.shape[1], x1)
        if x1 - x0 < 12:
            return False
        middle = self.y(y)
        for row in range(max(0, middle - 3), min(self.ink.shape[0], middle + 4)):
            values = self.ink[row, x0:x1]
            if self._longest(values) >= 0.70 * len(values):
                return True
        return False

    def vertical(self, x: float, top: float, bottom: float) -> bool:
        y0, y1 = sorted((self.y(top), self.y(bottom)))
        y0, y1 = max(0, y0), min(self.ink.shape[0], y1)
        if y1 - y0 < 12:
            return False
        middle = self.x(x)
        for col in range(max(0, middle - 3), min(self.ink.shape[1], middle + 4)):
            values = self.ink[y0:y1, col]
            if self._longest(values) >= 0.65 * len(values):
                return True
        return False


def _width_topology(
    token: OcrTokenObservation,
    profile: tuple[float, float, float],
    ink: _InkTopology,
) -> bool:
    cx, cy, radius = profile
    x0, y0, x1, y1 = token.source_bbox
    if not (cy - 2.2 * radius < y1 < cy - radius * 1.05):
        return False
    if not (abs((x0 + x1) / 2 - cx) < radius * 0.32):
        return False
    # An unlabeled width must sit between two stem/extension lines, connected
    # by the dimension line. Searching is relative to the plate radius.
    left_sides = [
        left
        for step in range(18, 70)
        if (left := cx - radius * step / 100) < x0 - radius * 0.07
        and ink.vertical(left, y1, cy - radius * 0.96)
    ]
    right_sides = [
        right
        for step in range(18, 70)
        if (right := cx + radius * step / 100) > x1 + radius * 0.07
        and ink.vertical(right, y1, cy - radius * 0.96)
    ]
    for left in left_sides:
        for right in right_sides:
            for y in np.linspace(y0, y1 + radius * 0.08, 10):
                if ink.horizontal(y, left, x0) and ink.horizontal(y, x1, right):
                    return True
    return False


def _length_topology(
    token: OcrTokenObservation,
    profile: tuple[float, float, float],
    ink: _InkTopology,
) -> bool:
    cx, cy, radius = profile
    x0, y0, x1, y1 = token.source_bbox
    if not (y1 - y0 > x1 - x0 and y0 < cy - radius * 0.35 < y1 + radius):
        return False
    if not (cy - 1.55 * radius < y0 and y1 < cy - 0.15 * radius):
        return False
    side = 1 if x0 > cx + radius else -1 if x1 < cx - radius else 0
    if not side:
        return False
    # The lower witness line must pass through the bore center; the upper one
    # must meet the handle tip. Their locations only classify the callout.
    for dimension_x in np.linspace(
        x1 + radius * 0.02 if side == 1 else x0 - radius * 0.02,
        x1 + radius * 0.17 if side == 1 else x0 - radius * 0.17,
        9,
    ):
        if not ink.vertical(dimension_x, cy - radius * 1.22, y0 - radius * 0.04):
            continue
        if not ink.vertical(dimension_x, y1 + radius * 0.04, cy - radius * 0.02):
            continue
        if not any(
            ink.horizontal(y, cx, dimension_x)
            for y in np.linspace(cy - radius * 0.035, cy + radius * 0.035, 9)
        ):
            continue
        return any(
            ink.horizontal(y, cx, dimension_x)
            for y in np.linspace(cy - radius * 1.52, cy - radius * 1.02, 30)
        )
    return False


def augment_vertical_handle_ocr(
    document,
    region: DerivedDrawingRegion,
    original: LocalOcrResult,
    engine: TesseractLocalOcrEngine,
) -> tuple[LocalOcrResult, float]:
    """Read the upper handle/profile neighborhood after a local 270° rotation."""

    from time import perf_counter

    profile = _profile(region)
    if profile is None:
        return original, 0.0
    cx, cy, radius = profile
    x0, y0, x1, y1 = region.source_bbox
    bbox = (
        max(x0, cx - radius * 1.85),
        max(y0, cy - radius * 1.85),
        min(x1, cx + radius * 1.85),
        min(y1, cy + radius * 0.13),
    )
    target = region.model_copy(
        update={"region_id": region.region_id + "-handle-rotated", "source_bbox": bbox}
    )
    started = perf_counter()
    rotated = rotate_rendered_region(render_region_png(document, target, dpi=300), 270)
    observed = engine.recognize(rotated, pass_prefix="target.handle.rot270.")
    tokens = [
        token.model_copy(
            update={
                "token_id": f"{region.region_id}:handle:{token.token_id}",
                "region_id": region.region_id,
                "normalization_rules": ["rotated_handle_callout_ocr"],
            }
        )
        for token in observed.tokens
    ]
    return (
        original.model_copy(update={"tokens": [*original.tokens, *tokens]}),
        perf_counter() - started,
    )


def detect_handle_observations(
    region: DerivedDrawingRegion,
    ocr: LocalOcrResult,
    rendered: RenderedRegion | None,
    global_unit: MeasurementUnit | None,
) -> dict[str, list[HandleObservation]]:
    results: dict[str, list[HandleObservation]] = {
        "handle_width": [],
        "handle_length_from_bore": [],
    }
    tokens = [t for t in ocr.tokens if t.region_id == region.region_id]
    profile = _profile(region)
    ink = _InkTopology(rendered) if rendered is not None and profile else None

    for line in build_spatial_lines(tokens):
        labels = normalize_engineering_text(line.normalized_text).normalized_text
        if "HANDLE" not in labels:
            continue
        field = (
            "handle_width"
            if "WIDTH" in labels or "WIDE" in labels
            else (
                "handle_length_from_bore"
                if "LENGTH" in labels and ("BORE" in labels or "CENTER" in labels)
                else None
            )
        )
        if field is None:
            continue
        labels_on_line = [
            token
            for token in line.tokens
            if any(
                word in token.interpreted_text.upper()
                for word in ("HANDLE", "WIDTH", "WIDE", "LENGTH", "CENTER")
            )
        ]
        for token in line.tokens:
            if (
                not labels_on_line
                or min(
                    bbox_distance(token.source_bbox, label.source_bbox)
                    for label in labels_on_line
                )
                > 40.0
            ):
                continue
            measured = _measurement(token.interpreted_text, global_unit)
            if measured:
                value, rules = measured
                results[field].append(
                    HandleObservation(
                        value,
                        token.raw_text,
                        _source(token),
                        (token.token_id,),
                        token.engine_pass,
                        "explicit_handle_dimension_label",
                        rules,
                    )
                )

    if profile is None or ink is None:
        return results
    for token in tokens:
        measured = _measurement(token.interpreted_text, global_unit)
        if not measured:
            continue
        value, rules = measured
        vertical = token.engine_pass.startswith("target.handle.rot270.")
        field = "handle_length_from_bore" if vertical else "handle_width"
        supported = (
            _length_topology(token, profile, ink)
            if vertical
            else _width_topology(token, profile, ink)
        )
        if supported:
            results[field].append(
                HandleObservation(
                    value,
                    token.raw_text,
                    _source(token),
                    (token.token_id,),
                    token.engine_pass,
                    (
                        "bore_center_to_tip_dimension_lines"
                        if vertical
                        else "stem_width_dimension_lines"
                    ),
                    rules,
                )
            )
    return results
