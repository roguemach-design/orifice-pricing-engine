"""Serialized DXF geometry and prospective packaging version adoption."""

from dataclasses import replace
from io import StringIO
from math import pi, hypot, sin, cos
import json
import ezdxf
import pytest
from shapely.geometry import Point
from packaging_generator import VERSION
from packaging_generator.generator import generate, layout, sampled_outline
from packaging_generator.contour import area, polygon
from packaging_generator.audit import inspect, decode
from plate_geometry import build_plate_geometry
from test_final4 import fixture_inputs, spec, system
from test_automatic_staging import stager


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"handle_width": 0.5},
        {"centerline_to_handle_end": 30},
        {"thickness": 0.5},
        {"handle_width": 4.8, "centerline_to_handle_end": 6},
    ],
)
def test_true_arcs_reliefs_offsets_alignment_and_determinism(changes):
    _, _, c, _ = fixture_inputs()
    s = replace(spec(), **changes)
    files = generate(s, c, {"revision": "SYNTHETIC-R1"})
    assert files == generate(s, c, {"revision": "SYNTHETIC-R1"})
    audit = inspect(files["packaging.dxf"])
    d = layout(s, c)
    assert audit["nest_count"] == d["nest_layers"]
    arcs = audit["nests"][0]["arcs"]
    paddle = arcs[0]
    assert paddle["radius"] == pytest.approx(
        s.finished_od / 2 + c.clearance - c.kerf / 2
    )
    reliefs = [a for a in arcs if a["sweep_degrees"] == pytest.approx(180)]
    assert len(reliefs) == 2 and all(a["bulge"] == pytest.approx(1) for a in reliefs)
    # Left side of the vertically oriented handle; both centers share its long edge.
    cx = d["center_x"] + d["nest_transform"]["xoff"]
    cy = d["nest_transform"]["yoff"]
    assert all(
        a["center"][0]
        == pytest.approx(cx - s.handle_width / 2 - c.clearance + c.kerf / 2)
        for a in reliefs
    )
    g = build_plate_geometry(s)
    bridge = d["geometry_report"]["minimum_bridge"]
    assert all(
        cy + g.join_x + bridge <= a["center"][1] - a["radius"]
        and a["center"][1] + a["radius"]
        <= cy + s.centerline_to_handle_end - g.corner_radius - bridge
        for a in reliefs
    )
    # Every circle is outside steel. Its open half projects away from the steel.
    steel = polygon(g.segments, error=0.000001)
    for info in d["geometry_report"]["finger_reliefs"]:
        x, y = info["center_plate_coordinates"]
        r = info["cutter_radius"]
        for i in range(101):
            p = Point(x + r * cos(pi * i / 100), y + r * sin(pi * i / 100))
            assert not steel.contains(p)
    # Independent serialized boundary must enclose steel at the requested offset.
    doc = ezdxf.read(StringIO(files["packaging.dxf"].decode()))
    hole = doc.modelspace().query('LWPOLYLINE[layer=="CUT_NEST"]')[0]
    poly, _ = decode(hole)
    from shapely import affinity

    steel = affinity.translate(affinity.rotate(steel, 90, origin=(0, 0)), cx, cy)
    assert poly.contains(steel)
    assert poly.boundary.distance(steel) >= c.clearance - c.kerf / 2 - 0.00003
    assert poly.area == pytest.approx(area(d["nest_segments"]), abs=0.001)
    assert VERSION == "corrugated-trifold-3-arcs-side-access"
    assert json.loads(files["manifest.json"])["generator_version"] == VERSION
    assert b"<polygon" not in files["layout.svg"] and b" A " in files["layout.svg"]


def tangent(s, end=False):
    if s.kind == "line":
        dx, dy = s.end[0] - s.start[0], s.end[1] - s.start[1]
    else:
        a = (s.start_degrees + (s.sweep_degrees if end else 0)) * pi / 180
        sign = 1 if s.sweep_degrees > 0 else -1
        dx, dy = -sin(a) * sign, cos(a) * sign
    n = hypot(dx, dy)
    return dx / n, dy / n


@pytest.mark.parametrize("kerf", [0, 0.01, 0.03, 0.04])
def test_exact_tangency_and_internal_kerf_direction(kerf):
    _, _, c, _ = fixture_inputs()
    c = replace(c, kerf=kerf)
    d = layout(spec(), c)
    segs = d["nest_segments"]
    # Only the four intentional line/relief mouth joins are non-tangent.
    for a, b in zip(segs, segs[1:] + segs[:1]):
        assert a.end == pytest.approx(b.start, abs=1e-10)
        if a.sweep_degrees == 180 or b.sweep_degrees == 180:
            continue
        assert tangent(a, True) == pytest.approx(tangent(b), abs=1e-10)
    assert d["geometry_report"]["neck_cutter_radius"] == pytest.approx(
        0.03125 - c.clearance + kerf / 2
    )
    assert segs[0].radius + kerf / 2 == pytest.approx(2.5 + c.clearance)
    assert all(
        a["cutter_diameter"] + kerf == pytest.approx(0.75)
        for a in d["geometry_report"]["finger_reliefs"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"handle_width": 0.1, "centerline_to_handle_end": 2.6},
        {
            "finished_od": 1,
            "finished_bore_diameter": 0.3,
            "handle_width": 0.25,
            "centerline_to_handle_end": 1,
        },
    ],
)
def test_constrained_handles_fail_with_engineering_reason(changes):
    _, _, c, _ = fixture_inputs()
    with pytest.raises(ValueError, match="cannot safely accommodate two"):
        generate(replace(spec(), **changes), c, {})


def test_collapsed_offset_not_guessed():
    _, _, c, _ = fixture_inputs()
    with pytest.raises(ValueError, match="collapses canonical neck"):
        generate(spec(), replace(c, clearance=0.04), {})


def test_historical_approval_does_not_generate_or_replace_bundles(system, monkeypatch):
    svc, a, _, _ = system
    auto = stager(svc)
    old = auto.ensure("PACKAGING", a)
    oldmeta = svc.metadata(old)
    before = {f["name"]: svc.download(old, f["name"])[2] for f in oldmeta["files"]}
    from datetime import datetime, timezone

    monkeypatch.setattr(
        "final4.automatic.PACKAGING_V3_APPROVAL_CUTOFF",
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "final4.automatic.PACKAGING_VERSION", "prospective-version-test"
    )
    monkeypatch.setattr(
        "final4.automatic.packaging",
        lambda *a: (_ for _ in ()).throw(AssertionError("historical regeneration")),
    )
    assert auto.ensure("PACKAGING", a) == old
    assert len(svc.list(a)) == 1
    assert svc.metadata(old) == oldmeta
    assert {
        f["name"]: svc.download(old, f["name"])[2] for f in oldmeta["files"]
    } == before


def test_historical_approval_without_bundle_requires_explicit_action(
    system, monkeypatch
):
    svc, a, _, _ = system
    from datetime import datetime, timezone

    monkeypatch.setattr(
        "final4.automatic.PACKAGING_V3_APPROVAL_CUTOFF",
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="explicit owner generation"):
        stager(svc).ensure("PACKAGING", a)
    assert not svc.list(a)
    # Explicit generation creates a NEW associated immutable artifact, without revising approval.
    revision = svc.repo.revision(a["revision_id"])
    b = svc.create("PACKAGING", a, actor="isolated-test-owner")
    assert b["generator_version"] == VERSION
    assert svc.repo.revision(a["revision_id"]) == revision
    inspect(svc.download(b["id"], "packaging.dxf")[2])
