"""Versioned engineering workflow. No manufacturing release or machine transport."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import hypot
import json
from .contract import digest, number, label, snapshot
from .generator import plan, generate, candidate_blocks, path_svg

VERSION = "haas-engineering-2"
POST_VERSION = "haas-inspection-plus-candidate-1"
STATES = (
    "DRAFT",
    "ENGINEERING REVIEW",
    "SETUP VERIFICATION REQUIRED",
    "SIMULATION VERIFIED",
    "MACHINE PROVE-OUT REQUIRED",
    "APPROVED FOR MANUFACTURING",
)


@dataclass(frozen=True)
class Parameters:
    version: str
    radial_step: float
    finish_stock: float
    chord_tolerance: float

    def __post_init__(self):
        label("parameter version", self.version)
        for name, low, high in [
            ("radial_step", 0.001, 0.035),
            ("finish_stock", 0.002, 0.020),
            ("chord_tolerance", 0.00001, 0.0002),
        ]:
            v = getattr(self, name)
            number(name, v)
            if not low <= v <= high:
                raise ValueError(f"{name} outside reviewed strategy bounds")


def verify_geometry(record, profile, geometry):
    """Separately derive swept-edge and straight-wall bounds from exported points.

    This is numeric path verification, never control simulation/collision certification.
    """
    r, p, g = record, profile, geometry
    checks = {}
    rr = [hypot(x, y) for x, y, z in g["paths"]["rough_tool_center"]]
    checks["rough_swept_edge"] = (
        abs(
            max(rr) + p.t1_diameter / 2 + g["finish_radial_stock"] - r.finished_bore / 2
        )
        < 1e-8
    )
    checks["entry_clearance"] = (
        g["start_center_radius"] + p.t1_diameter / 2
        < r.actual_blank_bore / 2 - r.blank_radial_uncertainty
    )
    edge = [
        2 * hypot(x, y) + p.t1_diameter
        for x, y, z in g["paths"]["finish_wear_adjusted_tool_center"]
    ]
    checks["finish_diameter"] = all(
        abs(v - r.finished_bore) <= r.bore_tolerance + 1e-8 for v in edge
    )
    checks["probe_straight_wall"] = (
        g["probe_ball_center_z"] - p.probe_ball_radius > 0
        and g["probe_ball_center_z"] + p.probe_ball_radius
        < r.thickness - r.top_chamfer_width
    )
    checks["z_and_flutes"] = all(
        p.work_z_min <= z <= p.work_z_max and r.thickness - z <= p.t1_flute_length
        for key in ("rough_tool_center", "finish_wear_adjusted_tool_center")
        for x, y, z in g["paths"][key]
    )
    checks["fixture"] = all(
        hypot(x, y) + p.t1_diameter / 2 + p.center_error_bound
        < p.fixture_opening_radius
        for key in ("rough_tool_center", "finish_wear_adjusted_tool_center")
        for x, y, z in g["paths"][key]
    )
    checks["chamfer_intersection"] = all(
        abs(
            hypot(x, y)
            + p.t2_tip_diameter / 2
            + (r.thickness - z)
            - r.top_chamfer_width
            - r.finished_bore / 2
        )
        < 1e-8
        for x, y, z in g["paths"]["chamfer_tool_center"]
    )
    if not all(checks.values()):
        raise ValueError(
            "independent geometric verification failed: "
            + str([k for k, v in checks.items() if not v])
        )
    return {
        "checks": checks,
        "scope": "NUMERICAL GEOMETRY ONLY",
        "physical_validation": False,
    }


def engineering_bundle(record, profile, parameters, parent, *, setup_context=None):
    if not 0.125 <= record.thickness <= 0.5:
        raise ValueError("engineering thickness scope .125-.500 inch")
    g = plan(record, profile, parameters)
    if setup_context is not None:
        if set(setup_context) != {
            "top_face_side",
            "fixture_orientation_reference",
        } or setup_context["top_face_side"] not in ("upstream", "downstream"):
            raise ValueError("explicit fixture orientation context required")
        label(
            "fixture_orientation_reference",
            setup_context["fixture_orientation_reference"],
        )
    if record.top_chamfer_width and setup_context is None:
        g["holds"].append(
            "verify chamfer top face against drawing and fixture orientation"
        )
    verification = verify_geometry(record, profile, g)
    files = generate(
        record, profile, parameters
    )  # Preserve review-only guards; replace path-dependent content below.
    inputs = {
        **snapshot(record, profile),
        "parameters": asdict(parameters),
        "setup_context": setup_context,
        "parent": parent,
        "generator_version": VERSION,
        "post_version": POST_VERSION,
    }
    fingerprint = digest(inputs)
    blocks = candidate_blocks(record, profile, g)
    files["program.NC"] = "\n".join(
        [
            "%",
            "O09001",
            "(ENGINEERING REVIEW - DO NOT RUN)",
            "#3000=1 (ENGINEERING HOLD)",
            "M30",
            f"(INPUT SHA256 {fingerprint})",
        ]
        + [f"({b})" for b in blocks]
        + ["%", ""]
    )
    files["inputs.json"] = json.dumps(inputs, sort_keys=True, indent=2) + "\n"
    files["simulation.json"] = json.dumps(g, sort_keys=True, indent=2) + "\n"
    files["paths.svg"] = path_svg(record, g)
    # Remove fixed v1 strategy text; report actual v2 values.
    files["setup.md"] = files["setup.md"].replace(
        "Rough spiral pitch .035 radial/revolution; cleanup circle leaves .010 radial finish stock.",
        f"Rough pitch {parameters.radial_step}; radial finish stock {parameters.finish_stock} inch.",
    )
    files[
        "setup.md"
    ] += f"\nEngineering version: {VERSION}\nInput fingerprint: {fingerprint}\nParent: {json.dumps(parent,sort_keys=True)}\n"
    files[
        "setup.md"
    ] += f"\nFixture orientation context: {json.dumps(setup_context,sort_keys=True)}\n"
    files["verification.json"] = (
        json.dumps(verification, sort_keys=True, indent=2) + "\n"
    )
    state = "SETUP VERIFICATION REQUIRED" if g["holds"] else "ENGINEERING REVIEW"
    files["readiness.json"] = (
        json.dumps(
            {
                "state": state,
                "geometry_verified": True,
                "simulation_verified": False,
                "engineering_review_completed": False,
                "physical_validation_completed": False,
                "release_eligible": False,
                "manufacturing_release_enabled": False,
                "holds": g["holds"],
                "input_sha256": fingerprint,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    files.pop("manifest.json")
    files["manifest.json"] = (
        json.dumps(
            {
                "generator_version": VERSION,
                "post_version": POST_VERSION,
                "input_sha256": fingerprint,
                "parent": parent,
                "state": state,
                "files": {
                    k: {
                        "sha256": sha256(v.encode("ascii")).hexdigest(),
                        "size": len(v.encode("ascii")),
                    }
                    for k, v in sorted(files.items())
                },
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    return files


def post_candidate(
    record,
    profile,
    parameters,
    parent,
    *,
    authorization,
    generator_actor,
    setup_context=None,
):
    """Offline trusted programmer workflow, never exposed by HTTP.

    Authorization is supplied by the shop evidence adapter, not a customer boolean.
    Produces a prove-out candidate, NEVER an approved production program.
    """
    if profile.holds:
        raise ValueError("verified machine/setup profile required")
    required = {
        "programmer",
        "evidence_reference",
        "input_sha256",
        "profile_sha256",
        "post_version",
        "program_number",
    }
    if set(authorization) != required:
        raise ValueError("complete independent programmer authorization required")
    if (
        type(authorization["program_number"]) is not int
        or not 1 <= authorization["program_number"] <= 8999
    ):
        raise ValueError("explicit verified nonreserved program number required")
    for key in ("programmer", "evidence_reference"):
        label(key, authorization[key])
    bundle = engineering_bundle(
        record, profile, parameters, parent, setup_context=setup_context
    )
    manifest = json.loads(bundle["manifest.json"])
    if (
        authorization["programmer"] == generator_actor
        or authorization["input_sha256"] != manifest["input_sha256"]
        or authorization["profile_sha256"] != digest(asdict(profile))
        or authorization["post_version"] != POST_VERSION
    ):
        raise ValueError(
            "authorization identity or exact input/post fingerprint mismatch"
        )
    g = plan(record, profile, parameters)
    if json.loads(bundle["readiness.json"])["holds"]:
        raise ValueError("unresolved engineering holds")
    # Deliberately distinct from review NC; absence of alarm is not release authority.
    nc = "\n".join(
        [
            "%",
            f"O{authorization['program_number']:05d}",
            "(PROVE OUT CANDIDATE - NOT MANUFACTURING APPROVED)",
            f"(INPUT SHA256 {manifest['input_sha256']})",
            "M00",
        ]
        + candidate_blocks(record, profile, g)
        + ["%", ""]
    )
    return {
        "candidate.NC": nc,
        "candidate-authorization.json": json.dumps(
            {
                **authorization,
                "candidate_sha256": sha256(nc.encode("ascii")).hexdigest(),
                "state": "MACHINE PROVE-OUT REQUIRED",
                "manufacturing_release_enabled": False,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
    }
