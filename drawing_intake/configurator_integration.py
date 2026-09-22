from __future__ import annotations

import hashlib
import io
import math
import multiprocessing
import os
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError
from pydantic import Field

from pricing_engine import QuoteInputs

from .assisted_intake import (
    ProcessedAssistedUpload,
    inspect_assisted_upload,
    select_assisted_candidate,
)
from .assisted_quote import (
    AssistedQuoteSession,
    CanonicalFieldValue,
    CanonicalFormAvailability,
    ConfigurationValueOrigin,
    PricingHandoffPreview,
    build_pricing_handoff_preview,
    canonical_required_fields,
    review_assisted_quote,
    set_customer_value,
)
from .models import ScalarValue, StrictModel


class DrawingUploadValidationError(ValueError):
    pass


class DrawingProcessingTimeoutError(TimeoutError):
    pass


class DrawingProcessingError(RuntimeError):
    pass


class DrawingProcessingBusyError(DrawingProcessingError):
    pass


class FormValueOrigin(str, Enum):
    DEFAULT = "default"
    DRAWING = "drawing"
    CUSTOMER = "customer"


class DrawingUploadLimits(StrictModel):
    max_file_bytes: int = Field(default=15 * 1024 * 1024, ge=1024)
    max_pdf_pages: int = Field(default=10, ge=1, le=50)
    max_image_dimension_px: int = Field(default=16000, ge=1000, le=50000)
    max_total_pixels: int = Field(default=80_000_000, ge=1_000_000)
    classification_dpi: int = Field(default=150, ge=72, le=300)
    processing_timeout_seconds: int = Field(default=90, ge=5, le=180)


@dataclass(frozen=True)
class ValidatedDrawingUpload:
    data: bytes
    filename: str
    media_type: str
    sha256: str
    page_count: int


class FormMergeConflict(StrictModel):
    canonical_field: str
    customer_value: ScalarValue
    drawing_value: ScalarValue


class FormIntegrationResult(StrictModel):
    values: dict[str, ScalarValue | None]
    origins: dict[str, FormValueOrigin]
    session: AssistedQuoteSession
    conflicts: list[FormMergeConflict] = Field(default_factory=list)


class PricingBoundaryAcceptance(StrictModel):
    manual_quote_request: dict[str, Any]
    assisted_quote_request: dict[str, Any]
    structures_equal: bool
    pricing_invoked: bool = False
    checkout_invoked: bool = False
    order_created: bool = False


_TRUE_VALUES = {"1", "true", "yes", "on"}
_ALLOWED_MEDIA_TYPES = {"application/pdf", "image/png", "image/jpeg"}
_MEDIA_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# Streamlit handles multiple sessions in one service process. Regional OCR can
# temporarily consume hundreds of MiB, so the controlled owner-test service runs
# at most one recognition child at a time. This guard is process-local and is not
# presented as a production-grade distributed queue.
_DRAWING_PROCESSING_LOCK = threading.Lock()


def feature_flag_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE_VALUES


def parse_allowed_user_ids(value: str | None) -> frozenset[str]:
    return frozenset(item.strip() for item in (value or "").split(",") if item.strip())


def internal_user_is_allowed(
    *, enabled: bool, user_id: str | None, allowed_user_ids: frozenset[str]
) -> bool:
    return bool(enabled and user_id and user_id in allowed_user_ids)


def upload_limits_from_environment(
    environment: Mapping[str, str] | None = None,
) -> DrawingUploadLimits:
    source = environment or os.environ

    def _integer(name: str, default: int) -> int:
        raw = (source.get(name) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise DrawingUploadValidationError(f"{name} must be an integer") from exc

    defaults = DrawingUploadLimits()
    return DrawingUploadLimits(
        max_file_bytes=_integer(
            "DRAWING_ASSISTED_MAX_FILE_BYTES", defaults.max_file_bytes
        ),
        max_pdf_pages=_integer(
            "DRAWING_ASSISTED_MAX_PDF_PAGES", defaults.max_pdf_pages
        ),
        max_image_dimension_px=_integer(
            "DRAWING_ASSISTED_MAX_IMAGE_DIMENSION_PX",
            defaults.max_image_dimension_px,
        ),
        max_total_pixels=_integer(
            "DRAWING_ASSISTED_MAX_TOTAL_PIXELS", defaults.max_total_pixels
        ),
        classification_dpi=_integer(
            "DRAWING_ASSISTED_CLASSIFICATION_DPI", defaults.classification_dpi
        ),
        processing_timeout_seconds=_integer(
            "DRAWING_ASSISTED_PROCESSING_TIMEOUT_SECONDS",
            defaults.processing_timeout_seconds,
        ),
    )


def _safe_filename(filename: str) -> str:
    if not filename or "\x00" in filename:
        raise DrawingUploadValidationError("The uploaded file name is invalid.")
    normalized = filename.replace("\\", "/")
    basename = Path(normalized).name.strip()
    if not basename or len(basename) > 200:
        raise DrawingUploadValidationError("The uploaded file name is invalid.")
    return basename


def _detect_media_type(data: bytes) -> str | None:
    if data.lstrip()[:5] == b"%PDF-":
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return None


def _validate_pdf_limits(data: bytes, limits: DrawingUploadLimits) -> int:
    try:
        pdf = pdfium.PdfDocument(data)
        try:
            page_count = len(pdf)
            if page_count < 1:
                raise DrawingUploadValidationError("The PDF contains no pages.")
            if page_count > limits.max_pdf_pages:
                raise DrawingUploadValidationError(
                    f"PDFs are limited to {limits.max_pdf_pages} pages."
                )
            total_pixels = 0
            for index in range(page_count):
                page = pdf[index]
                try:
                    width_points, height_points = page.get_size()
                finally:
                    page.close()
                width_px = math.ceil(
                    float(width_points) * limits.classification_dpi / 72.0
                )
                height_px = math.ceil(
                    float(height_points) * limits.classification_dpi / 72.0
                )
                if max(width_px, height_px) > limits.max_image_dimension_px:
                    raise DrawingUploadValidationError(
                        "A PDF page exceeds the permitted render dimensions."
                    )
                total_pixels += width_px * height_px
                if total_pixels > limits.max_total_pixels:
                    raise DrawingUploadValidationError(
                        "The PDF exceeds the permitted total render area."
                    )
            return page_count
        finally:
            pdf.close()
    except DrawingUploadValidationError:
        raise
    except Exception as exc:
        raise DrawingUploadValidationError("The PDF could not be safely read.") from exc


def _validate_image_limits(
    data: bytes, expected_media_type: str, limits: DrawingUploadLimits
) -> int:
    try:
        with Image.open(io.BytesIO(data)) as image:
            actual_format = (image.format or "").upper()
            expected_format = "PNG" if expected_media_type == "image/png" else "JPEG"
            if actual_format != expected_format:
                raise DrawingUploadValidationError(
                    "The image content does not match its file type."
                )
            width, height = image.size
            if width < 1 or height < 1:
                raise DrawingUploadValidationError("The image has invalid dimensions.")
            if max(width, height) > limits.max_image_dimension_px:
                raise DrawingUploadValidationError(
                    "The image exceeds the permitted dimensions."
                )
            if width * height > limits.max_total_pixels:
                raise DrawingUploadValidationError(
                    "The image exceeds the permitted pixel count."
                )
            image.verify()
    except DrawingUploadValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DrawingUploadValidationError(
            "The image could not be safely read."
        ) from exc
    return 1


def validate_drawing_upload(
    data: bytes,
    filename: str,
    client_media_type: str | None,
    *,
    limits: DrawingUploadLimits | None = None,
) -> ValidatedDrawingUpload:
    product_limits = limits or DrawingUploadLimits()
    if not data:
        raise DrawingUploadValidationError("Choose a non-empty drawing file.")
    if len(data) > product_limits.max_file_bytes:
        maximum_mb = product_limits.max_file_bytes / (1024 * 1024)
        raise DrawingUploadValidationError(
            f"Drawing files are limited to {maximum_mb:g} MB."
        )

    safe_name = _safe_filename(filename)
    suffix_media_type = _MEDIA_BY_SUFFIX.get(Path(safe_name).suffix.lower())
    if suffix_media_type is None:
        raise DrawingUploadValidationError(
            "Supported types are PDF, PNG, JPG, and JPEG."
        )
    detected_media_type = _detect_media_type(data)
    if detected_media_type is None:
        raise DrawingUploadValidationError(
            "The file content is not a supported drawing type."
        )
    normalized_client_type = (client_media_type or "").lower().split(";", 1)[0].strip()
    if normalized_client_type and normalized_client_type not in _ALLOWED_MEDIA_TYPES:
        raise DrawingUploadValidationError("The declared file type is not supported.")
    if suffix_media_type != detected_media_type:
        raise DrawingUploadValidationError(
            "The file extension does not match the drawing content."
        )
    if normalized_client_type and normalized_client_type != detected_media_type:
        raise DrawingUploadValidationError(
            "The declared file type does not match the drawing content."
        )

    if detected_media_type == "application/pdf":
        page_count = _validate_pdf_limits(data, product_limits)
    else:
        page_count = _validate_image_limits(data, detected_media_type, product_limits)
    return ValidatedDrawingUpload(
        data=data,
        filename=safe_name,
        media_type=detected_media_type,
        sha256=hashlib.sha256(data).hexdigest(),
        page_count=page_count,
    )


def _processing_worker(connection, operation: str, arguments: tuple[Any, ...]) -> None:
    try:
        if operation == "inspect":
            upload = arguments[0]
            result = inspect_assisted_upload(
                upload.data,
                upload.filename,
                media_type=upload.media_type,
            )
        elif operation == "select":
            processed, candidate_id, availability = arguments
            result = select_assisted_candidate(
                processed,
                candidate_id,
                availability=availability,
            )
        else:
            raise ValueError("unknown drawing-processing operation")
        connection.send(("ok", result))
    except BaseException as exc:  # child process must return a sanitized failure
        connection.send(("error", type(exc).__name__, str(exc)[:240]))
    finally:
        connection.close()


def _run_with_timeout(
    operation: str,
    arguments: tuple[Any, ...],
    *,
    timeout_seconds: int,
):
    if not _DRAWING_PROCESSING_LOCK.acquire(blocking=False):
        raise DrawingProcessingBusyError(
            "Another drawing is being processed. Try again when it finishes."
        )
    try:
        return _run_isolated_process(
            operation,
            arguments,
            timeout_seconds=timeout_seconds,
        )
    finally:
        _DRAWING_PROCESSING_LOCK.release()


def _run_isolated_process(
    operation: str,
    arguments: tuple[Any, ...],
    *,
    timeout_seconds: int,
):
    available_methods = multiprocessing.get_all_start_methods()
    method = "fork" if "fork" in available_methods else "spawn"
    context = multiprocessing.get_context(method)
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=_processing_worker,
        args=(sending, operation, arguments),
        daemon=True,
    )
    process.start()
    sending.close()
    try:
        if not receiving.poll(timeout_seconds):
            process.terminate()
            process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            raise DrawingProcessingTimeoutError(
                "Drawing processing exceeded the internal time limit."
            )
        try:
            message = receiving.recv()
        except EOFError as exc:
            raise DrawingProcessingError(
                "The isolated drawing worker exited without a result."
            ) from exc
    finally:
        receiving.close()
        if process.is_alive():
            process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)

    if not message or message[0] != "ok":
        error_name = message[1] if len(message) > 1 else "DrawingProcessingError"
        raise DrawingProcessingError(f"Local drawing processing failed ({error_name}).")
    return message[1]


def inspect_validated_upload(
    upload: ValidatedDrawingUpload,
    *,
    timeout_seconds: int,
) -> ProcessedAssistedUpload:
    return _run_with_timeout("inspect", (upload,), timeout_seconds=timeout_seconds)


def recognize_selected_candidate(
    processed: ProcessedAssistedUpload,
    candidate_id: str,
    *,
    availability: CanonicalFormAvailability,
    timeout_seconds: int,
) -> AssistedQuoteSession:
    return _run_with_timeout(
        "select",
        (processed, candidate_id, availability),
        timeout_seconds=timeout_seconds,
    )


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), abs_tol=1e-9)
    return left == right


def integrate_selected_session(
    selected: AssistedQuoteSession,
    *,
    current_values: Mapping[str, ScalarValue | None],
    current_origins: Mapping[str, FormValueOrigin | str],
    availability: CanonicalFormAvailability,
) -> FormIntegrationResult:
    """Apply proposals to the real form without overwriting customer entries."""

    values = {name: current_values.get(name) for name in QuoteInputs.model_fields}
    origins = {
        name: FormValueOrigin(origin)
        for name, origin in current_origins.items()
        if name in QuoteInputs.model_fields
    }
    required = set(canonical_required_fields())
    conflicts: list[FormMergeConflict] = []

    for field in QuoteInputs.model_fields:
        existing = values.get(field)
        existing_origin = origins.get(field, FormValueOrigin.DEFAULT)
        proposal = selected.configuration.get(field)
        if existing_origin == FormValueOrigin.CUSTOMER and _present(existing):
            if proposal is not None and not _equivalent(existing, proposal.value):
                conflicts.append(
                    FormMergeConflict(
                        canonical_field=field,
                        customer_value=existing,
                        drawing_value=proposal.value,
                    )
                )
            continue
        if proposal is not None:
            values[field] = proposal.value
            origins[field] = FormValueOrigin.DRAWING
        elif field in required:
            values[field] = None
            origins.pop(field, None)
        elif field == "handle_label" and existing_origin != FormValueOrigin.CUSTOMER:
            values[field] = ""
            origins[field] = FormValueOrigin.DEFAULT

    configuration: dict[str, CanonicalFieldValue] = dict(selected.configuration)
    integrated = selected.model_copy(
        update={"configuration": configuration, "confirmation_fingerprint": None}
    )
    for field, value in values.items():
        if origins.get(field) == FormValueOrigin.CUSTOMER:
            integrated = set_customer_value(integrated, field, value)

    # Evaluate now so an active-config mismatch fails before widget state changes.
    review_assisted_quote(integrated, availability=availability)
    return FormIntegrationResult(
        values=values,
        origins=origins,
        session=integrated,
        conflicts=conflicts,
    )


def synchronize_session_from_form(
    session: AssistedQuoteSession,
    *,
    previous_values: Mapping[str, ScalarValue | None],
    current_values: Mapping[str, ScalarValue | None],
    current_origins: Mapping[str, FormValueOrigin | str],
) -> FormIntegrationResult:
    values = {name: current_values.get(name) for name in QuoteInputs.model_fields}
    origins = {
        name: FormValueOrigin(origin)
        for name, origin in current_origins.items()
        if name in QuoteInputs.model_fields
    }
    updated = session
    for field in QuoteInputs.model_fields:
        before = previous_values.get(field)
        after = values.get(field)
        if _equivalent(before, after):
            continue
        origins[field] = FormValueOrigin.CUSTOMER
        updated = set_customer_value(updated, field, after)
    return FormIntegrationResult(
        values=values,
        origins=origins,
        session=updated,
    )


def accept_pricing_boundary_without_invocation(
    session: AssistedQuoteSession,
    manual_payload: Mapping[str, Any],
    *,
    availability: CanonicalFormAvailability,
) -> PricingBoundaryAcceptance:
    manual = QuoteInputs(**dict(manual_payload)).model_dump()
    preview: PricingHandoffPreview = build_pricing_handoff_preview(
        session, availability=availability
    )
    assisted = preview.quote_request
    return PricingBoundaryAcceptance(
        manual_quote_request=manual,
        assisted_quote_request=assisted,
        structures_equal=(manual == assisted),
    )
