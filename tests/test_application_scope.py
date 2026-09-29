from dataclasses import replace
from io import StringIO
import json
import pytest
import ezdxf
from reportlab.pdfgen.canvas import Canvas
from manufacturing_context import PlateApplication, DrawingState, STATUS_LABELS
from manufacturing_drawing import DrawingMetadata
from manufacturing_files import generate_job_package, pdf_bytes, dxf_bytes
from plate_geometry import PlateSpec, build_plate_geometry, manufacturing_record
from prototype_manufacturing import sample_spec
from section_geometry import build_section_geometry


@pytest.mark.parametrize("application", list(PlateApplication))
def test_application_needs_no_metering_inputs_and_activates_no_rules(
    application, tmp_path
):
    spec = replace(sample_spec(), application=application)
    g = build_plate_geometry(spec)
    package = generate_job_package(g, tmp_path)
    record = json.loads(package["json"])
    assert record["specification"]["application"] == application
    assert record["application_context"]["active_metering_rule_sets"] == []
    assert record["application_context"]["metering_validation"] == (
        "NOT IMPLEMENTED"
        if application == PlateApplication.METERING
        else "NOT APPLICABLE"
    )
    assert g.segments == build_plate_geometry(sample_spec()).segments
    assert package["dxf"] == dxf_bytes(build_plate_geometry(sample_spec()))
    assert build_section_geometry(spec).status == "NOT SPECIFIED - HOLD"
    assert spec.bore_tolerance is None
    assert package == generate_job_package(g, tmp_path)


def test_adapter_and_invalid_classification():
    config = dict(
        paddle_dia=5,
        bore_dia=1.548,
        handle_width=2,
        handle_length_from_bore=10.5,
        material="304",
        thickness=0.125,
    )
    assert (
        PlateSpec.from_configuration(config).application
        == PlateApplication.RESTRICTION_GENERAL
    )
    assert (
        PlateSpec.from_configuration(dict(config, application="metering")).application
        == PlateApplication.METERING
    )
    with pytest.raises(ValueError):
        PlateSpec.from_configuration(dict(config, application="unsupported"))


@pytest.mark.parametrize(
    "state", [DrawingState.PROTOTYPE, DrawingState.CUSTOMER_CONFIRMATION]
)
def test_explicit_state_pdf_json_match_without_transition(state, tmp_path, monkeypatch):
    labels = []
    original = Canvas.drawCentredString

    def capture(self, x, y, label, *a, **kw):
        labels.append(label)
        return original(self, x, y, label, *a, **kw)

    monkeypatch.setattr(Canvas, "drawCentredString", capture)
    metadata = DrawingMetadata(state=state)
    g = build_plate_geometry(sample_spec())
    package = generate_job_package(g, tmp_path, metadata=metadata)
    record = json.loads(package["json"])
    assert record["drawing"]["state"] == state
    assert record["status"] == STATUS_LABELS[state]
    assert STATUS_LABELS[state] in labels
    assert "NOT RELEASED FOR MANUFACTURE" in record["status"]
    assert metadata.state == state
    assert package == generate_job_package(g, tmp_path, metadata=metadata)


def test_release_reserved_and_cannot_masquerade_as_released(tmp_path):
    assert STATUS_LABELS[DrawingState.RELEASED] == "RELEASED FOR MANUFACTURE"
    g = build_plate_geometry(sample_spec())
    with pytest.raises(ValueError, match="release is not implemented"):
        generate_job_package(
            g, tmp_path / "bad", metadata=DrawingMetadata(state=DrawingState.RELEASED)
        )
    assert not (tmp_path / "bad").exists()
    with pytest.raises(ValueError):
        DrawingMetadata(state="approved")


def test_frozen_section_spec_cannot_be_overridden_only_on_pdf(tmp_path):
    with pytest.raises(ValueError, match="freeze section options"):
        generate_job_package(
            build_plate_geometry(sample_spec()),
            tmp_path / "bad",
            metadata=DrawingMetadata(flow_orientation="left-to-right"),
        )
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("enabled", [None, False, True])
def test_flow_is_not_forced_on_general_plate(enabled, monkeypatch):
    labels = []
    monkeypatch.setattr(
        Canvas, "drawString", lambda self, x, y, s, *a, **kw: labels.append(s)
    )
    pdf_bytes(build_plate_geometry(replace(sample_spec(), chamfer=enabled)))
    assert ("FLOW: HOLD" in labels) == (enabled is True)
    assert "FLOW" not in labels


def test_centreline_description_and_no_invented_requirements(monkeypatch):
    labels = []
    for method in ("drawString", "drawCentredString"):
        monkeypatch.setattr(
            Canvas, method, lambda self, x, y, s, *a, **kw: labels.append(s)
        )
    pdf_bytes(build_plate_geometry(sample_spec()))
    joined = "\n".join(labels)
    assert "10.500 C/L TO HANDLE END" in labels
    assert "ASME Y14.5-2018" in labels
    assert "APPLICATION: RESTRICTION / GENERAL" in labels
    assert "Ø1.548" in labels and "Ø5.000" in labels
    for forbidden in (
        "OVERALL",
        "1.423",
        "API",
        "AGA",
        "ISO 5167",
        "DATUM",
        "304L",
        "ASTM",
        "BREAK ALL EDGES",
        "POSITION",
        "FLATNESS",
    ):
        assert forbidden not in joined
