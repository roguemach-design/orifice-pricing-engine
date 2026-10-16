"""Shop-file presentation and independent prototype cutting-file validation."""

from dataclasses import replace
from io import StringIO
import json

import ezdxf
import pytest
from shapely.geometry import Polygon, LineString
from streamlit.testing.v1 import AppTest
from packaging_generator.generator import generate, layout, perforations
from test_final4 import fixture_inputs, spec, system


def test_laser_file_center_nest_disjoint_closed_contours_and_intact_fold_webs():
    _, _, config, _ = fixture_inputs()
    s = spec()
    d = layout(s, config)
    data = generate(s, config, {"revision_id": "fixture-R2"})
    doc = ezdxf.read(StringIO(data["packaging.dxf"].decode()))
    assert not doc.audit().has_errors and not doc.audit().has_fixes
    assert doc.units == ezdxf.units.IN
    assert {e.dxf.layer for e in doc.modelspace()} == {
        "CUT_SHELL",
        "CUT_FRAME",
        "CUT_NEST",
        "PERF_FOLD_LEFT",
        "PERF_FOLD_RIGHT",
    }
    contours = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"]
    boundaries = []
    for e in contours:
        assert e.closed
        coords = list(e.get_points("xy"))
        assert len(coords) == len(set(coords))
        poly = Polygon(coords)
        assert poly.is_valid and poly.area > 0
        boundaries.append(poly.boundary)
    for i, boundary in enumerate(boundaries):
        for other in boundaries[i + 1 :]:
            assert boundary.disjoint(other)
    center = next(e for e in contours if e.dxf.layer == "CUT_NEST")
    center_poly = Polygon(center.get_points("xy"))
    xmin, ymin, xmax, ymax = center_poly.bounds
    assert (xmin + xmax) / 2 == pytest.approx(d["center_x"] + d["panel_width"] / 2)
    assert (ymin + ymax) / 2 == pytest.approx(d["panel_height"] / 2)
    assert center_poly.area == pytest.approx(d["nest"].area)
    signatures = set()
    for e in doc.modelspace():
        if e.dxftype() == "LINE":
            key = (tuple(e.dxf.start), tuple(e.dxf.end))
            assert key not in signatures
            signatures.add(key)
            segment = LineString(
                [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            )
            assert all(segment.disjoint(boundary) for boundary in boundaries)
    stitches = perforations(d["panel_height"], config)
    for a, b in zip(stitches, stitches[1:]):
        assert b[0] - a[1] == pytest.approx(config.stitch_web)
    assert stitches[0][0] >= config.fold_end_bridge
    assert stitches[-1][1] <= d["panel_height"] - config.fold_end_bridge
    assert data == generate(s, config, {"revision_id": "fixture-R2"})


def test_single_layer_and_thicker_layers_preserve_center_cutout():
    _, _, config, _ = fixture_inputs()
    config = replace(config, caliper=0.25, max_layers=1)
    s = spec()
    d = layout(s, config)
    assert d["nest_layers"] == 1 and d["frame_positions"] == []
    doc = ezdxf.read(StringIO(generate(s, config, {})["packaging.dxf"].decode()))
    assert len(doc.modelspace().query('LWPOLYLINE[layer=="CUT_NEST"]')) == 1
    assert not list(doc.modelspace().query('*[layer=="CUT_FRAME"]'))
    assert not doc.audit().has_errors


@pytest.mark.parametrize(
    "change",
    [{"stitch_length": 0}, {"stitch_web": float("nan")}, {"fold_end_bridge": True}],
)
def test_bad_perforation_profile_fails_closed(change):
    _, _, config, _ = fixture_inputs()
    with pytest.raises(ValueError):
        replace(config, **change)


def test_downloads_preserve_stored_bundles_without_rerunning_generators(
    system, monkeypatch
):
    svc, parent, record, _ = system
    from dataclasses import asdict

    before = svc.repo.revision(parent["revision_id"])
    bundles = [
        svc.create(
            family,
            parent,
            actor="owner",
            reviewed_record=asdict(record) if family == "HAAS" else None,
        )
        for family in ("HAAS", "PACKAGING")
    ]
    expected = {
        (b["id"], f["name"]): svc.download(b["id"], f["name"])[2]
        for b in bundles
        for f in b["files"]
    }

    def forbidden(*a, **k):
        raise AssertionError("download regenerated artifact")

    monkeypatch.setattr("final4.service.packaging", forbidden)
    monkeypatch.setattr("final4.service.engineering_bundle", forbidden)
    for b in bundles:
        for f in b["files"]:
            assert svc.download(b["id"], f["name"])[2] == expected[b["id"], f["name"]]
        assert b["parent"]["revision_id"] == parent["revision_id"]
        assert not b["statuses"]["manufacturing_release_approved"]
        assert not b["statuses"]["release_eligible"]
    assert b"#3000=1 (ENGINEERING HOLD)" in expected[bundles[0]["id"], "program.NC"]
    assert svc.repo.revision(parent["revision_id"]) == before


def portal_source(current=True, approved=True):
    return """
import streamlit as st
from manufacturing_control.derived import show
class Client:
 def json(self,path):
  return dict(packaging_configuration={'version':'profile-test'},machine_profile={},machining_parameters={},staging_profiles={'HAAS':'h','PACKAGING':'p'})
 def manufacturing_post(self,path,body):
  if path.endswith('/query'):
   result=[]
   for n in range(3):
    for family,name in [('HAAS','program.NC'),('PACKAGING','packaging.dxf')]:
     result.append(dict(staging={'mode':'AUTOMATIC','profile_sha256':'h' if family=='HAAS' else 'p','machine_profile':{'revision':'M1'}},id=family+str(n),family=family,created_at=str(n),generator_version='corrugated-trifold-2',state='ENGINEERING REVIEW',files=[dict(name=name,filename=family+str(n)+'-R1-'+name,size=1,sha256='f'*64),dict(name='inputs.json',filename='audit.json',size=1,sha256='a'*64)]))
   return result
  st.session_state['generated']=body
  return {'id':'bundle'}
rev={'id':'r','number':1,'spec_sha256':'a'*64,'source_sha256':'b'*64,'spec_json':'{"part_identifier":"P","finished_bore_diameter":1.548,"bore_tolerance":0.001,"thickness":0.125,"material":"304 Stainless Steel","chamfer":false}'}
plate={'id':'p','order_id':'o','line_id':'line-1'}
show(Client(),rev,plate,CURRENT,APPROVED)
""".replace("CURRENT", str(current)).replace("APPROVED", str(approved))


def test_primary_only_latest_nc_and_packaging_audit_collapsed_no_generation_on_view():
    at = AppTest.from_string(portal_source()).run()
    assert not at.exception and "generated" not in at.session_state
    buttons = at.get("download_button")
    assert sum(b.proto.label == "Download NC" for b in buttons) == 1
    assert sum(b.proto.label == "Download Packaging DXF" for b in buttons) == 1
    for label in ("Engineering details / audit files", "Generation history (6)"):
        exp = next(e for e in at.expander if e.label == label)
        assert exp.proto.expanded is False
    for b in buttons:
        if b.proto.label in (
            "Download inputs.json",
            "Download program.NC",
            "Download packaging.dxf",
        ):
            # Audit downloads are descendants of the collapsed history, not primary cards.
            assert b in next(
                e for e in at.expander if e.label == "Generation history (6)"
            ).get("download_button")
    assert (
        len(
            next(e for e in at.expander if e.label == "Generation history (6)").get(
                "download_button"
            )
        )
        == 12
    )
    assert (
        not at.button and not at.checkbox and not at.number_input and not at.text_input
    )


@pytest.mark.parametrize("current,approved", [(False, True), (True, False)])
def test_historical_or_unapproved_selection_cannot_generate(current, approved):
    at = AppTest.from_string(portal_source(current, approved)).run()
    assert not at.exception and "generated" not in at.session_state
    assert not any("Generate" in b.label or "Regenerate" in b.label for b in at.button)
    if not current:
        assert not any(
            b.proto.label in ("Download NC", "Download Packaging DXF")
            for b in at.get("download_button")
        )


def test_normal_screen_has_no_review_or_generation_fields():
    at = AppTest.from_string(portal_source()).run()
    assert not at.exception
    assert (
        not at.text_input
        and not at.number_input
        and not at.selectbox
        and not at.checkbox
    )
    assert all(b.disabled for b in at.button)
    assert "generated" not in at.session_state


def test_failed_bundle_query_blocks_generation_and_preserves_audit():
    source = portal_source().replace(
        "  if path.endswith('/query'):",
        "  from owner_portal_transport import PortalError\n  raise PortalError('rate')\n  if path.endswith('/query'):",
    )
    at = AppTest.from_string(source).run()
    assert not at.exception and "generated" not in at.session_state
    assert all(b.disabled for b in at.button)
    assert any(e.label == "Engineering details / audit files" for e in at.expander)
    assert any("Too many requests" in i.value for i in at.info)
