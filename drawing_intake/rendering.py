from __future__ import annotations

import io
import math
import time

import pypdfium2 as pdfium
from PIL import Image
from pydantic import ConfigDict, Field

from .documents import DocumentKind, NormalizedDocument
from .models import CoordinateUnit, StrictModel
from .regions import DerivedDrawingRegion


class RegionCoordinateTransform(StrictModel):
    pdf_bbox: tuple[float, float, float, float]
    pixel_width: int = Field(gt=0)
    pixel_height: int = Field(gt=0)
    points_per_pixel_x: float = Field(gt=0)
    points_per_pixel_y: float = Field(gt=0)
    rotation_degrees: int = 0
    original_pixel_width: int | None = None
    original_pixel_height: int | None = None

    def _to_original_pixel(self, x: float, y: float) -> tuple[float, float]:
        angle = self.rotation_degrees % 360
        width = self.original_pixel_width or self.pixel_width
        height = self.original_pixel_height or self.pixel_height
        if angle == 90:
            return width - y, x
        if angle == 180:
            return width - x, height - y
        if angle == 270:
            return y, height - x
        return x, y

    def pixel_bbox_to_pdf(
        self, bbox: tuple[int, int, int, int]
    ) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = bbox
        corners = [
            self._to_original_pixel(x, y)
            for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
        ]
        x0 = min(point[0] for point in corners)
        y0 = min(point[1] for point in corners)
        x1 = max(point[0] for point in corners)
        y1 = max(point[1] for point in corners)
        pdf_x0, pdf_y0, _, _ = self.pdf_bbox
        return (
            pdf_x0 + x0 * self.points_per_pixel_x,
            pdf_y0 + y0 * self.points_per_pixel_y,
            pdf_x0 + x1 * self.points_per_pixel_x,
            pdf_y0 + y1 * self.points_per_pixel_y,
        )


class RenderedRegion(StrictModel):
    model_config = ConfigDict(
        extra="forbid", use_enum_values=True, arbitrary_types_allowed=True
    )

    region: DerivedDrawingRegion
    dpi: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_unit: CoordinateUnit = CoordinateUnit.PIXEL
    transform: RegionCoordinateTransform
    png_size_bytes: int = Field(ge=0)
    uncompressed_grayscale_bytes: int = Field(ge=0)
    render_seconds: float = Field(ge=0)
    png_bytes: bytes = Field(exclude=True, repr=False)


def render_region_png(
    document: NormalizedDocument,
    region: DerivedDrawingRegion,
    *,
    dpi: int = 300,
) -> RenderedRegion:
    """Render one selected region in memory and preserve its PDF coordinate mapping."""

    if dpi <= 0:
        raise ValueError("dpi must be positive")
    if not 1 <= region.page_number <= len(document.pages):
        raise IndexError("region page is outside the document")
    x0, y0, x1, y1 = region.source_bbox
    if x1 <= x0 or y1 <= y0:
        raise ValueError("region bbox must have positive width and height")

    started = time.perf_counter()
    if document.kind == DocumentKind.PDF:
        pdf = pdfium.PdfDocument(document.source_bytes)
        try:
            page = pdf[region.page_number - 1]
            try:
                page_width, page_height = page.get_size()
                crop = (x0, page_height - y1, page_width - x1, y0)
                image = page.render(
                    scale=dpi / 72.0,
                    crop=crop,
                    grayscale=True,
                    optimize_mode="print",
                ).to_pil()
            finally:
                page.close()
        finally:
            pdf.close()
    else:
        with Image.open(io.BytesIO(document.source_bytes)) as source:
            image = source.convert("L").crop(
                (round(x0), round(y0), round(x1), round(y1))
            )
            # A raster upload has no reliable PDF point scale. Treat its native
            # pixels as a 96-DPI observation and make the requested OCR DPI an
            # explicit, deterministic resampling target. This is deliberately
            # resolution enhancement only; no thresholding or content repair is
            # applied here, and the inverse transform continues to reference the
            # original source pixels.
            scale = dpi / 96.0
            if not math.isclose(scale, 1.0, rel_tol=0.0, abs_tol=1e-9):
                image = image.resize(
                    (
                        max(1, round(image.width * scale)),
                        max(1, round(image.height * scale)),
                    ),
                    Image.Resampling.LANCZOS,
                )

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    png_bytes = output.getvalue()
    width, height = image.size
    transform = RegionCoordinateTransform(
        pdf_bbox=region.source_bbox,
        pixel_width=width,
        pixel_height=height,
        points_per_pixel_x=(x1 - x0) / width,
        points_per_pixel_y=(y1 - y0) / height,
    )
    return RenderedRegion(
        region=region,
        dpi=dpi,
        width=width,
        height=height,
        transform=transform,
        png_size_bytes=len(png_bytes),
        uncompressed_grayscale_bytes=width * height,
        render_seconds=time.perf_counter() - started,
        png_bytes=png_bytes,
    )


def rotate_rendered_region(
    rendered: RenderedRegion, rotation_degrees: int
) -> RenderedRegion:
    """Rotate pixels locally while retaining inverse source-coordinate mapping."""

    angle = rotation_degrees % 360
    if angle not in {0, 90, 180, 270}:
        raise ValueError("rotation must be a right angle")
    if angle == 0:
        return rendered
    image = Image.open(io.BytesIO(rendered.png_bytes)).rotate(angle, expand=True)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    png = output.getvalue()
    width, height = image.size
    return rendered.model_copy(
        update={
            "width": width,
            "height": height,
            "png_bytes": png,
            "png_size_bytes": len(png),
            "uncompressed_grayscale_bytes": width * height,
            "transform": rendered.transform.model_copy(
                update={
                    "pixel_width": width,
                    "pixel_height": height,
                    "rotation_degrees": angle,
                    "original_pixel_width": rendered.width,
                    "original_pixel_height": rendered.height,
                }
            ),
        }
    )
