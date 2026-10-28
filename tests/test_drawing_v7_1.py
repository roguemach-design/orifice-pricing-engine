"""V7.1 presentation gates measured from serialized output, not screenshots alone."""
from dataclasses import replace
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from shapely.geometry import LineString, Point, box

from customer_controls import MATERIAL_COPY
from material_labels import drawing_material_name
from plate_geometry import PlateSpec, build_plate_geometry
from drawing_presentation import WEB, PRINT, build_views, fit_web_cell_text, text_width
from scripts.review_drawing_v6 import BASE, svg_for
from test_drawing_v6 import CASES, sampled_path, svg_path, feature


def texts(root):
    for t in root.findall('.//{*}text'):
        a = t.attrib
        x, y, size, width = (float(a[k]) for k in ('x', 'y', 'font-size', 'textLength'))
        x -= width / 2 if a['text-anchor'] == 'middle' else width if a['text-anchor'] == 'end' else 0
        yield t.text, box(x, y - size, x + width, y + size * .25)


def part_edges(root):
    for node in feature(root, 'plate-outline'):
        subpath = []
        for command in svg_path(node.attrib['d']):
            if command[0] == 'm' and subpath:
                yield LineString(sampled_path(subpath))
                subpath = []
            subpath.append(command)
        yield LineString(sampled_path(subpath))
    for key in ('bore', 'handle-hole', 'chamfer-circle'):
        for node in feature(root, key):
            a = node.attrib
            yield Point(float(a['cx']), float(a['cy'])).buffer(float(a['r']), quad_segs=100).boundary
    for key in ('section-face', 'section-end', 'bore-wall', 'hole-wall', 'chamfer-slope', 'chamfer-bore-line'):
        for node in feature(root, key):
            a = node.attrib
            yield LineString([(float(a['x1']), float(a['y1'])), (float(a['x2']), float(a['y2']))])


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('details', [False, True])
@pytest.mark.parametrize('material', list(MATERIAL_COPY))
def test_web_text_never_overlaps_text_or_crosses_part_outline(case, details, material):
    od, bore, width, length, hole = case
    spec = PlateSpec(od, bore, width, length, material, .125, bore_tolerance=.005,
                     chamfer=details, chamfer_width=.02 if details else None,
                     marking='FE-101' if details else None,
                     **(dict(handle_hole_enabled=True, handle_hole_diameter=hole[0],
                             handle_hole_center_from_handle_end=hole[1]) if hole else {}))
    root = ET.fromstring(svg_for(spec))
    labels = list(texts(root))
    edges = list(part_edges(root))
    for (a, ra), (b, rb) in combinations(labels, 2):
        assert not ra.intersects(rb), f'text collision: {a!r} / {b!r}'
    for label, rect in labels:
        assert not any(rect.intersects(edge) for edge in edges), f'part collision: {label!r}'


@pytest.mark.parametrize('material', list(MATERIAL_COPY))
@pytest.mark.parametrize('thickness', [.125, .5])
def test_live_title_block_uses_card_source_and_escapes_and_fits_marking(material, thickness):
    marking = '<&"' + 'LONG MARKING ' * 2 + '12345678901'
    assert len(marking) == 40  # Preserve the canonical maximum, including XML characters.
    svg = svg_for(replace(BASE, material=material, thickness=thickness, marking=marking))
    root = ET.fromstring(svg)
    assert '&lt;' in svg and '&amp;' in svg and '&quot;' in svg
    assert '<&"' not in svg
    fields = {t.attrib['data-feature']: t.text for t in root.findall('.//{*}text') if 'data-feature' in t.attrib}
    card_name = MATERIAL_COPY[material][0].replace(' SS', ' STAINLESS STEEL').upper()
    assert fields['web-material'] == card_name == drawing_material_name(material)
    assert fields['web-thickness'] == f'{thickness:.3f}'.removeprefix('0') + ' IN'
    assert fields['web-marking'].startswith('"') and fields['web-marking'].endswith('…"')
    assert fields['web-scale'] == root.attrib['data-scale']
    assert fields['web-status'] == 'CONFIGURATION PREVIEW — NOT AN APPROVED MANUFACTURING DRAWING'
    # Its cell is the third field in row two: compare against the actual cell path.
    node = feature(root, 'web-marking')[0]
    x, w = float(node.attrib['x']), float(node.attrib['textLength'])
    cells = [sampled_path(svg_path(p.attrib['d'])) for p in root.findall('.//{*}path')
             if p.attrib['d'].endswith('Z ') or p.attrib['d'].endswith('Z')]
    assert any(min(px for px, py in p) < x and x + w < max(px for px, py in p)
               and min(py for px, py in p) < float(node.attrib['y']) < max(py for px, py in p)
               for p in cells)


def test_sixty_character_display_text_fits_without_expanding_canonical_marking_limit():
    marking = '<&"' + 'LONG MARKING ' * 4 + '12345'
    assert len(marking) == 60
    # The presentation formatter is robust to 60 characters; input validation
    # still rejects more than 40, as it did before this drawing-only release.
    fitted = fit_web_cell_text('"' + marking + '"', 132.5, 6.6, quoted=True)
    assert fitted.startswith('"') and fitted.endswith('…"')
    assert text_width(fitted, 6.6 * WEB.text) <= 132.5 - 8
    with pytest.raises(ValueError, match='1-40 characters'):
        replace(BASE, marking=marking)


def test_profile_scales_and_marking_leader_are_presentation_only():
    g = build_plate_geometry(replace(BASE, marking='FE-101'))
    for profile in (WEB, PRINT):
        scene, view, _ = build_views(g, profile=profile)
        text = next(e for e in scene.elements if e.key == 'handle-length-label')
        assert text.data[3] == 8 * profile.text
        outline = next(e for e in scene.elements if e.key == 'plate-outline')
        assert outline.width == 1.25 * profile.line
        leader = next(e for e in scene.elements if e.key == 'marking')
        tip = leader.data[0]
        assert view.cx < tip[0] < view.cx + g.half_handle_width * view.scale
        assert view.break_ys[1] < tip[1] < view.tip_y
        labels = [e.data[2] for e in scene.elements if e.key == 'marking-label']
        assert labels == (['MARKING'] if profile == WEB else ['MARKING', 'SEE NOTE 6'])
    assert g.spec == replace(BASE, marking='FE-101')


def test_preview_and_landing_have_intrinsic_height_without_fixed_drawing_box():
    root = Path(__file__).parents[1]
    page = (root / 'pages/1_Quote.py').read_text()
    drawing = page.split('if preview_ready:')[1].split('else:')[0]
    assert 'st.markdown(' in drawing and 'render_plate_svg(' in drawing
    assert 'unsafe_allow_html=True' in drawing and 'st.html(' not in drawing
    assert 'height=300' not in drawing and 'height:100%' not in drawing
    css = (root / 'o-plates landing/styles.css').read_text()
    rule = css.split('.sticky-feedback__drawing svg{')[1].split('}')[0]
    assert 'width:100%' in rule and 'height:auto' in rule and 'max-height' not in rule
