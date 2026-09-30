"""Deterministic review bundle. NC is deliberately non-executable by construction."""

from hashlib import sha256
import json
from math import ceil, cos, pi, sin
from . import STATUS, VERSION
from .contract import digest, snapshot

RADIAL_STEP = 0.035
FINISH_STOCK = 0.010
CHORD_TOLERANCE = 0.0002
MAX_POINTS = 20000


def fmt(value):
    return f"{0 if abs(value) < .0000005 else value:.6f}"


def circle(radius, z, *, clockwise=False):
    n = max(72, ceil(pi / (2 * CHORD_TOLERANCE / radius) ** 0.5))
    direction = -1 if clockwise else 1
    return [
        [
            radius * cos(direction * 2 * pi * i / n),
            radius * sin(direction * 2 * pi * i / n),
            z,
        ]
        for i in range(n + 1)
    ]


def plan(record, profile):
    """Tool center paths; stock envelopes are separate from programmed radii."""
    r, p = record, profile
    if r.material != p.approved_material:
        raise ValueError("material has no approved profile cutting parameters")
    tool_r = p.t1_diameter / 2
    blank_min_r = r.actual_blank_bore / 2 - r.blank_radial_uncertainty
    start_r = blank_min_r - tool_r - p.entry_clearance
    finish_r = r.finished_bore / 2 - tool_r
    rough_r = finish_r - FINISH_STOCK
    if start_r <= 0 or rough_r <= 0 or start_r >= rough_r:
        raise ValueError("blank/tool/stock geometry cannot support outward spiral")
    if (
        finish_r - p.finish_lead <= 0
        or p.finish_lead <= FINISH_STOCK + p.max_radial_wear
    ):
        raise ValueError("finish lead must start inside the roughed bore")
    if r.thickness - p.cut_bottom_z > p.t1_flute_length:
        raise ValueError("required axial cut exceeds T1 flute length")
    if p.safe_z <= max(r.thickness, p.clamp_top_z):
        raise ValueError("safe Z must clear plate top and verified clamps")
    # H20 tip datum is physical ball bottom. Keep entire ball on straight wall.
    wall_top = r.thickness - r.top_chamfer_width
    center_low = p.probe_ball_radius + p.probe_edge_margin
    center_high = wall_top - p.probe_ball_radius - p.probe_edge_margin
    if center_low >= center_high:
        raise ValueError("no valid probe depth on straight bore wall for this stylus")
    probe_center_z = (center_low + center_high) / 2
    probe_tip_z = probe_center_z - p.probe_center_from_tip
    if blank_min_r <= p.probe_ball_radius + p.center_error_bound + p.entry_clearance:
        raise ValueError("probe insertion envelope does not fit blank")
    if p.center_error_bound > r.blank_radial_uncertainty:
        raise ValueError("blank uncertainty must include maximum centering shift")
    turns = (rough_r - start_r) / RADIAL_STEP
    angle = 2 * pi * turns
    max_radius = max(rough_r, finish_r, p.t2_max_diameter / 2)
    dtheta = min(pi / 90, (8 * CHORD_TOLERANCE / max_radius) ** 0.5)
    n = ceil(angle / dtheta)
    if n > MAX_POINTS:
        raise ValueError("spiral exceeds bounded review complexity")
    spiral = []
    for i in range(n + 1):
        a = angle * i / n
        radius = start_r + (rough_r - start_r) * i / n
        spiral.append([radius * cos(a), radius * sin(a), p.cut_bottom_z])
    # Continue at final radius to the +X seam, then sweep a complete cleanup circle.
    seam_angle = ceil(angle / (2 * pi)) * 2 * pi
    seam_n = max(1, ceil((seam_angle - angle) / dtheta))
    seam = [
        [
            rough_r * cos(angle + (seam_angle - angle) * i / seam_n),
            rough_r * sin(angle + (seam_angle - angle) * i / seam_n),
            p.cut_bottom_z,
        ]
        for i in range(1, seam_n + 1)
    ]
    rough = spiral + seam + circle(rough_r, p.cut_bottom_z)[1:]
    finish = circle(finish_r, p.cut_bottom_z)
    # CCW G41: positive radial wear moves inward, reducing finished diameter.
    compensated = circle(finish_r - p.radial_wear, p.cut_bottom_z)
    chamfer = []
    chamfer_radius = None
    if r.top_chamfer_width:
        # 90 included angle: cone radius at plate top = tip_r + tip_depth.
        # Intersection at z=top-width occurs at the finished cylindrical bore.
        depth = p.chamfer_tip_depth
        if depth <= r.top_chamfer_width or depth > p.t2_cut_length:
            raise ValueError("chamfer depth outside usable conical edge")
        top_tool_radius = p.t2_tip_diameter / 2 + depth
        if top_tool_radius >= p.t2_max_diameter / 2:
            raise ValueError("chamfer uses tool shoulder or exceeds cutting diameter")
        chamfer_radius = r.finished_bore / 2 + r.top_chamfer_width - top_tool_radius
        if chamfer_radius <= 0 or r.thickness - depth < 0:
            raise ValueError("chamfer tip crosses fixture datum or path radius invalid")
        if p.t2_max_diameter / 2 + p.entry_clearance >= r.finished_bore / 2:
            raise ValueError("chamfer tool cannot enter finished bore at center")
        chamfer = circle(chamfer_radius, r.thickness - depth)
    paths = {
        "rough_tool_center": rough,
        "finish_nominal_tool_center": finish,
        "finish_wear_adjusted_tool_center": compensated,
        "chamfer_tool_center": chamfer,
    }
    paths["rough_entry_nominal"] = [[0, 0, p.safe_z], [0, 0, p.cut_bottom_z], rough[0]]
    paths["finish_radial_lead_in_nominal"] = [
        [finish_r - p.finish_lead, 0, p.cut_bottom_z],
        [finish_r, 0, p.cut_bottom_z],
    ]
    paths["finish_radial_lead_out_nominal"] = list(
        reversed(paths["finish_radial_lead_in_nominal"])
    )
    paths["probe_center_positions"] = [[0, 0, probe_center_z]]
    if chamfer:
        paths["chamfer_entry_nominal"] = [
            [0, 0, p.safe_z],
            [0, 0, r.thickness - p.chamfer_tip_depth],
            chamfer[0],
        ]
    # Verify cutter sweep plus rough centering shift against an approved fixture envelope.
    # Travel uses work-coordinate bounds already transformed for the specific G54 and H tools.
    sweep = (
        max(
            rough_r + tool_r,
            finish_r + tool_r + p.max_radial_wear,
            (chamfer_radius or 0) + p.t2_max_diameter / 2,
        )
        + p.center_error_bound
        + p.probe_overtravel
    )
    if not (
        p.work_x_min <= -sweep
        and sweep <= p.work_x_max
        and p.work_y_min <= -sweep
        and sweep <= p.work_y_max
        and p.work_z_min <= p.cut_bottom_z
        and p.safe_z <= p.work_z_max
    ):
        raise ValueError("tool/probe swept envelope exceeds verified work travel")
    holds = list(p.holds)
    if (
        r.finished_bore / 2 + p.max_radial_wear + p.center_error_bound
        >= p.fixture_opening_radius
    ):
        raise ValueError("bore/tool sweep lacks radial fixture opening clearance")
    if abs(2 * p.radial_wear) > r.bore_tolerance:
        holds.append("entered D wear predicts a bore outside drawing tolerance")
    if p.cut_bottom_z == 0:
        holds.append("verify complete through-bore finish at Z0 without breakthrough")
    return {
        "finished_edge_radius": r.finished_bore / 2,
        "blank_min_radius": blank_min_r,
        "start_center_radius": start_r,
        "rough_end_center_radius": rough_r,
        "finish_center_radius": finish_r,
        "wear_adjusted_bore": r.finished_bore - 2 * p.radial_wear,
        "probe_ball_center_z": probe_center_z,
        "probe_tip_z": probe_tip_z,
        "chamfer_center_radius": chamfer_radius,
        "radial_pitch_per_revolution": RADIAL_STEP,
        "finish_radial_stock": FINISH_STOCK,
        "chord_tolerance": CHORD_TOLERANCE,
        "holds": holds,
        "paths": paths,
        "simulation_limits": [
            "Geometry preview only: not Haas control emulation or collision certification",
            "G41 radial lead transition depends on installed cutter-comp mode and control",
            "Probe internal motions, clamps, holders, toolchange and machine retract require on-machine verification",
        ],
    }


def candidate_blocks(record, profile, geometry):
    r, p, g = record, profile, geometry
    safe, bottom = fmt(p.safe_z), fmt(p.cut_bottom_z)
    probe_z = fmt(g["probe_tip_z"])
    retract = f"G53 G00 Z{fmt(p.retract_machine_z)}"
    blocks = [
        "G20 G17 G90 G94 G40 G49 G80",
        "G54",
        "M05",
        "M09",
        retract,
        "T20 M06",
        f"G43 H{p.t20_h} Z{safe}",
        "G00 X0.000000 Y0.000000",
        "G65 P9832",
        f"G65 P9810 Z{probe_z} F{fmt(p.probe_feed)}",
        f"G65 P9814 D{fmt(r.actual_blank_bore)} Q{fmt(p.probe_overtravel)} S1",
        f"G65 P9810 Z{safe} F{fmt(p.probe_feed)}",
        "G65 P9833",
        retract,
        "T1 M06",
        f"S{p.rough_rpm} M03",
        f"G43 H{p.t1_h} Z{safe}",
        "G00 X0.000000 Y0.000000",
        "M08",
        f"G01 Z{bottom} F{fmt(p.plunge_feed)}",
    ]
    for x, y, _ in g["paths"]["rough_tool_center"]:
        blocks.append(f"G01 X{fmt(x)} Y{fmt(y)} F{fmt(p.rough_feed)}")
    finish = g["finish_center_radius"]
    inside = finish - p.finish_lead
    blocks += [
        f"G01 X{fmt(inside)} Y0.000000 F{fmt(p.finish_feed)}",
        f"S{p.finish_rpm} M03",
        f"G01 G41 D{p.t1_d} X{fmt(finish)} Y0.000000 F{fmt(p.finish_feed)}",
        f"G03 X{fmt(-finish)} Y0.000000 I{fmt(-finish)} J0.000000",
        f"G03 X{fmt(finish)} Y0.000000 I{fmt(finish)} J0.000000",
        f"G01 G40 X{fmt(inside)} Y0.000000",
        f"G00 Z{safe}",
        "M09",
        "M05",
        retract,
    ]
    if r.top_chamfer_width:
        cr = g["chamfer_center_radius"]
        blocks += [
            "T2 M06",
            f"S{p.chamfer_rpm} M03",
            f"G43 H{p.t2_h} Z{safe}",
            "G00 X0.000000 Y0.000000",
            "M08",
            f"G01 Z{fmt(r.thickness-p.chamfer_tip_depth)} F{fmt(p.plunge_feed)}",
            f"G01 X{fmt(cr)} Y0.000000 F{fmt(p.chamfer_feed)}",
            f"G03 X{fmt(-cr)} Y0.000000 I{fmt(-cr)} J0.000000",
            f"G03 X{fmt(cr)} Y0.000000 I{fmt(cr)} J0.000000",
            "G01 X0.000000 Y0.000000",
            f"G00 Z{safe}",
            "M09",
            "M05",
            retract,
        ]
    # No S/T input to P9814: measurement only. Do not assign macro variables.
    blocks += [
        "T20 M06",
        f"G43 H{p.t20_h} Z{safe}",
        "G00 X0.000000 Y0.000000",
        "G65 P9832",
        f"G65 P9810 Z{probe_z} F{fmt(p.probe_feed)}",
        f"G65 P9814 D{fmt(r.finished_bore)} Q{fmt(p.probe_overtravel)}",
        "M00",  # operator records #188 before another cycle overwrites it
        f"G65 P9810 Z{safe} F{fmt(p.probe_feed)}",
        "G65 P9833",
        retract,
        "M30",
    ]
    return blocks


def path_svg(record, geometry):
    radius = record.finished_bore / 2 + record.top_chamfer_width + 0.3

    def poly(points, color):
        xy = " ".join(f"{fmt(x)},{fmt(-y)}" for x, y, _ in points)
        return f'<polyline points="{xy}" fill="none" stroke="{color}" stroke-width=".003"/>'

    result = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-radius} {-radius} {2*radius} {2*radius}">',
        '<rect x="-100" y="-100" width="200" height="200" fill="white"/>',
    ]
    for rad, color in (
        (record.actual_blank_bore / 2, "#777"),
        (record.finished_bore / 2, "#111"),
    ):
        result.append(
            f'<circle r="{fmt(rad)}" fill="none" stroke="{color}" stroke-width=".006"/>'
        )
    for key, color in (
        ("rough_tool_center", "#2874a6"),
        ("finish_nominal_tool_center", "#148f77"),
        ("finish_wear_adjusted_tool_center", "#b7950b"),
        ("chamfer_tool_center", "#884ea0"),
    ):
        result.append(poly(geometry["paths"][key], color))
    result.append("</svg>")
    return "\n".join(result) + "\n"


def generate(record, profile):
    g = plan(record, profile)
    inputs = snapshot(record, profile)
    record_hash, profile_hash = digest(inputs["record"]), digest(inputs["profile"])
    nc = [
        "%",
        "O09001",
        f"({STATUS})",
        f"(GENERATOR {VERSION})",
        f"(JOB {record.job_id} PART {record.part_id} REV {record.drawing_revision})",
        f"(RECORD SHA256 {record_hash})",
        f"(PROFILE SHA256 {profile_hash})",
        "#3000=1 (REVIEW DRAFT DO NOT RUN)",
        "M30",
        "(EVERY CANDIDATE BLOCK BELOW IS COMMENTED - NO MACHINE RELEASE)",
        "(Z0 PLATE BOTTOM - G54 Z IS FIXTURE DATUM)",
        "(T1 HELICAL 59845W - T2 HELICAL 07029 - T20 WIPS)",
        "(G41 D IS WEAR ONLY - G43 H IS TOOL LENGTH)",
        "(FINISH CCW G41 - POSITIVE WEAR REDUCES BORE)",
        "(FINAL M00 RECORD MEASURED DIAMETER VARIABLE 188 BEFORE CONTINUING)",
    ]
    nc += [f"(HOLD {hold})" for hold in g["holds"]]
    nc += [f"({block})" for block in candidate_blocks(record, profile, g)]
    nc += ["%", ""]
    setup = [
        f"# {STATUS}",
        f"Generator: {VERSION}",
        f"Job: {record.job_id}; part: {record.part_id}; drawing: {record.drawing_revision}",
        f"Record SHA256: {record_hash}",
        f"Profile SHA256: {profile_hash}",
        f"Reviewed by: {record.reviewed_by}; reference: {record.review_reference}",
        f"Source: {record.source_kind}; SHA256: {record.source_sha256}",
        f"Machine: {profile.machine_id}; control: {profile.control_version}",
        f"Profile verifier: {profile.verified_by or 'UNVERIFIED'}",
        "",
        "Z0 = plate bottom / fixture datum; G54 Z must remain unchanged.",
        "Load T20 WIPS, T1 59845W, T2 07029; verify holders, stickout, calibration and H offsets.",
        f"H offsets T1/T2/T20: {profile.t1_h}/{profile.t2_h}/{profile.t20_h}",
        f"Setting 40: {profile.setting40}; D{profile.t1_d} geometry=0; wear={profile.t1_d_wear}",
        f"Cut Z={profile.cut_bottom_z}; verified fixture clearance below={profile.fixture_clearance_below}",
        f"Probe ball center Z={fmt(g['probe_ball_center_z'])}; programmed physical tip Z={fmt(g['probe_tip_z'])}",
        f"Rough center endpoint={fmt(g['rough_end_center_radius'])}; finish center radius={fmt(g['finish_center_radius'])}",
        "Rough spiral pitch .035 radial/revolution; cleanup circle leaves .010 radial finish stock.",
        "Pitch is not a claim of constant instantaneous cutter engagement or validated chip load.",
        f"Expected wear-adjusted diameter={fmt(g['wear_adjusted_bore'])}",
        f"Feeds/RPM rough: {profile.rough_feed}/{profile.rough_rpm}; finish: {profile.finish_feed}/{profile.finish_rpm}; chamfer: {profile.chamfer_feed}/{profile.chamfer_rpm}",
        "Final probe cycle has no S or T argument. Record #188 at M00; no automatic correction/recut.",
        "Inspection is a blank operator form, not evidence a measurement occurred.",
        "Top bore edge chamfer only; width is radial and angle is 45 degrees from plate face.",
        "",
        "HOLD findings:",
    ] + [f"- {h}" for h in g["holds"]]
    setup += ["", "Simulation limitations:"] + [
        f"- {h}" for h in g["simulation_limits"]
    ]
    setup += [
        "",
        "Before machine use: programmer reviews the exact hashed bundle, verifies the actual setup,",
        "and performs a controlled prove-out under shop procedure. This generator has no release operation.",
        "NC candidate is entirely commented after an alarm and M30. Do not strip guards to treat it as approved.",
    ]
    inspection = [
        f"# {STATUS}",
        "Bore inspection record - UNMEASURED",
        f"Job: {record.job_id}",
        f"Part: {record.part_id}; drawing revision: {record.drawing_revision}",
        f"Record SHA256: {record_hash}; profile SHA256: {profile_hash}",
        f"Nominal bore: {record.finished_bore} inch; tolerance +/- {record.bore_tolerance}",
        f"Acceptable diameter: {record.finished_bore-record.bore_tolerance:.6f} to {record.finished_bore+record.bore_tolerance:.6f} inch",
        f"Probe contact center Z: {g['probe_ball_center_z']:.6f}",
        "Unit/serial: __________  Operator: __________  Date: __________",
        "Probe calibration/reference: __________  WIPS #188 diameter: __________",
        "Independent gauge/reference: __________  Independent measured diameter: __________",
        "Pass/fail/hold: __________  Notes: __________",
        "No automatic recutting or tool/work-offset correction authorized.",
    ]
    files = {
        "program.NC": "\n".join(nc),
        "setup.md": "\n".join(setup) + "\n",
        "inspection.md": "\n".join(inspection) + "\n",
        "paths.svg": path_svg(record, g),
        "simulation.json": json.dumps(g, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        "inputs.json": json.dumps(inputs, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
    }
    manifest = {
        "status": STATUS,
        "generator_version": VERSION,
        "record_sha256": record_hash,
        "profile_sha256": profile_hash,
        "holds": g["holds"],
        "files": {
            name: sha256(text.encode("ascii")).hexdigest()
            for name, text in files.items()
        },
    }
    files["manifest.json"] = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    return files
