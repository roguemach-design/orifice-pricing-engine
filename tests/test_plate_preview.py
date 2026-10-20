from math import hypot
import re
from xml.etree import ElementTree

import pytest

from plate_preview import render_plate_svg


def test_svg_contains_customer_dimensions_and_drawing_disclaimer():
    svg=render_plate_svg(paddle_dia=3,bore_dia=1,handle_width=1.5,handle_length_from_bore=9,thickness=.125,material='304',bore_tolerance=.005,handle_label='UPSTREAM',chamfer=True)
    for label in ('Ø3.000','Ø1.000 ±.005','1.50','9.00','.125','UPSTREAM','CHAMFER SIZE REQUIRED','Configuration preview','Not an approved manufacturing drawing'):
        assert label in svg
    assert 'NTS' not in svg and 'role="img"' in svg
    ElementTree.fromstring(svg)


def test_svg_escapes_customer_controlled_text():
    svg = render_plate_svg(
        paddle_dia=3,
        bore_dia=1,
        handle_width=1,
        handle_length_from_bore=5,
        thickness=0.25,
        material="<script>alert(1)</script>",
        handle_label="A&B <UPSTREAM>",
    )

    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    assert "A&amp;B &lt;UPSTREAM&gt;" in svg


@pytest.mark.parametrize(
    ("paddle_dia", "bore_dia", "handle_width", "handle_length"),
    [
        (1.0, 0.125, 0.125, 0.75),
        (3.0, 1.0, 1.5, 9.0),
        (48.0, 19.0, 1.5, 25.0),
    ],
)
def test_svg_is_valid_for_small_default_and_maximum_configurations(paddle_dia,bore_dia,handle_width,handle_length):
    from drawing_standards import dimension
    svg=render_plate_svg(paddle_dia=paddle_dia,bore_dia=bore_dia,handle_width=handle_width,handle_length_from_bore=handle_length,thickness=.5,material='Carbon Steel')
    root=ElementTree.fromstring(svg)
    assert root.tag.endswith('svg')
    for value,feature in ((paddle_dia,'od'),(bore_dia,'bore'),(handle_width,'width'),(handle_length,'length'),(.5,'thickness')):
        assert dimension(value,feature) in svg
    assert 'Carbon Steel' in svg


def test_material_thickness_and_chamfer_update_title_block_with_customer_width():
    common=dict(paddle_dia=6,bore_dia=2,handle_width=1.5,handle_length_from_bore=10)
    stainless=render_plate_svg(material='304',thickness=.125,chamfer=False,**common)
    carbon=render_plate_svg(material='Carbon Steel',thickness=.5,chamfer=True,chamfer_width=.062,**common)
    assert stainless!=carbon
    assert '304' in stainless and '.125' in stainless
    assert 'Carbon Steel' in carbon and '.500' in carbon
    assert '.062 X 45°' in carbon
    assert 'chamfer-circle' in carbon and 'chamfer-circle' not in stainless


@pytest.mark.parametrize(
    ("od", "handle_width", "handle_length"),
    [
        (3.0, 1.5, 9.0),
        (5.0, 2.0, 9.0),
        (8.5, 1.5, 14.0),
        (16.0, 1.25, 20.0),
        (1.0, 0.9, 2.0),  # Wide handle on a small plate.
    ],
)
def test_outer_profile_has_one_tangent_symmetric_contour(od,handle_width,handle_length):
    from plate_geometry import PlateSpec,build_plate_geometry
    from drawing_presentation import build_presentation
    from test_drawing_v6 import svg_path,sampled_path
    g=build_plate_geometry(PlateSpec(od,od/3,handle_width,handle_length,'304',.125))
    view=build_presentation(g)
    root=ElementTree.fromstring(render_plate_svg(paddle_dia=od,bore_dia=od/3,handle_width=handle_width,handle_length_from_bore=handle_length,thickness=.125,material='304'))
    outline=root.find(".//*[@data-feature='plate-outline']")
    assert outline is not None and outline.attrib['fill']=='none'
    points=sampled_path(svg_path(outline.attrib['d']))
    assert min(x for x,y in points)+max(x for x,y in points)==pytest.approx(view.cx*2,abs=.01)
    assert max(x for x,y in points)-min(x for x,y in points)==pytest.approx(od*view.scale,rel=.005)
    endpoints=[p[-1] for p in svg_path(outline.attrib['d']) if len(p)>1]
    for seg in g.segments:
        x,y=view.point(seg.end)
        assert any(p==pytest.approx((x,-y),abs=.00001) for p in endpoints)
    # Canonical neck circle is tangent to both OD and straight handle.
    for seg in (g.segments[1],g.segments[-1]):
        assert hypot(*seg.center)==pytest.approx(g.radius+g.corner_radius)
        assert abs(seg.center[1])==pytest.approx(g.half_handle_width+g.corner_radius)
    assert sum(seg.radius==.03125 for seg in g.segments)==4
