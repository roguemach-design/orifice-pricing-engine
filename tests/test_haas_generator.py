"""Geometry and authorization regressions; no machine actions or release claims."""

from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json
from math import atan2, hypot, pi
from pathlib import Path
import re
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from haas_generator.contract import CHECKS, construct, from_dict, loads
from haas_generator.generator import candidate_blocks, generate, plan
from haas_generator.web import archive, create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    return from_dict(
        json.loads((ROOT / "examples/haas/record.json").read_text()),
        json.loads((ROOT / "examples/haas/profile.json").read_text()),
    )


def test_sample_corrected_radii_and_probe_depth(inputs):
    r, p = inputs
    g = plan(r, p)
    assert g["finished_edge_radius"] == pytest.approx(0.774)
    assert g["finish_center_radius"] == pytest.approx(0.524)
    assert g["rough_end_center_radius"] == pytest.approx(0.514)
    # Ball, not just point, lies on straight cylindrical wall below chamfer.
    z = g["probe_ball_center_z"]
    assert z - p.probe_ball_radius > 0
    assert z + p.probe_ball_radius < r.thickness - r.top_chamfer_width
    assert g["probe_tip_z"] != 0.125


def test_spiral_monotonic_pitch_and_swept_edge(inputs):
    r, p = inputs
    points = plan(r, p)["paths"]["rough_tool_center"]
    radii = [hypot(x, y) for x, y, _ in points]
    assert all(b >= a - 1e-10 for a, b in zip(radii, radii[1:]))
    assert max(radii) + p.t1_diameter / 2 == pytest.approx(r.finished_bore / 2 - 0.010)
    # Unwrap the first expanding turn independently from generated coordinates.
    angle = 0
    last = atan2(points[0][1], points[0][0])
    for point, radius in zip(points[1:], radii[1:]):
        current = atan2(point[1], point[0])
        angle += (current - last + pi) % (2 * pi) - pi
        last = current
        if radius < max(radii) - 1e-8:
            assert radius - radii[0] == pytest.approx(
                0.035 * angle / (2 * pi), abs=1e-8
            )


@pytest.mark.parametrize(
    "setting,wear", [("RADIUS", 0.0004), ("DIAMETER", 0.0008), ("RADIUS", -0.0004)]
)
def test_wear_is_not_full_radius_compensation(inputs, setting, wear):
    r, p = inputs
    p = replace(p, setting40=setting, t1_d_wear=wear)
    g = plan(r, p)
    radius = hypot(*g["paths"]["finish_wear_adjusted_tool_center"][0][:2])
    correction = wear / (2 if setting == "DIAMETER" else 1)
    assert radius == pytest.approx(0.524 - correction)
    assert g["wear_adjusted_bore"] == pytest.approx(1.548 - 2 * correction)


def test_chamfer_cone_intersections_and_top_only(inputs):
    r, p = inputs
    g = plan(r, p)
    center = g["chamfer_center_radius"]
    # 45-degree tool cone: radius at top = tip radius + tip depth.
    assert center + p.t2_tip_diameter / 2 + p.chamfer_tip_depth == pytest.approx(
        r.finished_bore / 2 + r.top_chamfer_width
    )
    assert (
        center + p.t2_tip_diameter / 2 + p.chamfer_tip_depth - r.top_chamfer_width
        == pytest.approx(r.finished_bore / 2)
    )
    assert all(z > 0 for _, _, z in g["paths"]["chamfer_tool_center"])


def test_no_chamfer_means_no_t2(inputs):
    r, p = inputs
    r = replace(r, top_chamfer_width=0)
    g = plan(r, p)
    assert not g["paths"]["chamfer_tool_center"]
    assert "T2 M06" not in candidate_blocks(r, p, g)


@pytest.mark.parametrize("thickness", [0.125, 0.250, 0.375, 0.500])
def test_supported_plate_depths(inputs, thickness):
    r, p = inputs
    r = replace(r, thickness=thickness)
    g = plan(r, p)
    assert 0 < g["probe_tip_z"] < thickness
    assert thickness - p.cut_bottom_z <= p.t1_flute_length


@pytest.mark.parametrize(
    "change",
    [
        {"fixture_clearance_below": 0},
        {"t1_d_geometry": 0.5},
        {"setting40": "UNKNOWN"},
        {"rough_rpm": 9000},
        {"rough_feed": 200},
        {"t2_included_angle": 60},
        {"t2_tip_diameter": 0.001},
        {"t1_d_wear": 0.2},
        {"probe_center_from_tip": 0},
        {"t1_h": True},
    ],
)
def test_invalid_machine_profile_rejected(inputs, change):
    _, p = inputs
    with pytest.raises(ValueError):
        replace(p, **change)


@pytest.mark.parametrize(
    "change",
    [
        {"units": "mm"},
        {"finished_bore": float("nan")},
        {"thickness": True},
        {"actual_blank_bore": 1.549},
        {"source_sha256": "unknown"},
        {"reviewed_by": ""},
        {"job_id": "X) M03 ("},
        {"top_chamfer_width": 0.125},
        {"finished_bore": 1e100},
    ],
)
def test_invalid_record_rejected(inputs, change):
    r, _ = inputs
    with pytest.raises(ValueError):
        replace(r, **change)


@pytest.mark.parametrize(
    "change",
    [
        {"work_x_max": 0.5},
        {"safe_z": 0.1},
        {"fixture_opening_radius": 0.7},
        {"t1_flute_length": 0.1},
        {"probe_ball_radius": 0.060, "probe_center_from_tip": 0.060},
        {"chamfer_tip_depth": 0.008},
        {"center_error_bound": 0.02},
        {"finish_lead": 0.011},
        {"approved_material": "Carbon Steel"},
    ],
)
def test_invalid_combined_geometry_rejected(inputs, change):
    r, p = inputs
    with pytest.raises(ValueError):
        plan(r, replace(p, **change))


def test_narrow_blank_rejects_tool(inputs):
    r, p = inputs
    with pytest.raises(ValueError, match="spiral"):
        plan(replace(r, actual_blank_bore=0.49), p)


def test_probe_calls_update_xy_once_measure_only_later(inputs):
    r, p = inputs
    blocks = candidate_blocks(r, p, plan(r, p))
    calls = [b for b in blocks if b.startswith("G65 P9814")]
    assert len(calls) == 2
    assert calls[0].endswith(" S1")
    assert not re.search(r" [STZ]", calls[1])
    assert not re.search(r" Z", calls[0])  # Z argument selects boss, not internal bore!
    assert not any(b.startswith(("G10", "#")) for b in blocks)
    assert blocks[blocks.index(calls[1]) + 1] == "M00"
    assert sum(b.startswith("G01 G41 D") for b in blocks) == 1
    assert sum(b.startswith("G01 G40") for b in blocks) == 1


def test_emitted_nc_rough_and_finish_coordinates(inputs):
    r, p = inputs
    blocks = candidate_blocks(r, p, plan(r, p))
    rough = []
    for block in blocks:
        match = re.fullmatch(r"G01 X(-?[0-9.]+) Y(-?[0-9.]+) F15.000000", block)
        if match:
            rough.append(hypot(float(match[1]), float(match[2])))
    assert rough
    assert max(rough) + 0.250 == pytest.approx(0.764, abs=0.000001)
    assert "G01 G41 D1 X0.524000 Y0.000000 F10.000000" in blocks
    assert "G03 X-0.524000 Y0.000000 I-0.524000 J0.000000" in blocks


def test_all_nc_motion_is_commented_even_with_complete_verification(inputs):
    r, p = inputs
    p = replace(
        p, verified_by="TEST ONLY", evidence={key: "SYNTHETIC TEST" for key in CHECKS}
    )
    files = generate(r, p)
    active = [
        line
        for line in files["program.NC"].splitlines()
        if line and not line.startswith("(")
    ]
    assert active == ["%", "O09001", "#3000=1 (REVIEW DRAFT DO NOT RUN)", "M30", "%"]
    assert "operator-ready" not in files["program.NC"]


def test_reproducibility_manifest_and_revision_binding(inputs):
    r, p = inputs
    files = generate(r, p)
    assert files == generate(r, p)
    assert archive(files) == archive(generate(r, p))
    manifest = json.loads(files["manifest.json"])
    for name, expected in manifest["files"].items():
        assert sha256(files[name].encode("ascii")).hexdigest() == expected
    changed = generate(replace(r, drawing_revision="R2"), p)
    assert changed["program.NC"] != files["program.NC"]
    assert "UNMEASURED" in files["inspection.md"]
    assert len(manifest["holds"]) == len(CHECKS) + 1


def test_strict_json_and_unknown_fields(inputs):
    for data in ('{"x":1,"x":2}', '{"x":NaN}'):
        with pytest.raises(ValueError):
            loads(data)
    r, _ = inputs
    with pytest.raises(ValueError, match="unknown"):
        construct(type(r), {**asdict(r), "operator_ready": True})
    with pytest.raises(ValueError):
        replace(r, finished_bore=10**1000)


def test_zero_breakthrough_and_excess_wear_remain_on_hold(inputs):
    r, p = inputs
    p = replace(p, cut_bottom_z=0, t1_d_wear=0.003)
    holds = plan(r, p)["holds"]
    assert any("through-bore" in h for h in holds)
    assert any("outside drawing tolerance" in h for h in holds)


@pytest.fixture
def client(inputs):
    _, p = inputs
    return TestClient(
        create_app(admin_key="test-only-dedicated-secret-value-12345", profile=p)
    )


@pytest.mark.parametrize(
    "path,method", [("/", "get"), ("/profile", "get"), ("/generate", "post")]
)
def test_admin_auth_required(client, path, method):
    call = getattr(client, method)
    assert call(path).status_code == 401
    assert (
        call(
            path, auth=("customer", "test-only-dedicated-secret-value-12345")
        ).status_code
        == 401
    )
    assert call(path, auth=("admin", "wrong")).status_code == 401


def test_admin_generation_and_profile_override_rejection(client, inputs):
    r, _ = inputs
    auth = ("admin", "test-only-dedicated-secret-value-12345")
    assert client.get("/", auth=auth).status_code == 200
    response = client.post("/generate", json=asdict(r), auth=auth)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    with ZipFile(BytesIO(response.content)) as bundle:
        assert "REVIEW DRAFT DO NOT RUN" in bundle.read("program.NC").decode()
    assert (
        client.post(
            "/generate", json={**asdict(r), "profile": {}}, auth=auth
        ).status_code
        == 422
    )
    assert (
        client.post("/generate", content='{"finished_bore":NaN}', auth=auth).status_code
        == 422
    )
    assert client.post("/generate", content="x" * 32769, auth=auth).status_code == 413
    assert client.get("/openapi.json").status_code == 404


def test_secret_missing_fails_closed(inputs):
    with pytest.raises(ValueError):
        create_app(admin_key=None, profile=inputs[1])
