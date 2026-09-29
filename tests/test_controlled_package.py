from dataclasses import replace
import json
import pytest
import ezdxf
from reportlab.pdfgen.canvas import Canvas
from plate_geometry import build_plate_geometry, GEOMETRY_VERSION
from prototype_manufacturing import sample_spec
from manufacturing_files import generate_job_package, pdf_bytes
from manufacturing_drawing import DrawingMetadata


def geometry():
    return build_plate_geometry(replace(sample_spec(), part_identifier="PROTOTYPE-001"))


def labels_for(g, monkeypatch, metadata=None):
    labels = []
    for name in ("drawString", "drawCentredString"):
        original = getattr(Canvas, name)

        def capture(self, x, y, value, *a, _original=original, **kw):
            labels.append(value)
            return _original(self, x, y, value, *a, **kw)

        monkeypatch.setattr(Canvas, name, capture)
    pdf_bytes(g, metadata)
    return labels


def test_paired_package_reopens_as_clean_rough_blank(tmp_path):
    g = geometry()
    outputs = generate_job_package(g, tmp_path / "job")
    assert set(outputs) == {"pdf", "dxf", "json"}
    assert {p.name for p in (tmp_path / "job").iterdir()} == {
        "OP-PROTOTYPE-001.pdf",
        "OP-PROTOTYPE-001.dxf",
        "OP-PROTOTYPE-001.json",
    }
    doc = ezdxf.readfile(tmp_path / "job/OP-PROTOTYPE-001.dxf")
    audit = doc.audit()
    assert not audit.errors and not audit.fixes
    assert doc.units == 1
    outer, bore = list(doc.modelspace())
    assert outer.dxftype() == "LWPOLYLINE" and outer.closed
    assert outer.dxf.layer == "CUT_OUTER"
    assert bore.dxftype() == "CIRCLE" and bore.dxf.layer == "CUT_BORE"
    assert bore.dxf.radius * 2 == pytest.approx(1.423, rel=0, abs=1e-12)
    assert g.spec.finished_bore_diameter - bore.dxf.radius * 2 == pytest.approx(
        0.125, rel=0, abs=1e-12
    )
    for actual, expected in zip(outer.get_points("xyb"), g.outer_vertices_xyb):
        assert actual == pytest.approx(expected, rel=0, abs=1e-12)
    assert len(outer) == len(g.outer_vertices_xyb)
    assert sum(seg.radius == 0.03125 for seg in g.segments) == 4
    record = json.loads(outputs["json"])
    assert record["geometry"]["version"] == GEOMETRY_VERSION
    assert record["specification"]["part_identifier"] == "PROTOTYPE-001"
    assert "straight-handle-v1-prototype" not in outputs["json"].decode()
    assert outputs == generate_job_package(g, tmp_path / "job")


def test_finished_print_identity_and_no_unapproved_gdt(monkeypatch):
    labels = labels_for(geometry(), monkeypatch)
    for value in (
        "ORIFICE PLATE",
        "PART NO.",
        "DWG NO.",
        "PROTOTYPE-001",
        "OP-PROTOTYPE-001",
        "INCHES",
        "NTS",
        "1 OF 1",
        "ASME Y14.5-2018",
        "P3E",
        "Ø5.000",
        "Ø1.548",
        "2.000",
        "10.500 C/L TO HANDLE END",
        "4X R 0.03125",
        "0.125",
        "304 STAINLESS STEEL",
        "1",
    ):
        assert value in labels
    joined = "\n".join(labels)
    for forbidden in (
        "DATA SHEET",
        "1.423",
        "UNDERSIZE",
        "KERF",
        "DXF",
        "DATUM",
        "POSITION",
        "FLATNESS",
        "PERPENDICULARITY",
        "RUNOUT",
        "CONCENTRICITY",
        "ORIENTATION ONLY",
    ):
        assert forbidden not in joined
    # A/B are unboxed section/detail identifiers, not datum feature symbols.
    assert labels.count("A") == 2 and "SECTION A-A - NTS" in labels
    assert not any(symbol in joined for symbol in ("⌖", "⏥", "⟂", "⌭"))
    assert "UNLESS OTHERWISE SPECIFIED:" in labels
    assert all(value in labels for value in (".X", ".XX", ".XXX", "ANGLES"))


@pytest.mark.parametrize("stale", ["sample-plate.pdf", "old.svg", "stale.json"])
def test_stale_directory_rejected_without_writing(tmp_path, stale):
    (tmp_path / stale).write_text("old")
    with pytest.raises(ValueError, match="segregate"):
        generate_job_package(geometry(), tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == [stale]


def test_noncanonical_geometry_rejected(tmp_path):
    bad = replace(geometry(), corner_radius=0)
    with pytest.raises(ValueError, match="canonical"):
        generate_job_package(bad, tmp_path / "job")
    assert not (tmp_path / "job").exists()


def test_stale_record_version_rejected(tmp_path, monkeypatch):
    import manufacturing_files as files

    original = files.manufacturing_record

    def stale(g):
        record = original(g)
        record["geometry"]["version"] = "straight-handle-v1-prototype"
        return record

    monkeypatch.setattr(files, "manufacturing_record", stale)
    with pytest.raises(ValueError, match="stale geometry"):
        files.generate_job_package(geometry(), tmp_path / "job")
    assert not (tmp_path / "job").exists()


def test_explicit_note_fields_and_revisions_are_consumed(monkeypatch):
    metadata = DrawingMetadata(
        specification_revision="TEST-SPEC-R2",
        revision="TEST-R3",
        surface_finish="TEST APPROVED FACE REQUIREMENT",
        edge_finish="TEST EDGE REQUIREMENT",
        inspection="TEST INSPECTION REQUIREMENT",
        marking_method="TEST METHOD",
        marking_location="TEST LOCATION",
        tolerance_x="TEST-X",
        tolerance_xx="TEST-XX",
        tolerance_xxx="TEST-XXX",
        tolerance_angles="TEST-ANGLE",
    )
    joined = "\n".join(labels_for(geometry(), monkeypatch, metadata))
    for value in (
        "TEST-SPEC-R2",
        "TEST-R3",
        "TEST APPROVED FACE REQUIREMENT",
        "TEST EDGE REQUIREMENT",
        "TEST INSPECTION REQUIREMENT",
        "TEST METHOD",
        "TEST LOCATION",
        "TEST-X",
        "TEST-XX",
        "TEST-XXX",
        "TEST-ANGLE",
    ):
        assert value in joined


@pytest.mark.parametrize("state", [False, True])
def test_none_and_incomplete_emit_no_detail_or_assumed_flow(monkeypatch, state):
    g = build_plate_geometry(replace(geometry().spec, chamfer=state))
    joined = "\n".join(labels_for(g, monkeypatch))
    assert "DETAIL B" not in joined
    assert ("CHAMFER: INCOMPLETE - HOLD" if state else "CHAMFER: NONE") in joined
    assert "ORIENTATION ONLY" not in joined
    if not state:
        assert "FLOW" not in joined


def test_configured_chamfer_detail_exact_values(monkeypatch):
    g = build_plate_geometry(
        replace(
            geometry().spec,
            chamfer=True,
            chamfer_width=0.04,
            chamfer_angle_degrees=45,
            chamfer_side="downstream",
            flow_orientation="left-to-right",
            chamfer_width_definition="radial-angle-from-face",
        )
    )
    labels = labels_for(g, monkeypatch)
    for value in (
        "DETAIL B - BORE EDGE - NTS",
        "DOWNSTREAM / ANGLE FROM FACE",
        "45°",
        "0.040 RAD",
        "AXIAL DEPTH 0.0400 / LAND 0.0850",
        "FLOW",
        "B",
    ):
        assert value in labels
