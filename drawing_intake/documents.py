from __future__ import annotations

import hashlib
import io
from enum import Enum
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image
from pydantic import ConfigDict, Field

from .models import CoordinateUnit, StrictModel


class DocumentKind(str, Enum):
    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"


class PageContentKind(str, Enum):
    NATIVE_TEXT = "native_text"
    IMAGE_ONLY = "image_only"
    EMPTY_OR_VECTOR_ONLY = "empty_or_vector_only"


class PageOrientation(str, Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"
    SQUARE = "square"


class TextBlock(StrictModel):
    text: str
    bbox: tuple[float, float, float, float]
    coordinate_unit: CoordinateUnit


class VectorProfileHint(StrictModel):
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    coordinate_unit: CoordinateUnit = CoordinateUnit.PDF_POINT


class NormalizedPage(StrictModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    coordinate_unit: CoordinateUnit
    rotation_degrees: int
    orientation: PageOrientation
    content_kind: PageContentKind
    text_blocks: list[TextBlock] = Field(default_factory=list)
    vector_profile_hints: list[VectorProfileHint] = Field(default_factory=list)
    image_count: int = Field(default=0, ge=0)

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.text_blocks)


class NormalizedDocument(StrictModel):
    model_config = ConfigDict(
        extra="forbid", use_enum_values=True, arbitrary_types_allowed=True
    )

    filename: str
    media_type: str
    kind: DocumentKind
    sha256: str
    pages: list[NormalizedPage]
    metadata: dict[str, str] = Field(default_factory=dict)
    source_bytes: bytes = Field(exclude=True, repr=False)

    @property
    def has_text_layer(self) -> bool:
        return any(
            page.content_kind == PageContentKind.NATIVE_TEXT for page in self.pages
        )


class DocumentNormalizationError(ValueError):
    pass


def _orientation(width: float, height: float) -> PageOrientation:
    if abs(width - height) < 1e-6:
        return PageOrientation.SQUARE
    return PageOrientation.LANDSCAPE if width > height else PageOrientation.PORTRAIT


def _group_words_into_lines(words: list[dict]) -> list[TextBlock]:
    if not words:
        return []

    sorted_words = sorted(
        words, key=lambda word: (round(float(word["top"]), 1), float(word["x0"]))
    )
    lines: list[list[dict]] = []
    for word in sorted_words:
        if not lines or abs(float(word["top"]) - float(lines[-1][0]["top"])) > 3.0:
            lines.append([word])
        else:
            lines[-1].append(word)

    blocks: list[TextBlock] = []
    for line in lines:
        ordered = sorted(line, key=lambda word: float(word["x0"]))
        text = " ".join(str(word.get("text") or "").strip() for word in ordered).strip()
        if not text:
            continue
        blocks.append(
            TextBlock(
                text=text,
                bbox=(
                    min(float(word["x0"]) for word in ordered),
                    min(float(word["top"]) for word in ordered),
                    max(float(word["x1"]) for word in ordered),
                    max(float(word["bottom"]) for word in ordered),
                ),
                coordinate_unit=CoordinateUnit.PDF_POINT,
            )
        )
    return blocks


def _extract_vector_profile_hints(page) -> list[VectorProfileHint]:
    """Keep generic circular-profile hints without retaining full vector content."""

    page_minimum = min(float(page.width), float(page.height))
    minimum_size = page_minimum * 0.035
    maximum_size = page_minimum * 0.25
    hints: list[VectorProfileHint] = []
    for curve in page.curves:
        width = float(curve.get("width") or 0.0)
        height = float(curve.get("height") or 0.0)
        if not minimum_size <= width <= maximum_size:
            continue
        if not minimum_size <= height <= maximum_size:
            continue
        if not 0.8 <= width / height <= 1.2:
            continue
        if not curve.get("stroke", True):
            continue
        if len(curve.get("path") or []) < 4:
            continue
        x0 = float(curve["x0"])
        x1 = float(curve["x1"])
        top = float(curve["top"])
        bottom = float(curve["bottom"])
        hints.append(
            VectorProfileHint(
                bbox=(x0, top, x1, bottom),
                center=((x0 + x1) / 2.0, (top + bottom) / 2.0),
                width=width,
                height=height,
            )
        )
    return hints


def _normalize_pdf(data: bytes, filename: str, media_type: str) -> NormalizedDocument:
    pages: list[NormalizedPage] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                blocks = _group_words_into_lines(words)
                image_count = len(page.images or [])
                if blocks:
                    content_kind = PageContentKind.NATIVE_TEXT
                elif image_count:
                    content_kind = PageContentKind.IMAGE_ONLY
                else:
                    content_kind = PageContentKind.EMPTY_OR_VECTOR_ONLY
                width = float(page.width)
                height = float(page.height)
                pages.append(
                    NormalizedPage(
                        page_number=page_number,
                        width=width,
                        height=height,
                        coordinate_unit=CoordinateUnit.PDF_POINT,
                        rotation_degrees=int(page.rotation or 0) % 360,
                        orientation=_orientation(width, height),
                        content_kind=content_kind,
                        text_blocks=blocks,
                        vector_profile_hints=_extract_vector_profile_hints(page),
                        image_count=image_count,
                    )
                )
            metadata = {
                str(key): str(value)
                for key, value in (pdf.metadata or {}).items()
                if value is not None
            }
    except Exception as exc:
        raise DocumentNormalizationError(
            f"Could not read PDF: {type(exc).__name__}"
        ) from exc

    if not pages:
        raise DocumentNormalizationError("PDF contains no pages")
    return NormalizedDocument(
        filename=filename,
        media_type=media_type,
        kind=DocumentKind.PDF,
        sha256=hashlib.sha256(data).hexdigest(),
        pages=pages,
        metadata=metadata,
        source_bytes=data,
    )


def _normalize_image(
    data: bytes,
    filename: str,
    media_type: str,
    kind: DocumentKind,
) -> NormalizedDocument:
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            exif_orientation = str(image.getexif().get(274, ""))
    except Exception as exc:
        raise DocumentNormalizationError(
            f"Could not read image: {type(exc).__name__}"
        ) from exc

    metadata = {"exif_orientation": exif_orientation} if exif_orientation else {}
    return NormalizedDocument(
        filename=filename,
        media_type=media_type,
        kind=kind,
        sha256=hashlib.sha256(data).hexdigest(),
        pages=[
            NormalizedPage(
                page_number=1,
                width=float(width),
                height=float(height),
                coordinate_unit=CoordinateUnit.PIXEL,
                rotation_degrees=0,
                orientation=_orientation(float(width), float(height)),
                content_kind=PageContentKind.IMAGE_ONLY,
                image_count=1,
            )
        ],
        metadata=metadata,
        source_bytes=data,
    )


def normalize_document(
    data: bytes,
    filename: str,
    media_type: str | None = None,
) -> NormalizedDocument:
    """Normalize metadata/text in memory; this function never persists an upload."""

    if not data:
        raise DocumentNormalizationError("document is empty")
    suffix = Path(filename).suffix.lower()
    detected_media_type = (media_type or "").lower().split(";", 1)[0].strip()

    if detected_media_type == "application/pdf" or suffix == ".pdf":
        return _normalize_pdf(data, filename, "application/pdf")
    if detected_media_type == "image/png" or suffix == ".png":
        return _normalize_image(data, filename, "image/png", DocumentKind.PNG)
    if detected_media_type in {"image/jpeg", "image/jpg"} or suffix in {
        ".jpg",
        ".jpeg",
    }:
        return _normalize_image(data, filename, "image/jpeg", DocumentKind.JPEG)
    raise DocumentNormalizationError("supported types are PDF, PNG, JPG, and JPEG")


def render_page_png(
    document: NormalizedDocument,
    page_number: int,
    *,
    dpi: int = 300,
) -> bytes:
    """Render on demand for a vision provider without persisting an intermediate image."""

    if not 1 <= page_number <= len(document.pages):
        raise IndexError("page_number is outside the document")
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    output = io.BytesIO()
    if document.kind == DocumentKind.PDF:
        pdf = pdfium.PdfDocument(document.source_bytes)
        try:
            page = pdf[page_number - 1]
            try:
                image = page.render(scale=dpi / 72.0).to_pil()
                image.save(output, format="PNG")
            finally:
                page.close()
        finally:
            pdf.close()
        return output.getvalue()

    with Image.open(io.BytesIO(document.source_bytes)) as image:
        image.save(output, format="PNG")
    return output.getvalue()
