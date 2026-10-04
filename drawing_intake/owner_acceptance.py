from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from pydantic import Field

from .models import StrictModel


class AcceptanceEventKind(str, Enum):
    ANALYZE_DRAWING = "analyze_drawing"
    SELECT_CANDIDATE = "select_candidate"
    APPLY_VALUES = "apply_values"
    CHANGE_FIELD = "change_field"
    CONFIRM_CONFIGURATION = "confirm_configuration"
    RESET_TO_MANUAL = "reset_to_manual"


class AcceptanceEvent(StrictModel):
    kind: AcceptanceEventKind
    elapsed_seconds: float = Field(ge=0)
    canonical_field: str | None = None
    field_change: str | None = None


class OwnerAcceptanceRun(StrictModel):
    """Privacy-minimized, session-local owner acceptance record.

    This deliberately excludes filenames, file hashes, drawing contents, OCR text,
    dimensions, customer data, and source coordinates. The browser may download the
    record as JSON; the application does not persist or transmit it.
    """

    schema_version: str = "phase1h-1"
    run_id: str
    started_at_utc: datetime
    upload_media_type: str
    upload_bytes: int = Field(ge=0)
    page_count: int = Field(ge=1)
    candidate_count: int = Field(default=0, ge=0)
    inspection_seconds: float | None = Field(default=None, ge=0)
    recognition_seconds: float | None = Field(default=None, ge=0)
    auto_populated_fields: list[str] = Field(default_factory=list)
    current_missing_fields: list[str] = Field(default_factory=list)
    current_invalid_fields: list[str] = Field(default_factory=list)
    current_unsupported_fields: list[str] = Field(default_factory=list)
    corrected_fields: list[str] = Field(default_factory=list)
    manually_completed_fields: list[str] = Field(default_factory=list)
    confirmation_current: bool = False
    events: list[AcceptanceEvent] = Field(default_factory=list)


class OwnerAcceptanceSummary(StrictModel):
    schema_version: str
    run_id: str
    started_at_utc: datetime
    upload_media_type: str
    upload_bytes: int
    page_count: int
    candidate_count: int
    inspection_seconds: float | None
    recognition_seconds: float | None
    processing_wait_seconds: float
    explicit_app_clicks: int
    drawing_upload_and_selection_actions: int
    customer_actions: int
    distinct_auto_populated_fields: int
    distinct_manual_field_entries: int
    distinct_corrected_fields: int
    page_transitions: int = 0
    current_missing_fields: list[str]
    current_invalid_fields: list[str]
    current_unsupported_fields: list[str]
    confirmation_current: bool
    elapsed_seconds_to_current_state: float = Field(ge=0)
    optional_owner_notes: str = ""
    retention: str = (
        "Session memory only; downloaded by the owner on request; no drawing content."
    )


def start_owner_acceptance_run(
    *, upload_media_type: str, upload_bytes: int, page_count: int
) -> OwnerAcceptanceRun:
    return OwnerAcceptanceRun(
        run_id=str(uuid.uuid4()),
        started_at_utc=datetime.now(timezone.utc),
        upload_media_type=upload_media_type,
        upload_bytes=upload_bytes,
        page_count=page_count,
    )


def elapsed_since_start(run: OwnerAcceptanceRun) -> float:
    return max(
        0.0,
        (datetime.now(timezone.utc) - run.started_at_utc).total_seconds(),
    )


def record_event(
    run: OwnerAcceptanceRun,
    kind: AcceptanceEventKind,
    *,
    canonical_field: str | None = None,
    field_change: str | None = None,
) -> OwnerAcceptanceRun:
    event = AcceptanceEvent(
        kind=kind,
        elapsed_seconds=elapsed_since_start(run),
        canonical_field=canonical_field,
        field_change=field_change,
    )
    return run.model_copy(update={"events": [*run.events, event]})


def update_run(
    run: OwnerAcceptanceRun,
    *,
    candidate_count: int | None = None,
    inspection_seconds: float | None = None,
    recognition_seconds: float | None = None,
    auto_populated_fields: Iterable[str] | None = None,
    current_missing_fields: Iterable[str] | None = None,
    current_invalid_fields: Iterable[str] | None = None,
    current_unsupported_fields: Iterable[str] | None = None,
    confirmation_current: bool | None = None,
) -> OwnerAcceptanceRun:
    changes: dict[str, Any] = {}
    if candidate_count is not None:
        changes["candidate_count"] = candidate_count
    if inspection_seconds is not None:
        changes["inspection_seconds"] = inspection_seconds
    if recognition_seconds is not None:
        changes["recognition_seconds"] = recognition_seconds
    if auto_populated_fields is not None:
        changes["auto_populated_fields"] = sorted(set(auto_populated_fields))
    if current_missing_fields is not None:
        changes["current_missing_fields"] = sorted(set(current_missing_fields))
    if current_invalid_fields is not None:
        changes["current_invalid_fields"] = sorted(set(current_invalid_fields))
    if current_unsupported_fields is not None:
        changes["current_unsupported_fields"] = sorted(set(current_unsupported_fields))
    if confirmation_current is not None:
        changes["confirmation_current"] = confirmation_current
    return run.model_copy(update=changes)


def record_field_change(
    run: OwnerAcceptanceRun,
    *,
    canonical_field: str,
    previous_origin: str | None,
    previous_value_present: bool,
) -> OwnerAcceptanceRun:
    if previous_origin == "drawing":
        change = "correction"
        corrected = sorted({*run.corrected_fields, canonical_field})
        completed = run.manually_completed_fields
    elif not previous_value_present:
        change = "manual_entry"
        corrected = run.corrected_fields
        completed = sorted({*run.manually_completed_fields, canonical_field})
    else:
        change = "customer_edit"
        corrected = run.corrected_fields
        completed = run.manually_completed_fields
    changed = record_event(
        run,
        AcceptanceEventKind.CHANGE_FIELD,
        canonical_field=canonical_field,
        field_change=change,
    )
    return changed.model_copy(
        update={
            "corrected_fields": corrected,
            "manually_completed_fields": completed,
        }
    )


def summarize_owner_acceptance(
    run: OwnerAcceptanceRun,
    *,
    optional_owner_notes: str = "",
) -> OwnerAcceptanceSummary:
    explicit_click_kinds = {
        AcceptanceEventKind.ANALYZE_DRAWING,
        AcceptanceEventKind.APPLY_VALUES,
        AcceptanceEventKind.CONFIRM_CONFIGURATION,
        AcceptanceEventKind.RESET_TO_MANUAL,
    }
    drawing_action_kinds = {
        AcceptanceEventKind.ANALYZE_DRAWING,
        AcceptanceEventKind.SELECT_CANDIDATE,
        AcceptanceEventKind.APPLY_VALUES,
    }
    return OwnerAcceptanceSummary(
        schema_version=run.schema_version,
        run_id=run.run_id,
        started_at_utc=run.started_at_utc,
        upload_media_type=run.upload_media_type,
        upload_bytes=run.upload_bytes,
        page_count=run.page_count,
        candidate_count=run.candidate_count,
        inspection_seconds=run.inspection_seconds,
        recognition_seconds=run.recognition_seconds,
        processing_wait_seconds=round(
            (run.inspection_seconds or 0) + (run.recognition_seconds or 0), 3
        ),
        explicit_app_clicks=sum(
            event.kind in explicit_click_kinds for event in run.events
        ),
        drawing_upload_and_selection_actions=sum(
            event.kind in drawing_action_kinds for event in run.events
        ),
        customer_actions=len(run.events),
        distinct_auto_populated_fields=len(run.auto_populated_fields),
        distinct_manual_field_entries=len(run.manually_completed_fields),
        distinct_corrected_fields=len(run.corrected_fields),
        current_missing_fields=run.current_missing_fields,
        current_invalid_fields=run.current_invalid_fields,
        current_unsupported_fields=run.current_unsupported_fields,
        confirmation_current=run.confirmation_current,
        elapsed_seconds_to_current_state=round(elapsed_since_start(run), 3),
        optional_owner_notes=optional_owner_notes.strip(),
    )


def feedback_json(summary: OwnerAcceptanceSummary) -> str:
    return json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True)
