from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
import time

from PIL import Image, ImageOps
from pydantic import Field

from .models import CoordinateUnit, StrictModel
from .rendering import RenderedRegion


class LocalOcrDependencyError(RuntimeError):
    pass


class LocalOcrExecutionError(RuntimeError):
    pass


class OcrTokenObservation(StrictModel):
    token_id: str
    region_id: str
    page_number: int = Field(ge=1)
    raw_text: str
    normalized_text: str | None = None
    normalization_rules: list[str] = Field(default_factory=list)
    engine_confidence: float | None = None
    pixel_bbox: tuple[int, int, int, int]
    source_bbox: tuple[float, float, float, float]
    source_coordinate_unit: CoordinateUnit = CoordinateUnit.PDF_POINT
    engine: str
    engine_pass: str
    line_key: str

    @property
    def interpreted_text(self) -> str:
        return self.normalized_text or self.raw_text


class LocalOcrResult(StrictModel):
    engine: str
    engine_version: str
    region_id: str
    dpi: int
    page_segmentation_modes: list[int]
    tokens: list[OcrTokenObservation]
    ocr_seconds: float = Field(ge=0)


class TesseractLocalOcrEngine:
    """Local-only Tesseract TSV adapter with token-level provenance."""

    def __init__(
        self,
        *,
        executable: str = "tesseract",
        language: str = "eng",
        page_segmentation_modes: tuple[int, ...] = (6, 11),
    ) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise LocalOcrDependencyError(
                "Tesseract executable is required for local OCR but was not found."
            )
        if not page_segmentation_modes:
            raise ValueError("at least one page segmentation mode is required")
        self.executable = resolved
        self.language = language
        self.page_segmentation_modes = page_segmentation_modes
        self.version = self._read_version()

    def _read_version(self) -> str:
        completed = subprocess.run(
            [self.executable, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
            timeout=10,
        )
        first_line = completed.stdout.splitlines()[0] if completed.stdout else "unknown"
        return first_line.strip()

    def recognize(
        self, rendered: RenderedRegion, *, pass_prefix: str = ""
    ) -> LocalOcrResult:
        started = time.perf_counter()
        tokens: list[OcrTokenObservation] = []
        for psm in self.page_segmentation_modes:
            pass_name = f"{pass_prefix}psm{psm}"
            completed = subprocess.run(
                [
                    self.executable,
                    "stdin",
                    "stdout",
                    "--dpi",
                    str(rendered.dpi),
                    "--psm",
                    str(psm),
                    "-l",
                    self.language,
                    "tsv",
                ],
                input=rendered.png_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=60,
            )
            if completed.returncode != 0:
                message = completed.stderr.decode("utf-8", errors="replace").strip()
                raise LocalOcrExecutionError(
                    f"Local Tesseract OCR failed for {pass_name}: {message[:240]}"
                )
            tokens.extend(
                self._parse_tsv(
                    completed.stdout.decode("utf-8", errors="replace"),
                    rendered,
                    pass_name,
                )
            )
        return LocalOcrResult(
            engine="tesseract_tsv_local",
            engine_version=self.version,
            region_id=rendered.region.region_id,
            dpi=rendered.dpi,
            page_segmentation_modes=list(self.page_segmentation_modes),
            tokens=tokens,
            ocr_seconds=time.perf_counter() - started,
        )

    @staticmethod
    def _parse_tsv(
        raw_tsv: str,
        rendered: RenderedRegion,
        pass_name: str,
    ) -> list[OcrTokenObservation]:
        observations: list[OcrTokenObservation] = []
        reader = csv.DictReader(io.StringIO(raw_tsv), delimiter="\t")
        for row_index, row in enumerate(reader, start=1):
            raw_text = (row.get("text") or "").strip()
            if not raw_text:
                continue
            try:
                left = int(row["left"])
                top = int(row["top"])
                width = int(row["width"])
                height = int(row["height"])
                confidence_value = float(row["conf"])
            except (KeyError, TypeError, ValueError) as exc:
                raise LocalOcrExecutionError("Malformed Tesseract TSV output") from exc
            pixel_bbox = (left, top, left + width, top + height)
            confidence = confidence_value if confidence_value >= 0 else None
            line_key = ":".join(
                (
                    pass_name,
                    row.get("block_num") or "0",
                    row.get("par_num") or "0",
                    row.get("line_num") or "0",
                )
            )
            observations.append(
                OcrTokenObservation(
                    token_id=f"{rendered.region.region_id}:{pass_name}:{row_index}",
                    region_id=rendered.region.region_id,
                    page_number=rendered.region.page_number,
                    raw_text=raw_text,
                    engine_confidence=confidence,
                    pixel_bbox=pixel_bbox,
                    source_bbox=rendered.transform.pixel_bbox_to_pdf(pixel_bbox),
                    source_coordinate_unit=rendered.region.coordinate_unit,
                    engine="tesseract_tsv_local",
                    engine_pass=pass_name,
                    line_key=line_key,
                )
            )
        return observations


def recover_plus_minus_glyphs(
    result: LocalOcrResult,
    rendered: RenderedRegion,
    *,
    tolerance_context: bool = False,
) -> LocalOcrResult:
    """Recover ± only when a tolerance-context glyph has two ink crossbars.

    Tesseract commonly emits the outlined CAD ``±`` glyph as ``+`` or ``£``.
    This rule inspects the original token pixels and requires two separated,
    substantial horizontal bands.  A plain plus therefore remains a plus.
    ``tolerance_context`` is reserved for a cell already bound to a tolerance
    column; ordinary page OCR must still supply a BORE/TOL text context.
    """

    image = Image.open(io.BytesIO(rendered.png_bytes)).convert("L")
    output: list[OcrTokenObservation] = []
    tokens_by_pass: dict[str, list[OcrTokenObservation]] = {}
    for token in result.tokens:
        tokens_by_pass.setdefault(token.engine_pass, []).append(token)

    for token in result.tokens:
        raw = token.raw_text.strip()
        glyph_with_value = re.match(r"^[+#£](?=(?:\d|\.))", raw)
        if raw not in {"+", "£"} and glyph_with_value is None:
            output.append(token)
            continue
        context_tokens = tokens_by_pass[token.engine_pass]
        context = " ".join(item.raw_text.upper() for item in context_tokens)
        if not tolerance_context and "BORE" not in context and "TOL" not in context:
            output.append(token)
            continue
        x0, y0, x1, y1 = token.pixel_bbox
        if glyph_with_value is not None:
            x1 = min(x1, x0 + max(8, int((x1 - x0) * 0.36)))
        crop = ImageOps.autocontrast(image.crop((x0, y0, x1, y1)))
        if crop.width < 3 or crop.height < 5:
            output.append(token)
            continue
        pixels = crop.load()
        row_ink = [
            sum(pixels[x, y] < 160 for x in range(crop.width))
            for y in range(crop.height)
        ]
        substantial = max(2, int(crop.width * 0.45))
        bands: list[list[int]] = []
        for y, count in enumerate(row_ink):
            if count < substantial:
                continue
            if bands and y == bands[-1][-1] + 1:
                bands[-1].append(y)
            else:
                bands.append([y])
        separated = [sum(band) / len(band) for band in bands]
        has_two_crossbars = any(
            lower - upper >= max(3, crop.height * 0.2)
            for index, upper in enumerate(separated)
            for lower in separated[index + 1 :]
        )
        if has_two_crossbars:
            output.append(
                token.model_copy(
                    update={
                        "normalized_text": (
                            "±" + raw[1:] if glyph_with_value is not None else "±"
                        ),
                        "normalization_rules": [
                            *token.normalization_rules,
                            "two_horizontal_bands_plus_minus_glyph",
                        ],
                    }
                )
            )
        else:
            output.append(token)
    return result.model_copy(update={"tokens": output})
