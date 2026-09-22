from __future__ import annotations

import io
import time
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from .documents import NormalizedDocument
from .engineering_text import normalize_engineering_text
from .models import FieldStatus
from .ocr import (
    LocalOcrResult,
    OcrTokenObservation,
    TesseractLocalOcrEngine,
    recover_plus_minus_glyphs,
)
from .regions import DerivedDrawingRegion
from .rendering import RenderedRegion, render_region_png

if TYPE_CHECKING:
    from .deterministic import FieldRecognitionResult


def _label(raw: str) -> str:
    return "".join(
        character
        for character in normalize_engineering_text(raw).normalized_text
        if character.isalnum()
    )


def _threshold_variant(rendered: RenderedRegion) -> RenderedRegion:
    image = ImageOps.autocontrast(
        Image.open(io.BytesIO(rendered.png_bytes)).convert("L")
    )
    histogram = image.histogram()
    total = sum(histogram)
    weighted = sum(index * count for index, count in enumerate(histogram))
    background = 0
    background_weight = 0.0
    maximum = -1.0
    threshold = 160
    for level, count in enumerate(histogram):
        background += count
        if not background or background == total:
            continue
        background_weight += level * count
        foreground = total - background
        mean_background = background_weight / background
        mean_foreground = (weighted - background_weight) / foreground
        variance = background * foreground * (mean_background - mean_foreground) ** 2
        if variance > maximum:
            maximum = variance
            threshold = level
    binary = image.point(lambda value: 255 if value > threshold else 0)
    output = io.BytesIO()
    binary.save(output, format="PNG", optimize=False)
    png = output.getvalue()
    return rendered.model_copy(
        update={
            "png_bytes": png,
            "png_size_bytes": len(png),
        }
    )


def _target_region(
    document: NormalizedDocument,
    parent: DerivedDrawingRegion,
    token: OcrTokenObservation,
    purpose: str,
) -> DerivedDrawingRegion:
    page = document.pages[parent.page_number - 1]
    x0, y0, x1, y1 = token.source_bbox
    bbox = (
        max(parent.source_bbox[0], x0 - 50.0),
        max(parent.source_bbox[1], y0 - 28.0),
        min(parent.source_bbox[2], x1 + 50.0),
        min(parent.source_bbox[3], y1 + 28.0),
    )
    bbox = (
        max(0.0, bbox[0]),
        max(0.0, bbox[1]),
        min(page.width, bbox[2]),
        min(page.height, bbox[3]),
    )
    return DerivedDrawingRegion(
        region_id=f"{parent.region_id}-target-{purpose}-{token.token_id.rsplit(':', 1)[-1]}",
        source_group_id=parent.source_group_id,
        source_filename=parent.source_filename,
        page_number=parent.page_number,
        source_bbox=bbox,
        candidate_bbox=parent.candidate_bbox,
        derivation_method=f"targeted_{purpose}_neighborhood_v1",
    )


def _remap_tokens(
    tokens: list[OcrTokenObservation], parent_region_id: str, purpose: str
) -> list[OcrTokenObservation]:
    output = []
    for token in tokens:
        output.append(
            token.model_copy(
                update={
                    "token_id": f"{parent_region_id}:{purpose}:{token.token_id}",
                    "region_id": parent_region_id,
                    "normalization_rules": list(
                        dict.fromkeys(
                            [*token.normalization_rules, "targeted_callout_ocr"]
                        )
                    ),
                }
            )
        )
    return output


def augment_unresolved_callouts(
    document: NormalizedDocument,
    region: DerivedDrawingRegion,
    initial: LocalOcrResult,
    fields: dict[str, "FieldRecognitionResult"],
    engine: TesseractLocalOcrEngine,
) -> tuple[LocalOcrResult, float]:
    """Rerun only unresolved labeled neighborhoods at 600 DPI.

    Target passes corroborate observations but are explicitly marked as derived
    evidence, so they cannot masquerade as independent manufacturing evidence.
    """

    started = time.perf_counter()
    needs = {
        "bore": fields["bore_diameter"].status
        in {FieldStatus.AMBIGUOUS, FieldStatus.LOW_CONFIDENCE, FieldStatus.NOT_DETECTED}
        or fields["bore_tolerance_minus"].status == FieldStatus.NOT_DETECTED,
        "outside": fields["outside_diameter"].status
        in {
            FieldStatus.AMBIGUOUS,
            FieldStatus.LOW_CONFIDENCE,
            FieldStatus.NOT_DETECTED,
        },
        "thickness": fields["thickness"].status
        in {
            FieldStatus.AMBIGUOUS,
            FieldStatus.LOW_CONFIDENCE,
            FieldStatus.NOT_DETECTED,
        },
        "quantity": fields["quantity"].status == FieldStatus.NOT_DETECTED,
    }
    purpose_labels = {
        "bore": {"BORE"},
        "outside": {"DIA", "OD"},
        "thickness": {"THK", "THICK", "THICKNESS"},
        "quantity": {"QTY", "QUANTITY", "REQ", "REQD"},
    }
    selected: list[tuple[str, OcrTokenObservation]] = []
    seen: set[tuple[str, int, int]] = set()
    for purpose, required in needs.items():
        if not required:
            continue
        for token in initial.tokens:
            if _label(token.interpreted_text) not in purpose_labels[purpose]:
                continue
            center = (
                round((token.source_bbox[0] + token.source_bbox[2]) / 2),
                round((token.source_bbox[1] + token.source_bbox[3]) / 2),
            )
            key = (purpose, *center)
            if key not in seen:
                seen.add(key)
                selected.append((purpose, token))

    added: list[OcrTokenObservation] = []
    added_ocr_seconds = 0.0
    for purpose, anchor in selected:
        target = _target_region(document, region, anchor, purpose)
        rendered = render_region_png(document, target, dpi=600)
        raw = engine.recognize(rendered, pass_prefix=f"target.{purpose}.raw.")
        raw = recover_plus_minus_glyphs(raw, rendered)
        added.extend(_remap_tokens(raw.tokens, region.region_id, purpose))
        added_ocr_seconds += raw.ocr_seconds
        if purpose == "bore":
            thresholded = _threshold_variant(rendered)
            threshold_result = engine.recognize(
                thresholded, pass_prefix="target.bore.otsu."
            )
            threshold_result = recover_plus_minus_glyphs(threshold_result, thresholded)
            marked = [
                token.model_copy(
                    update={
                        "normalization_rules": [
                            *token.normalization_rules,
                            "otsu_threshold_preprocessing",
                        ]
                    }
                )
                for token in threshold_result.tokens
            ]
            added.extend(_remap_tokens(marked, region.region_id, purpose))
            added_ocr_seconds += threshold_result.ocr_seconds

    if not added:
        return initial, 0.0
    combined = initial.model_copy(
        update={
            "tokens": [*initial.tokens, *added],
            "ocr_seconds": initial.ocr_seconds + added_ocr_seconds,
        }
    )
    return combined, time.perf_counter() - started
