from __future__ import annotations

import io
import re
import time

from PIL import Image
from pydantic import Field

from .engineering_text import (
    parse_material,
    parse_measurement,
    parse_quantity,
    parse_tolerance,
)
from .models import (
    CoordinateUnit,
    FieldStatus,
    MeasurementUnit,
    SourceEvidence,
    StrictModel,
)
from .documents import NormalizedDocument
from .ocr import (
    LocalOcrResult,
    OcrTokenObservation,
    TesseractLocalOcrEngine,
    recover_plus_minus_glyphs,
)
from .regions import DerivedDrawingRegion
from .rendering import (
    RenderedRegion,
    render_region_png,
    rotate_rendered_region,
)


class TableGrid(StrictModel):
    horizontal_lines: list[int]
    vertical_lines: list[int]
    source_bbox: tuple[float, float, float, float]
    coordinate_unit: CoordinateUnit = CoordinateUnit.PDF_POINT


class TableFieldObservation(StrictModel):
    value: float | int | str | None = None
    normalized_unit: MeasurementUnit | None = None
    raw_text: str | None = None
    status: FieldStatus
    evidence: SourceEvidence | None = None
    reason: str | None = None
    raw_observations: list[str] = Field(default_factory=list)
    normalization_rules: list[str] = Field(default_factory=list)


class TablePlateCandidate(StrictModel):
    row_index: int = Field(ge=1)
    tag: TableFieldObservation
    quantity: TableFieldObservation
    outside_diameter: TableFieldObservation
    thickness: TableFieldObservation
    bore_diameter: TableFieldObservation
    bore_tolerance_plus: TableFieldObservation
    bore_tolerance_minus: TableFieldObservation
    material: TableFieldObservation
    global_units: TableFieldObservation


class TableScheduleResult(StrictModel):
    grid: TableGrid | None = None
    candidates: list[TablePlateCandidate] = Field(default_factory=list)
    document_warnings: list[str] = Field(default_factory=list)
    quote_candidate_created: bool = False
    targeted_ocr_seconds: float = Field(default=0.0, ge=0)


def _clusters(indices: list[int]) -> list[list[int]]:
    output: list[list[int]] = []
    for value in indices:
        if output and value <= output[-1][-1] + 1:
            output[-1].append(value)
        else:
            output.append([value])
    return output


def detect_ruled_table(rendered: RenderedRegion) -> TableGrid | None:
    """Detect a substantial ruled grid using projection profiles only."""

    image = Image.open(io.BytesIO(rendered.png_bytes)).convert("L")
    width, height = image.size
    pixels = image.load()
    horizontal_counts = [
        sum(pixels[x, y] < 230 for x in range(width)) for y in range(height)
    ]
    horizontal = [
        round(sum(group) / len(group))
        for group in _clusters(
            [
                index
                for index, count in enumerate(horizontal_counts)
                if count >= width * 0.35
            ]
        )
    ]
    if len(horizontal) < 4:
        return None

    sequences: list[list[int]] = []
    for line in horizontal:
        if sequences and line - sequences[-1][-1] <= max(80, height * 0.08):
            sequences[-1].append(line)
        else:
            sequences.append([line])
    horizontal = max(sequences, key=lambda item: (len(item), item[-1] - item[0]))
    if len(horizontal) < 4:
        return None
    top, bottom = horizontal[0], horizontal[-1]
    span = max(1, bottom - top + 1)
    vertical_counts = [
        sum(pixels[x, y] < 230 for y in range(top, bottom + 1)) for x in range(width)
    ]
    vertical = [
        round(sum(group) / len(group))
        for group in _clusters(
            [
                index
                for index, count in enumerate(vertical_counts)
                if count >= span * 0.72
            ]
        )
    ]
    if len(vertical) < 3:
        return None
    source_bbox = rendered.transform.pixel_bbox_to_pdf(
        (vertical[0], horizontal[0], vertical[-1], horizontal[-1])
    )
    return TableGrid(
        horizontal_lines=horizontal,
        vertical_lines=vertical,
        source_bbox=source_bbox,
        coordinate_unit=rendered.region.coordinate_unit,
    )


def _token_center(token: OcrTokenObservation) -> tuple[float, float]:
    x0, y0, x1, y1 = token.pixel_bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def _cell_tokens(
    tokens: list[OcrTokenObservation], bbox: tuple[int, int, int, int]
) -> list[OcrTokenObservation]:
    x0, y0, x1, y1 = bbox
    selected = [
        token
        for token in tokens
        if x0 <= _token_center(token)[0] <= x1 and y0 <= _token_center(token)[1] <= y1
    ]
    psm11 = [token for token in selected if token.engine_pass.endswith("psm11")]
    return sorted(psm11 or selected, key=lambda token: token.pixel_bbox[0])


def _text(tokens: list[OcrTokenObservation]) -> str:
    return " ".join(token.interpreted_text for token in tokens).strip()


def _column_for_header(
    tokens: list[OcrTokenObservation],
    grid: TableGrid,
    patterns: tuple[str, ...],
    *,
    x_range: tuple[int, int] | None = None,
) -> int | None:
    top, header_bottom = grid.horizontal_lines[:2]
    candidates = []
    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]+", "", token.interpreted_text.upper())
        matches = any(
            pattern in compact or (pattern == "OD" and compact == "0D")
            for pattern in patterns
        )
        if (
            top <= _token_center(token)[1] <= header_bottom
            and (x_range is None or x_range[0] <= _token_center(token)[0] <= x_range[1])
            and matches
        ):
            candidates.append(token)
    if not candidates:
        return None
    psm11 = [token for token in candidates if token.engine_pass.endswith("psm11")]
    candidates = psm11 or candidates
    center = _token_center(candidates[0])[0]
    for index, (left, right) in enumerate(
        zip(grid.vertical_lines, grid.vertical_lines[1:])
    ):
        if left <= center <= right:
            return index
    return None


def _plate_section_bounds(
    tokens: list[OcrTokenObservation], grid: TableGrid
) -> tuple[int, int] | None:
    top = grid.horizontal_lines[0]
    headings = [
        token
        for token in tokens
        if top - 45 <= _token_center(token)[1] <= top
        and token.interpreted_text.upper() == "ORIFICE"
    ]
    for heading in headings:
        y = _token_center(heading)[1]
        same_line = [
            token
            for token in tokens
            if token.engine_pass == heading.engine_pass
            and abs(_token_center(token)[1] - y) <= 8
        ]
        words = {token.interpreted_text.upper() for token in same_line}
        if not {"PLATE", "DIM"}.issubset(words):
            continue
        left = max(
            (line for line in grid.vertical_lines if line <= heading.pixel_bbox[0]),
            default=grid.vertical_lines[0],
        )
        design = [
            token
            for token in same_line
            if token.interpreted_text.upper() == "DESIGN"
            and token.pixel_bbox[0] > heading.pixel_bbox[0]
        ]
        right_anchor = design[0].pixel_bbox[0] if design else grid.vertical_lines[-1]
        right = max(
            (line for line in grid.vertical_lines if line <= right_anchor),
            default=grid.vertical_lines[-1],
        )
        if right > left:
            return left, right
    return None


def _source(tokens: list[OcrTokenObservation], raw: str) -> SourceEvidence | None:
    if not tokens:
        return None
    return SourceEvidence(
        page_number=tokens[0].page_number,
        raw_text=raw,
        bbox=(
            min(token.source_bbox[0] for token in tokens),
            min(token.source_bbox[1] for token in tokens),
            max(token.source_bbox[2] for token in tokens),
            max(token.source_bbox[3] for token in tokens),
        ),
        coordinate_unit=tokens[0].source_coordinate_unit,
        extraction_method="local_ocr+generic_ruled_table_binding_v1",
    )


def _missing(reason: str) -> TableFieldObservation:
    return TableFieldObservation(status=FieldStatus.NOT_DETECTED, reason=reason)


def _cell_source_bbox(
    rendered: RenderedRegion,
    bbox: tuple[int, int, int, int],
    *,
    inset: float = 0.0,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rendered.transform.pixel_bbox_to_pdf(bbox)
    applied = min(inset, (x1 - x0) * 0.15, (y1 - y0) * 0.15)
    return (x0 + applied, y0 + applied, x1 - applied, y1 - applied)


def _targeted_cell_ocr(
    document: NormalizedDocument,
    rendered: RenderedRegion,
    bbox: tuple[int, int, int, int],
    *,
    purpose: str,
    engine: TesseractLocalOcrEngine,
) -> tuple[LocalOcrResult, float]:
    """Rerender one ruled-table cell at 600 DPI without changing raw page OCR."""

    started = time.perf_counter()
    source_bbox = _cell_source_bbox(rendered, bbox, inset=1.0)
    region = DerivedDrawingRegion(
        region_id=f"{rendered.region.region_id}-table-{purpose}",
        source_group_id=rendered.region.source_group_id,
        source_filename=rendered.region.source_filename,
        page_number=rendered.region.page_number,
        source_bbox=source_bbox,
        candidate_bbox=source_bbox,
        coordinate_unit=rendered.region.coordinate_unit,
        derivation_method=f"targeted_table_{purpose}_cell_v1",
    )
    target = render_region_png(document, region, dpi=600)
    rotation = rendered.transform.rotation_degrees % 360
    if rotation:
        target = rotate_rendered_region(target, rotation)
    result = engine.recognize(target, pass_prefix=f"target.table.{purpose}.")
    result = recover_plus_minus_glyphs(
        result,
        target,
        tolerance_context=purpose == "tolerance",
    )
    marked = [
        token.model_copy(
            update={
                "normalization_rules": list(
                    dict.fromkeys(
                        [
                            *token.normalization_rules,
                            "targeted_table_cell_ocr",
                            "table_cell_border_exclusion",
                        ]
                    )
                )
            }
        )
        for token in result.tokens
    ]
    return (
        result.model_copy(update={"tokens": marked}),
        time.perf_counter() - started,
    )


def _quantity_from_cell_text(raw: str) -> int | None:
    """Parse only an isolated quantity cell after excluding its grid borders."""

    match = re.fullmatch(r"\s*[^A-Z0-9]*([0-9]+)[^A-Z0-9]*\s*", raw.upper())
    return int(match.group(1)) if match else None


def _targeted_quantity_observation(
    document: NormalizedDocument,
    rendered: RenderedRegion,
    bbox: tuple[int, int, int, int],
    base_raw: str,
    engine: TesseractLocalOcrEngine,
) -> tuple[TableFieldObservation | None, float]:
    result, elapsed = _targeted_cell_ocr(
        document, rendered, bbox, purpose="quantity", engine=engine
    )
    by_pass: dict[str, list[OcrTokenObservation]] = {}
    for token in result.tokens:
        by_pass.setdefault(token.engine_pass, []).append(token)
    readings: list[tuple[int, str, list[OcrTokenObservation]]] = []
    for tokens in by_pass.values():
        raw = _text(sorted(tokens, key=lambda token: token.pixel_bbox[0]))
        value = _quantity_from_cell_text(raw)
        if value is not None:
            readings.append((value, raw, tokens))
    values = {value for value, _, _ in readings}
    if len(values) != 1:
        return None, elapsed
    value, raw, tokens = readings[0]
    return (
        TableFieldObservation(
            value=value,
            normalized_unit=MeasurementUnit.COUNT,
            raw_text=raw,
            status=FieldStatus.LOW_CONFIDENCE,
            evidence=_source(tokens, raw),
            reason="targeted_table_cell_requires_explicit_selection",
            raw_observations=list(dict.fromkeys([base_raw, raw])),
            normalization_rules=[
                "targeted_table_cell_ocr",
                "table_cell_border_exclusion",
            ],
        ),
        elapsed,
    )


def _targeted_tolerance_observation(
    document: NormalizedDocument,
    rendered: RenderedRegion,
    bbox: tuple[int, int, int, int],
    base_raw: str,
    units: MeasurementUnit | None,
    engine: TesseractLocalOcrEngine,
):
    result, elapsed = _targeted_cell_ocr(
        document, rendered, bbox, purpose="tolerance", engine=engine
    )
    by_pass: dict[str, list[OcrTokenObservation]] = {}
    for token in result.tokens:
        by_pass.setdefault(token.engine_pass, []).append(token)
    readings = []
    for tokens in by_pass.values():
        raw = _text(sorted(tokens, key=lambda token: token.pixel_bbox[0]))
        parsed = parse_tolerance(raw, default_unit=units)
        if parsed is not None:
            readings.append((parsed, raw, tokens))
    values = {
        (parsed.plus, parsed.minus, parsed.upper_limit, parsed.lower_limit)
        for parsed, _, _ in readings
    }
    if len(values) != 1:
        return None, elapsed
    parsed, raw, tokens = readings[0]
    rules = sorted({rule for token in tokens for rule in token.normalization_rules})
    return (parsed, _source(tokens, raw), raw, base_raw, rules), elapsed


def parse_plate_schedule(
    rendered: RenderedRegion,
    ocr: LocalOcrResult,
    *,
    document: NormalizedDocument | None = None,
    ocr_engine: TesseractLocalOcrEngine | None = None,
) -> TableScheduleResult:
    grid = detect_ruled_table(rendered)
    if grid is None or len(grid.horizontal_lines) < 3:
        return TableScheduleResult(
            document_warnings=["No substantial ruled table was detected."]
        )
    tokens = ocr.tokens
    plate_section = _plate_section_bounds(tokens, grid)
    columns = {
        "tag": _column_for_header(tokens, grid, ("TAG",)),
        "quantity": _column_for_header(tokens, grid, ("QTY", "QUANTITY")),
        "outside_diameter": _column_for_header(
            tokens, grid, ("OD",), x_range=plate_section
        ),
        "thickness": _column_for_header(
            tokens, grid, ("THK", "THICK"), x_range=plate_section
        ),
        "bore_diameter": _column_for_header(
            tokens, grid, ("BORE",), x_range=plate_section
        ),
    }
    if columns["bore_diameter"] is not None:
        columns["bore_tolerance"] = columns["bore_diameter"] + 1
    else:
        columns["bore_tolerance"] = None
    quote_schedule_columns = plate_section is not None and all(
        columns[name] is not None
        for name in (
            "tag",
            "quantity",
            "outside_diameter",
            "thickness",
            "bore_diameter",
            "bore_tolerance",
        )
    )
    targeted_engine = (
        ocr_engine or TesseractLocalOcrEngine()
        if document is not None and quote_schedule_columns
        else None
    )
    targeted_seconds = 0.0

    all_text = _text(tokens)
    material_observations = []
    for token in tokens:
        value = parse_material(token.interpreted_text)
        if value is None:
            continue
        center_y = _token_center(token)[1]
        same_row = [
            item
            for item in tokens
            if item.engine_pass == token.engine_pass
            and abs(_token_center(item)[1] - center_y) <= 12
        ]
        row_words = {item.interpreted_text.upper() for item in same_row}
        if {"ORIFICE", "PLATE"}.issubset(row_words):
            material_observations.append((value, token, same_row))
    material_value = material_observations[0][0] if material_observations else None
    units_value = (
        MeasurementUnit.MILLIMETER
        if re.search(r"\bM\.?\s*M\.?\b", all_text.upper())
        else (
            MeasurementUnit.INCH
            if re.search(r"\b(?:INCH(?:ES)?|ALL DIMENSIONS IN IN)\b", all_text.upper())
            else None
        )
    )
    material = (
        TableFieldObservation(
            value=material_value,
            raw_text=material_observations[0][1].raw_text,
            status=FieldStatus.LOW_CONFIDENCE,
            evidence=_source(
                material_observations[0][2], _text(material_observations[0][2])
            ),
            reason="document_level_material_requires_row_confirmation",
        )
        if material_value
        else _missing("no_schedule_material")
    )
    units = (
        TableFieldObservation(
            value=units_value.value,
            normalized_unit=units_value,
            raw_text="document unit note",
            status=FieldStatus.LOW_CONFIDENCE,
            reason="document_level_units_require_row_confirmation",
        )
        if units_value
        else _missing("no_schedule_units")
    )

    def field_for(row_top: int, row_bottom: int, column: int | None, kind: str):
        nonlocal targeted_seconds
        if column is None or column + 1 >= len(grid.vertical_lines):
            return _missing(f"no_{kind}_column")
        cell = _cell_tokens(
            tokens,
            (
                grid.vertical_lines[column],
                row_top,
                grid.vertical_lines[column + 1],
                row_bottom,
            ),
        )
        raw = _text(cell)
        if not raw:
            return _missing(f"empty_{kind}_cell")
        if kind == "tag":
            value = raw
            unit = None
        elif kind == "quantity":
            value = parse_quantity(f"QTY {raw}")
            unit = MeasurementUnit.COUNT
        elif kind == "tolerance":
            parsed = parse_tolerance(raw, default_unit=units_value)
            value = parsed
            unit = units_value
        else:
            parsed = parse_measurement(raw, default_unit=units_value)
            value = parsed.value if parsed else None
            unit = units_value
        if value is None:
            return TableFieldObservation(
                raw_text=raw,
                status=FieldStatus.AMBIGUOUS,
                evidence=_source(cell, raw),
                reason=f"unparsed_{kind}_cell",
            )
        if kind == "tolerance":
            return value, _source(cell, raw), raw
        return TableFieldObservation(
            value=value,
            normalized_unit=unit,
            raw_text=raw,
            status=FieldStatus.LOW_CONFIDENCE,
            evidence=_source(cell, raw),
            reason="table_row_requires_explicit_selection",
            raw_observations=[raw],
        )

    candidates = []
    data_lines = grid.horizontal_lines[1:]
    for row_index, (top, bottom) in enumerate(zip(data_lines, data_lines[1:]), start=1):
        quantity_cell = None
        if columns["quantity"] is not None:
            quantity_cell = (
                grid.vertical_lines[columns["quantity"]],
                top,
                grid.vertical_lines[columns["quantity"] + 1],
                bottom,
            )
        base_quantity = field_for(top, bottom, columns["quantity"], "quantity")
        if (
            document is not None
            and quote_schedule_columns
            and quantity_cell is not None
        ):
            targeted_quantity, elapsed = _targeted_quantity_observation(
                document,
                rendered,
                quantity_cell,
                base_quantity.raw_text or "",
                targeted_engine,
            )
            targeted_seconds += elapsed
            if targeted_quantity is not None:
                base_quantity = targeted_quantity
        tolerance = field_for(top, bottom, columns["bore_tolerance"], "tolerance")
        if (
            document is not None
            and quote_schedule_columns
            and not isinstance(tolerance, tuple)
            and columns["bore_tolerance"] is not None
        ):
            tolerance_cell = (
                grid.vertical_lines[columns["bore_tolerance"]],
                top,
                grid.vertical_lines[columns["bore_tolerance"] + 1],
                bottom,
            )
            targeted_tolerance, elapsed = _targeted_tolerance_observation(
                document,
                rendered,
                tolerance_cell,
                tolerance.raw_text or "",
                units_value,
                targeted_engine,
            )
            targeted_seconds += elapsed
            if targeted_tolerance is not None:
                tolerance = targeted_tolerance
        if isinstance(tolerance, tuple):
            parsed, source, raw = tolerance[:3]
            if len(tolerance) == 5:
                base_raw = [tolerance[3]]
                rules = tolerance[4]
            else:
                base_raw = []
                rules = []
            observations = list(dict.fromkeys([*base_raw, raw]))
            plus = (
                TableFieldObservation(
                    value=parsed.plus,
                    normalized_unit=parsed.unit,
                    raw_text=raw,
                    status=FieldStatus.LOW_CONFIDENCE,
                    evidence=source,
                    reason="table_row_requires_explicit_selection",
                    raw_observations=observations,
                    normalization_rules=rules,
                )
                if parsed.plus is not None
                else _missing("tolerance_plus_not_present")
            )
            minus = (
                TableFieldObservation(
                    value=parsed.minus,
                    normalized_unit=parsed.unit,
                    raw_text=raw,
                    status=FieldStatus.LOW_CONFIDENCE,
                    evidence=source,
                    reason="table_row_requires_explicit_selection",
                    raw_observations=observations,
                    normalization_rules=rules,
                )
                if parsed.minus is not None
                else _missing("tolerance_minus_not_present")
            )
        else:
            plus = minus = tolerance
        candidates.append(
            TablePlateCandidate(
                row_index=row_index,
                tag=field_for(top, bottom, columns["tag"], "tag"),
                quantity=base_quantity,
                outside_diameter=field_for(
                    top, bottom, columns["outside_diameter"], "outside_diameter"
                ),
                thickness=field_for(top, bottom, columns["thickness"], "thickness"),
                bore_diameter=field_for(
                    top, bottom, columns["bore_diameter"], "bore_diameter"
                ),
                bore_tolerance_plus=plus,
                bore_tolerance_minus=minus,
                material=material,
                global_units=units,
            )
        )
    return TableScheduleResult(
        grid=grid,
        candidates=candidates,
        document_warnings=[
            "Multiple schedule rows require explicit row selection; no quote candidate was created."
        ],
        quote_candidate_created=False,
        targeted_ocr_seconds=targeted_seconds,
    )
