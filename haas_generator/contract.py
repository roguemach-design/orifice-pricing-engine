"""Strict, versioned manufacturing record and server-owned machine profile."""

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
from math import isfinite
import re


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode("ascii")).hexdigest()


def number(name, value, *, positive=False):
    if type(value) not in (int, float):
        raise ValueError(f"{name}: finite numeric value required")
    if abs(value) > 100000:
        raise ValueError(f"{name}: outside bounded generator range")
    if not isfinite(value):
        raise ValueError(f"{name}: finite numeric value required")
    if positive and value <= 0:
        raise ValueError(f"{name}: positive value required")


def label(name, value):
    # Cannot escape an NC comment, inject code, HTML or a file path.
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9 _.:+-]{1,100}", value
    ):
        raise ValueError(f"{name}: 1-100 safe ASCII characters required")


def construct(cls, data):
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__}: object required")
    unexpected = set(data) - {f.name for f in fields(cls)}
    if unexpected:
        raise ValueError(f"{cls.__name__}: unknown fields: {sorted(unexpected)}")
    try:
        return cls(**data)
    except TypeError as exc:
        raise ValueError(f"{cls.__name__}: missing or invalid fields") from exc


def loads(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        text,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )


@dataclass(frozen=True)
class ReviewedRecord:
    schema_version: str
    units: str
    job_id: str
    part_id: str
    drawing_revision: str
    source_kind: str
    source_sha256: str
    reviewed_by: str
    review_reference: str
    finished_bore: float
    bore_tolerance: float  # symmetric +/- diametral
    actual_blank_bore: float  # measured minimum inscribed diameter
    blank_radial_uncertainty: float  # taper/ovality/centering error bound
    thickness: float
    material: str
    top_chamfer_width: float  # radial width, 45 degrees from face; zero means none

    def __post_init__(self):
        if self.schema_version != "1" or self.units != "inch":
            raise ValueError("schema_version=1 and explicit inch units required")
        for name in (
            "job_id",
            "part_id",
            "drawing_revision",
            "reviewed_by",
            "review_reference",
            "material",
        ):
            label(name, getattr(self, name))
        if self.source_kind not in (
            "intake",
            "print-recognition",
            "dxf-import",
            "manual",
        ):
            raise ValueError("unsupported source kind")
        if not isinstance(self.source_sha256, str) or not re.fullmatch(
            "[0-9a-f]{64}", self.source_sha256
        ):
            raise ValueError("source SHA256 required")
        for name in (
            "finished_bore",
            "bore_tolerance",
            "actual_blank_bore",
            "thickness",
        ):
            number(name, getattr(self, name), positive=True)
        for name in ("blank_radial_uncertainty", "top_chamfer_width"):
            number(name, getattr(self, name))
            if getattr(self, name) < 0:
                raise ValueError(f"{name}: nonnegative required")
        if self.bore_tolerance >= self.finished_bore:
            raise ValueError("invalid bore tolerance")
        if (
            self.actual_blank_bore + 2 * self.blank_radial_uncertainty
            >= self.finished_bore - self.bore_tolerance
        ):
            raise ValueError("blank stock envelope exceeds minimum finished bore")
        if self.top_chamfer_width >= self.thickness:
            raise ValueError("chamfer would consume the straight bore wall")


CHECKS = (
    "machine_identity_and_control",
    "fixture_and_clamp_clearance",
    "g54_fixture_z",
    "travel_and_toolchange",
    "tool_geometry_and_h_offsets",
    "setting40_and_d_wear",
    "material_feeds_and_spindle",
    "wips_calibration_and_macros",
    "probe_xy_only",
    "probe_measurement_only",
    "probe_result_variable",
    "rough_bore_envelope",
)


@dataclass(frozen=True)
class MachineProfile:
    schema_version: str
    profile_id: str
    machine_id: str
    control_version: str
    approved_material: str
    verified_by: str | None
    evidence: dict[str, str]
    setting40: str
    t1_diameter: float
    t1_flute_length: float
    t1_h: int
    t1_d: int
    t1_d_geometry: float
    t1_d_wear: float
    max_radial_wear: float
    t2_tip_diameter: float
    t2_included_angle: float
    t2_cut_length: float
    t2_max_diameter: float
    t2_h: int
    t20_h: int
    probe_ball_radius: float
    probe_center_from_tip: float  # H20 is calibrated to physical ball bottom
    probe_edge_margin: float
    probe_overtravel: float
    center_error_bound: float
    probe_feed: float
    safe_z: float
    retract_machine_z: float
    cut_bottom_z: float
    fixture_clearance_below: float
    fixture_opening_radius: float
    clamp_top_z: float
    entry_clearance: float
    finish_lead: float
    chamfer_tip_depth: float  # measured below plate top at physical flat tip
    rough_rpm: int
    rough_feed: float
    plunge_feed: float
    finish_rpm: int
    finish_feed: float
    chamfer_rpm: int
    chamfer_feed: float
    max_rpm: int
    max_feed: float
    work_x_min: float
    work_x_max: float
    work_y_min: float
    work_y_max: float
    work_z_min: float
    work_z_max: float

    def __post_init__(self):
        if self.schema_version != "1" or self.setting40 not in ("RADIUS", "DIAMETER"):
            raise ValueError("unsupported profile schema or Setting 40")
        for name in (
            "profile_id",
            "machine_id",
            "control_version",
            "approved_material",
        ):
            label(name, getattr(self, name))
        if self.verified_by is not None:
            label("verified_by", self.verified_by)
        if not isinstance(self.evidence, dict) or set(self.evidence) - set(CHECKS):
            raise ValueError("unknown verification evidence")
        for key, value in self.evidence.items():
            label(key, value)
        integer_names = (
            "t1_h",
            "t1_d",
            "t2_h",
            "t20_h",
            "rough_rpm",
            "finish_rpm",
            "chamfer_rpm",
            "max_rpm",
        )
        for name in integer_names:
            value = getattr(self, name)
            if (
                type(value) is not int
                or value < 1
                or (name.endswith("_h") or name == "t1_d")
                and value > 200
            ):
                raise ValueError(f"{name}: invalid integer")
        nonnumeric = {
            "schema_version",
            "profile_id",
            "machine_id",
            "control_version",
            "approved_material",
            "verified_by",
            "evidence",
            "setting40",
        }
        for f in fields(self):
            if f.name not in nonnumeric:
                number(f.name, getattr(self, f.name))
        for name in (
            "t1_diameter",
            "t1_flute_length",
            "max_radial_wear",
            "t2_tip_diameter",
            "t2_cut_length",
            "t2_max_diameter",
            "probe_ball_radius",
            "probe_edge_margin",
            "probe_overtravel",
            "probe_feed",
            "entry_clearance",
            "finish_lead",
            "chamfer_tip_depth",
            "rough_feed",
            "plunge_feed",
            "finish_feed",
            "chamfer_feed",
            "max_feed",
            "fixture_opening_radius",
        ):
            number(name, getattr(self, name), positive=True)
        if self.fixture_clearance_below < 0 or self.center_error_bound < 0:
            raise ValueError("negative clearance/error bound")
        if abs(self.t1_diameter - 0.5) > 0.002 or self.t1_flute_length > 0.625:
            raise ValueError("T1 must match measured nominal half-inch 59845W geometry")
        if (
            self.t2_included_angle != 90
            or abs(self.t2_tip_diameter - 0.080) > 0.002
            or self.t2_cut_length > 0.210
        ):
            raise ValueError("T2 must match measured 07029 geometry")
        if self.t2_max_diameter > 0.5 or self.t2_max_diameter <= self.t2_tip_diameter:
            raise ValueError("invalid chamfer cutter diameter")
        if self.probe_center_from_tip != self.probe_ball_radius:
            raise ValueError("only ball-bottom H20 calibration supported")
        if len({self.t1_h, self.t2_h, self.t20_h}) != 3:
            raise ValueError("tool H offsets must be distinct")
        if self.t1_d_geometry != 0:
            raise ValueError(
                "wear-only requires D geometry zero, not nominal tool diameter"
            )
        if (
            abs(self.radial_wear) > self.max_radial_wear
            or self.max_radial_wear >= 0.010
        ):
            raise ValueError("D wear exceeds finish-stock budget")
        if self.finish_lead <= self.max_radial_wear:
            raise ValueError("compensation lead shorter than allowable wear")
        if self.cut_bottom_z > 0:
            raise ValueError("through-bore bottom must be at or below fixture datum")
        if self.cut_bottom_z < -self.fixture_clearance_below:
            raise ValueError("below-datum cutting lacks fixture clearance")
        if self.retract_machine_z > 0:
            raise ValueError("invalid machine Z retract")
        for axis in "xyz":
            if getattr(self, f"work_{axis}_min") >= getattr(self, f"work_{axis}_max"):
                raise ValueError("invalid verified work-coordinate travel envelope")
        if max(self.rough_rpm, self.finish_rpm, self.chamfer_rpm) > self.max_rpm:
            raise ValueError("spindle limit exceeded")
        if (
            max(
                self.rough_feed,
                self.finish_feed,
                self.chamfer_feed,
                self.plunge_feed,
                self.probe_feed,
            )
            > self.max_feed
        ):
            raise ValueError("feed limit exceeded")

    @property
    def radial_wear(self):
        return self.t1_d_wear / (2 if self.setting40 == "DIAMETER" else 1)

    @property
    def holds(self):
        return (["machine profile has no verifier"] if not self.verified_by else []) + [
            f"verify {key}" for key in CHECKS if not self.evidence.get(key)
        ]


def from_dict(record, profile):
    return construct(ReviewedRecord, record), construct(MachineProfile, profile)


def snapshot(record, profile):
    return {"record": asdict(record), "profile": asdict(profile)}
