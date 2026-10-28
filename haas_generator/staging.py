"""Automatic internal NC post from frozen geometry and controlled setup profiles.

A nominal rough blank is NEVER represented as a measured blank. Numerical
validation cannot qualify machine/setup safety. The unconditional alarm stays.
"""

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from .contract import label, number, digest
from .engineering import engineering_bundle
from .generator import candidate_blocks, plan
from plate_geometry import rough_bore_diameter

VERSION = "haas-frozen-staging-1"


@dataclass(frozen=True)
class FixtureProfile:
    version: str
    fixture_id: str
    fixture_revision: str
    machine_profile_revision: str
    orientation_reference: str
    top_face_policy: str
    nominal_blank_radial_uncertainty: float
    program_number: int

    def __post_init__(self):
        for k in (
            "version",
            "fixture_id",
            "fixture_revision",
            "machine_profile_revision",
            "orientation_reference",
        ):
            label(k, getattr(self, k))
        if self.top_face_policy != "APPROVED_CHAMFER_SIDE_UP":
            raise ValueError("unsupported controlled face convention")
        number("blank envelope", self.nominal_blank_radial_uncertainty, positive=True)
        if self.nominal_blank_radial_uncertainty > 0.05:
            raise ValueError("blank envelope outside bounded strategy")
        if type(self.program_number) is not int or not 1 <= self.program_number <= 8999:
            raise ValueError("controlled nonreserved program number required")


@dataclass(frozen=True)
class FrozenRecord:
    job_id: str
    part_id: str
    drawing_revision: str
    source_sha256: str
    finished_bore: float
    bore_tolerance: float
    nominal_blank_bore: float
    blank_radial_uncertainty: float
    thickness: float
    material: str
    top_chamfer_width: float
    quantity: int
    source_kind: str = field(default="approved-frozen-plate", init=False)
    blank_basis: str = field(default="NOMINAL TARGET - NOT A MEASUREMENT", init=False)
    units: str = field(default="inch", init=False)

    @property
    def actual_blank_bore(self):
        # Compatibility with the accepted path planner only. Persisted inputs
        # name this nominal_blank_bore, with explicit unmeasured provenance.
        return self.nominal_blank_bore


def generate(spec, machine, fixture, parameters, parent):
    if spec.chamfer is None or (
        spec.chamfer
        and (
            spec.chamfer_angle_degrees != 45
            or spec.chamfer_width_definition != "radial-angle-from-face"
            or spec.chamfer_side not in ("upstream", "downstream")
        )
    ):
        raise ValueError("supported exact chamfer geometry required")
    r = FrozenRecord(
        job_id=parent["order_id"],
        part_id=spec.part_identifier,
        drawing_revision=parent["revision"],
        source_sha256=parent["spec_sha256"],
        finished_bore=spec.finished_bore_diameter,
        bore_tolerance=spec.bore_tolerance,
        nominal_blank_bore=rough_bore_diameter(spec),
        blank_radial_uncertainty=fixture.nominal_blank_radial_uncertainty,
        thickness=spec.thickness,
        material=spec.material,
        top_chamfer_width=spec.chamfer_width if spec.chamfer else 0,
        quantity=spec.quantity,
    )
    if (
        r.nominal_blank_bore + 2 * r.blank_radial_uncertainty
        >= r.finished_bore - r.bore_tolerance
    ):
        raise ValueError(
            "controlled blank envelope leaves insufficient machining stock"
        )
    setup = dict(
        top_face_side=spec.chamfer_side if spec.chamfer else "upstream",
        fixture_orientation_reference=fixture.orientation_reference,
    )
    files = engineering_bundle(r, machine, parameters, parent, setup_context=setup)
    inputs = json.loads(files["inputs.json"])
    inputs.update(
        engineering_version=inputs["generator_version"],
        generator_version=VERSION,
        fixture_profile=asdict(fixture),
        machine_profile_revision=fixture.machine_profile_revision,
    )
    fingerprint = digest(inputs)
    geometry = plan(r, machine, parameters)
    # This is a complete motion program behind an unconditional alarm, rather
    # than the older commented draft after an early M30. There is no automatic
    # transition to an unguarded program, even for a verified profile.
    files["program.NC"] = "\n".join(
        [
            "%",
            f"O{fixture.program_number:05d}",
            "(REVIEW / SETUP VERIFICATION REQUIRED)",
            "#3000=1 (SETUP PROVE OUT REQUIRED)",
            "M00",
            f"(ORDER {r.job_id})",
            f"(PLATE {parent['plate_id']})",
            f"(FROZEN REVISION {parent['revision_id']})",
            f"(SPEC SHA256 {r.source_sha256})",
            f"(MACHINE PROFILE REV {fixture.machine_profile_revision})",
            f"(MACHINE PROFILE SHA256 {digest(asdict(machine))})",
            f"(FIXTURE PROFILE REV {fixture.fixture_revision})",
            f"(FIXTURE PROFILE SHA256 {digest(asdict(fixture))})",
            f"(INPUT SHA256 {fingerprint})",
            f"(GENERATOR {VERSION})",
            f"(QUANTITY {r.quantity} - ONE PART PER MANUAL CYCLE)",
            "(NOMINAL ROUGH BORE - NOT MEASURED - VERIFY BLANK ENVELOPE)",
            "(T20 CENTER G54 XY ONLY - G54 Z REMAINS FIXTURE DATUM)",
            "(G41 D WEAR ONLY - G43 H TOOL LENGTH)",
            "(NO AUTOMATIC RECUT OR WEAR ADJUSTMENT)",
        ]
        + [f"(HOLD {h})" for h in geometry["holds"]]
        + candidate_blocks(r, machine, geometry)
        + ["%", ""]
    )
    readiness = json.loads(files["readiness.json"])
    readiness.update(
        state="SETUP VERIFICATION REQUIRED",
        input_sha256=fingerprint,
        holds=readiness["holds"]
        + [
            "verify nominal blank envelope against the physical blank",
            "independent programmer review and physical prove-out required",
        ],
        engineering_review_completed=False,
        physical_validation_completed=False,
        manufacturing_release_enabled=False,
        release_eligible=False,
    )
    files["readiness.json"] = json.dumps(readiness, sort_keys=True, indent=2) + "\n"
    files["inputs.json"] = json.dumps(inputs, sort_keys=True, indent=2) + "\n"
    files["setup.md"] = files["setup.md"].replace(
        "NC candidate is entirely commented after an alarm and M30. Do not strip guards to treat it as approved.",
        "NC contains complete motion blocks behind an unconditional setup alarm. It is not machine-approved; preserve the alarm pending controlled programmer review and physical prove-out.",
    )
    files["setup.md"] += (
        "\nAutomatic staging uses nominal Frozen Plate rough-blank geometry, NOT measured blank evidence.\n"
        + f"Automatic generator: {VERSION}; controlled fixture profile: {fixture.version}; machine revision: {fixture.machine_profile_revision}.\nInput fingerprint: {fingerprint}\n"
    )
    manifest = dict(
        generator_version=VERSION,
        parent=parent,
        input_sha256=fingerprint,
        state="SETUP VERIFICATION REQUIRED",
        files={
            k: dict(
                size=len(v.encode("ascii")),
                sha256=sha256(v.encode("ascii")).hexdigest(),
            )
            for k, v in sorted(files.items())
            if k != "manifest.json"
        },
    )
    files["manifest.json"] = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    return {k: v.encode("ascii") for k, v in files.items()}
