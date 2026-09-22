import json
from pathlib import Path
from unittest.mock import patch

import pytest

import drawing_intake.configurator_integration as integration
from drawing_intake.configurator_integration import DrawingProcessingBusyError
from drawing_intake.owner_acceptance import (
    AcceptanceEventKind,
    feedback_json,
    record_event,
    record_field_change,
    start_owner_acceptance_run,
    summarize_owner_acceptance,
    update_run,
)


def test_owner_feedback_is_privacy_minimized_and_metrics_remain_separate():
    run = start_owner_acceptance_run(
        upload_media_type="application/pdf",
        upload_bytes=12345,
        page_count=2,
    )
    run = record_event(run, AcceptanceEventKind.ANALYZE_DRAWING)
    run = record_event(run, AcceptanceEventKind.SELECT_CANDIDATE)
    run = record_event(run, AcceptanceEventKind.APPLY_VALUES)
    run = update_run(
        run,
        candidate_count=8,
        inspection_seconds=2.5,
        recognition_seconds=1.25,
        auto_populated_fields=["bore_dia", "paddle_dia"],
        current_missing_fields=["handle_width"],
    )
    run = record_field_change(
        run,
        canonical_field="bore_dia",
        previous_origin="drawing",
        previous_value_present=True,
    )
    run = record_field_change(
        run,
        canonical_field="handle_width",
        previous_origin=None,
        previous_value_present=False,
    )
    run = record_event(run, AcceptanceEventKind.CONFIRM_CONFIGURATION)
    run = update_run(run, current_missing_fields=[], confirmation_current=True)

    summary = summarize_owner_acceptance(
        run, optional_owner_notes="Selection wording was clear."
    )
    assert summary.explicit_app_clicks == 3
    assert summary.drawing_upload_and_selection_actions == 3
    assert summary.customer_actions == 6
    assert summary.distinct_auto_populated_fields == 2
    assert summary.distinct_manual_field_entries == 1
    assert summary.distinct_corrected_fields == 1
    assert summary.page_transitions == 0
    assert summary.processing_wait_seconds == 3.75
    assert summary.confirmation_current is True

    exported = json.loads(feedback_json(summary))
    assert exported["optional_owner_notes"] == "Selection wording was clear."
    serialized = json.dumps(exported).lower()
    for prohibited in (
        "filename",
        "sha256",
        "raw_text",
        "source_bbox",
        "drawing_number",
        "customer_id",
    ):
        assert prohibited not in serialized


def test_field_entry_and_clicks_are_not_conflated():
    run = start_owner_acceptance_run(
        upload_media_type="image/png",
        upload_bytes=500,
        page_count=1,
    )
    run = record_event(run, AcceptanceEventKind.ANALYZE_DRAWING)
    run = record_field_change(
        run,
        canonical_field="bore_dia",
        previous_origin=None,
        previous_value_present=False,
    )
    summary = summarize_owner_acceptance(run)
    assert summary.explicit_app_clicks == 1
    assert summary.customer_actions == 2
    assert summary.distinct_manual_field_entries == 1


def test_drawing_processing_fails_busy_instead_of_starting_second_worker(
    monkeypatch,
):
    class AlreadyBusy:
        def acquire(self, *, blocking):
            assert blocking is False
            return False

        def release(self):
            raise AssertionError("an unacquired guard must not be released")

    monkeypatch.setattr(integration, "_DRAWING_PROCESSING_LOCK", AlreadyBusy())
    with pytest.raises(DrawingProcessingBusyError, match="Another drawing"):
        integration._run_with_timeout("inspect", (), timeout_seconds=5)


def test_phase1h_container_excludes_private_corpus_and_installs_local_ocr():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    dockerignore = (root / ".dockerignore").read_text()
    assert "tesseract-ocr" in dockerfile
    assert "tesseract-ocr-eng" in dockerfile
    assert "drawing_corpus/private" in dockerignore
    assert "USER appuser" in dockerfile


def test_owner_acceptance_environment_disables_manual_checkout(monkeypatch):
    from streamlit.testing.v1 import AppTest

    import auth

    class Response:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

        def raise_for_status(self):
            return None

    active_config = {
        "materials": ["304"],
        "thicknesses_by_material": {"304": [0.125]},
        "lead_times_days": [14],
        "default_lead_time_days": 14,
        "tolerance_options_in": [0.005],
        "max_paddle_dia_in": 48.0,
        "max_bore_dia_in": 19.0,
        "max_handle_label_chars": 40,
    }
    price = {
        "unit_price": 100.0,
        "total_price": 100.0,
        "area_sq_in": 10.0,
        "estimated_total_weight_lb": 5.0,
        "estimated_package_in": {"length": 10, "width": 10, "height": 2},
        "configuration_id": "owner-test",
        "pricing_config_version": "test",
    }
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    with patch("requests.get", return_value=Response(active_config)), patch(
        "requests.post", return_value=Response(price)
    ):
        app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "pages" / "1_Quote.py"),
            default_timeout=20,
        ).run()

    assert not app.exception
    checkout = next(
        button for button in app.button if button.label == "Continue to secure checkout"
    )
    assert checkout.disabled is True
    assert any(
        "controlled owner-acceptance" in caption.value for caption in app.caption
    )
