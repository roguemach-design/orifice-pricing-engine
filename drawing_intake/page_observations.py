from __future__ import annotations

from .documents import NormalizedDocument
from .ocr import LocalOcrResult, TesseractLocalOcrEngine
from .regions import DerivedDrawingRegion
from .rendering import RenderedRegion, render_region_png, rotate_rendered_region


def observe_page_locally(
    document: NormalizedDocument,
    *,
    page_number: int = 1,
    dpi: int = 150,
    ocr_engine: TesseractLocalOcrEngine | None = None,
) -> tuple[LocalOcrResult, int, RenderedRegion]:
    """OCR a page locally and conservatively correct a sideways orientation."""

    page = document.pages[page_number - 1]
    region = DerivedDrawingRegion(
        region_id=f"page-{page_number}-observation",
        source_group_id=document.sha256[:12],
        source_filename=document.filename,
        page_number=page_number,
        source_bbox=(0.0, 0.0, page.width, page.height),
        candidate_bbox=(0.0, 0.0, page.width, page.height),
        coordinate_unit=page.coordinate_unit,
        derivation_method="full_page_local_observation_v1",
    )
    engine = ocr_engine or TesseractLocalOcrEngine()
    rendered = render_region_png(document, region, dpi=dpi)
    candidates: list[tuple[int, LocalOcrResult, RenderedRegion]] = [
        (0, engine.recognize(rendered), rendered)
    ]
    initial_chars = sum(
        len("".join(character for character in token.raw_text if character.isalnum()))
        for token in candidates[0][1].tokens
    )
    initial_mean = initial_chars / max(1, len(candidates[0][1].tokens))
    if initial_mean < 3.0:
        for angle in (90, 270):
            rotated = rotate_rendered_region(rendered, angle)
            rotated_result = engine.recognize(rotated, pass_prefix=f"rot{angle}.")
            candidates.append((angle, rotated_result, rotated))
            readable = " ".join(
                token.raw_text.upper() for token in rotated_result.tokens
            )
            if (
                sum(
                    word in readable
                    for word in (
                        "ORIFICE",
                        "PLATE",
                        "BORE",
                        "MATERIAL",
                        "DIMENSION",
                        "QTY",
                        "TAG",
                    )
                )
                >= 3
            ):
                break
    scored = []
    for angle, result, candidate_render in candidates:
        text = " ".join(token.raw_text.upper() for token in result.tokens)
        characters = sum(
            len(
                "".join(
                    character for character in token.raw_text if character.isalnum()
                )
            )
            for token in result.tokens
        )
        engineering_words = sum(
            text.count(word)
            for word in (
                "ORIFICE",
                "PLATE",
                "BORE",
                "MATERIAL",
                "DIMENSION",
                "QTY",
                "TAG",
            )
        )
        scored.append(
            (
                characters + engineering_words * 500,
                characters,
                angle,
                result,
                candidate_render,
            )
        )
    scored.sort(reverse=True, key=lambda item: item[0])
    best_score, best_chars, best_angle, best, best_render = scored[0]
    if (
        best_angle
        and best_chars < initial_chars * 1.5
        and best_score < initial_chars * 2
    ):
        return candidates[0][1], 0, candidates[0][2]
    return best, best_angle, best_render
