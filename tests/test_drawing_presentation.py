"""NTS is a PDF-only mapping; dimensions remain facts from the exact spec."""

from dataclasses import replace
from hashlib import sha256
from math import atan2, degrees
from pathlib import Path
import pytest
from reportlab.pdfgen.canvas import Canvas
import manufacturing_drawing as drawing
from manufacturing_files import dxf_bytes, preview_svg
from plate_geometry import build_plate_geometry, manufacturing_record
from prototype_manufacturing import sample_spec
from section_geometry import build_section_geometry


def example(**updates):
    values = dict(
        chamfer=True,
        chamfer_width=0.04,
        chamfer_angle_degrees=45,
        chamfer_side="downstream",
        flow_orientation="left-to-right",
        chamfer_width_definition="radial-angle-from-face",
    )
    values.update(updates)
    return build_plate_geometry(replace(sample_spec(), **values))


def test_presentation_is_independent_and_labels_stay_exact(monkeypatch):
    from drawing_presentation import build_presentation
    g=example()
    before=(manufacturing_record(g),dxf_bytes(g),preview_svg(g))
    labels=[]
    for method in ('drawString','drawCentredString'):
        monkeypatch.setattr(Canvas,method,lambda self,x,y,t,*a,**k:labels.append(t))
    view=build_presentation(g)
    first=drawing.render_pdf(g,presentation=view)
    original=labels[:];labels.clear()
    second=drawing.render_pdf(g,presentation=replace(view,denominator=view.denominator*2))
    assert first!=second
    assert [x for x in labels if not x.startswith('1:')]==[x for x in original if not x.startswith('1:')]
    for value in ('Ø1.548','10.50','2.00','.125','.040 X 45°'):
        assert value in labels
    assert before==(manufacturing_record(g),dxf_bytes(g),preview_svg(g))


@pytest.mark.parametrize("length", [2.7, 10.5, 30])
def test_upward_rotation_and_shortened_handle_only_affect_display(length):
    from drawing_presentation import build_presentation
    g=build_plate_geometry(replace(sample_spec(),centerline_to_handle_end=length))
    v=build_presentation(g)
    assert v.point((length,0))==pytest.approx((v.cx,v.tip_y))
    assert v.point((-g.radius,0))==pytest.approx((v.cx,v.cy-g.radius*v.scale))
    assert g.spec.centerline_to_handle_end==length
    assert max(p[0] for seg in g.segments for p in (seg.start,seg.end))==length
    assert (v.tip_y-v.cy < length*v.scale-1e-9)==v.broken


@pytest.mark.parametrize("flow", ["left-to-right", "right-to-left"])
@pytest.mark.parametrize("side", ["upstream", "downstream"])
@pytest.mark.parametrize("angle", [30, 45, 60])
def test_section_angle_side_and_flow_survive_nts(flow, side, angle, monkeypatch):
    from drawing_presentation import build_views
    g=example(flow_orientation=flow,chamfer_side=side,chamfer_angle_degrees=angle)
    sec=build_section_geometry(g.spec)
    scene,v,shown=build_views(g)
    slope=next(e for e in scene.elements if e.key=='chamfer-slope').data
    dx,dy=(abs(slope[1][i]-slope[0][i]) for i in (0,1))
    assert degrees(atan2(dx,dy))==pytest.approx(angle,abs=1e-10)
    assert shown.face==sec.face==('left' if (side=='upstream')==(flow=='left-to-right') else 'right')
    faces=[e.data for e in scene.elements if e.key=='section-face']
    assert max(a[0] for a,b in faces)-min(a[0] for a,b in faces)==pytest.approx(g.spec.thickness*v.scale)
    index=next(i for i,e in enumerate(scene.elements) if e.key=='flow')
    arrow=scene.elements[index+1].data
    assert (arrow[0][1]<arrow[1][1])==(flow=='right-to-left')


@pytest.mark.parametrize("enabled", [False, True])
def test_no_fake_bevel_when_none_or_incomplete(enabled):
    from drawing_presentation import build_views
    g=build_plate_geometry(replace(sample_spec(),chamfer=enabled))
    sec=build_section_geometry(g.spec)
    scene,_,_=build_views(g)
    assert not sec.chamfer_drawn
    assert sec.status==('INCOMPLETE - HOLD' if enabled else 'NONE')
    assert not any(e.key in ('chamfer-slope','chamfer-circle') for e in scene.elements)


def test_locked_golden_pdf_visual_fixture():
    g = build_plate_geometry(replace(sample_spec(), part_identifier="PROTOTYPE-001"))
    data = drawing.render_pdf(g)
    expected = (
        (Path(__file__).parent / "fixtures/v6-manufacturing-print.sha256")
        .read_text()
        .strip()
    )
    assert (
        sha256(data).hexdigest() == expected
    ), "Review raster visually before explicit fixture refresh"
    assert data == drawing.render_pdf(g)
