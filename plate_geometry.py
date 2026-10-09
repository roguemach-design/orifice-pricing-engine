"""Canonical inch geometry. No display clamps, I/O, CAD or model dependency."""

from dataclasses import dataclass, asdict
from decimal import Decimal
from math import atan2, isfinite, pi, sqrt, tan
from typing import Mapping
from manufacturing_context import PlateApplication, application_context

ROUGH_BORE_DIAMETER_ALLOWANCE = 0.125
CORNER_RADIUS = 0.03125
GEOMETRY_VERSION = "straight-handle-r03125-v2-prototype"


@dataclass(frozen=True)
class PlateSpec:
    finished_od: float
    finished_bore_diameter: float
    handle_width: float
    centerline_to_handle_end: float
    material: str
    thickness: float
    bore_tolerance: float | None = None  # symmetric +/- inches
    chamfer: bool | None = None
    chamfer_width: float | None = None
    chamfer_angle_degrees: float | None = None
    chamfer_side: str | None = None
    flow_orientation: str | None = None
    chamfer_width_definition: str | None = None
    marking: str | None = None
    quantity: int = 1
    part_identifier: str = "sample-plate"
    handle_hole_enabled: bool = False
    handle_hole_diameter: float | None = None
    handle_hole_center_from_handle_end: float | None = None
    application: PlateApplication = PlateApplication.RESTRICTION_GENERAL

    def __post_init__(self):
        object.__setattr__(self, "application", PlateApplication(self.application))
        for name in (
            "finished_od",
            "finished_bore_diameter",
            "handle_width",
            "centerline_to_handle_end",
            "thickness",
            "bore_tolerance",
            "chamfer_width",
            "chamfer_angle_degrees",
        ):
            value = getattr(self, name)
            if value is None and name in (
                "bore_tolerance",
                "chamfer_width",
                "chamfer_angle_degrees",
            ):
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        validate_handle_hole(
            self.finished_od, self.handle_width, self.centerline_to_handle_end,
            self.handle_hole_enabled, self.handle_hole_diameter,
            self.handle_hole_center_from_handle_end,
        )
        if self.finished_bore_diameter >= self.finished_od:
            raise ValueError("finished bore must be smaller than OD")
        if self.handle_width >= self.finished_od:
            raise ValueError("straight-handle prototype requires handle width < OD")
        if self.centerline_to_handle_end <= self.finished_od / 2:
            raise ValueError("handle end must extend beyond plate radius")
        if self.bore_tolerance is not None and (
            self.finished_bore_diameter - self.bore_tolerance <= 0
            or self.finished_bore_diameter + self.bore_tolerance >= self.finished_od
        ):
            raise ValueError("bore tolerance envelope must remain inside plate")
        if type(self.quantity) is not int or self.quantity < 1:
            raise ValueError("quantity must be a positive integer")
        if self.chamfer is not None and type(self.chamfer) is not bool:
            raise ValueError("chamfer must be boolean or unspecified")
        if self.chamfer is not True and any(
            v is not None
            for v in (self.chamfer_width, self.chamfer_angle_degrees, self.chamfer_side)
        ):
            raise ValueError("chamfer details require chamfer=True")
        if self.chamfer_angle_degrees is not None and self.chamfer_angle_degrees >= 90:
            raise ValueError("chamfer angle must be below 90 degrees")
        if self.flow_orientation not in (None, "left-to-right", "right-to-left"):
            raise ValueError("unsupported flow_orientation")
        if self.chamfer_side not in (None, "upstream", "downstream"):
            raise ValueError("unsupported chamfer_side")
        if self.chamfer_width_definition not in (
            None,
            "radial-angle-from-face",
            "axial-depth-angle-from-face",
        ):
            raise ValueError("unsupported chamfer_width_definition")
        for name, limit in (
            ("material", 40),
            ("part_identifier", 40),
            ("marking", 40),
            ("chamfer_side", 25),
        ):
            value = getattr(self, name)
            if value is None and name in ("marking", "chamfer_side"):
                continue
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
                or not value.isascii()
                or any(ord(c) < 32 for c in value)
            ):
                raise ValueError(
                    f"{name} must be printable ASCII, 1-{limit} characters"
                )

    @classmethod
    def from_configuration(cls, data: Mapping, *, part_identifier="sample-plate"):
        """Adapter for existing normalized quote/order keys; no pricing dependency."""
        return cls(
            finished_od=data["paddle_dia"],
            finished_bore_diameter=data["bore_dia"],
            handle_width=data["handle_width"],
            centerline_to_handle_end=data["handle_length_from_bore"],
            material=data["material"],
            thickness=data["thickness"],
            bore_tolerance=data.get("bore_tolerance"),
            chamfer=data.get("chamfer"),
            chamfer_width=data.get("chamfer_width"),
            chamfer_angle_degrees=data.get("chamfer_angle_degrees"),
            chamfer_side=data.get("chamfer_side"),
            flow_orientation=data.get("flow_orientation"),
            chamfer_width_definition=data.get("chamfer_width_definition"),
            marking=data.get("handle_label"),
            quantity=data.get("quantity", 1),
            part_identifier=part_identifier,
            handle_hole_enabled=data.get("handle_hole_enabled", False),
            handle_hole_diameter=data.get("handle_hole_diameter"),
            handle_hole_center_from_handle_end=data.get("handle_hole_center_from_handle_end"),
            application=data.get("application", PlateApplication.RESTRICTION_GENERAL),
        )


def validate_handle_hole(od, width, length, enabled=False, diameter=None, distance=None):
    """Validate the nominal circle against the canonical straight handle envelope."""
    if type(enabled) is not bool:
        raise ValueError("Handle hole must be enabled or disabled.")
    if not enabled:
        if diameter is not None or distance is not None:
            raise ValueError("Handle hole dimensions require Handle Hole to be enabled.")
        return
    for label, value in (("Handle hole diameter", diameter), ("Handle end to hole center", distance)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
            raise ValueError(f"{label} is required and must be finite and greater than zero.")
    if Decimal(str(diameter)) > Decimal(str(width)) * Decimal("0.90"):
        raise ValueError("Handle hole diameter cannot exceed 90% of handle width.")
    radius = diameter / 2
    if distance - radius <= 0:
        raise ValueError("Handle hole must remain inside the handle end.")
    R, h, r = od / 2, width / 2, CORNER_RADIUS
    if h <= r or h >= R:
        raise ValueError("Handle dimensions do not support canonical geometry.")
    neck_x = sqrt((R - h) * (R + h + 2 * r))
    center_x = length - distance
    # Straight region begins at the actual neck tangent; exclude the plate body too.
    if center_x - radius <= max(neck_x, R):
        raise ValueError("Handle hole must clear the neck transition and circular plate body.")
    # Rounded tip: require the circle inside the rounded rectangle, not only its bbox.
    clearance = h - radius
    if center_x > length - r and clearance < r:
        dx = center_x - (length - r)
        dy = max(0.0, radius - (h - r))
        if dx * dx + dy * dy >= r * r:
            raise ValueError("Handle hole must clear the rounded handle tip.")


def canonical_specification(spec):
    """Omit disabled feature keys, preserving historical no-hole bytes and hashes."""
    record = asdict(spec)
    if not spec.handle_hole_enabled:
        for name in ("handle_hole_enabled", "handle_hole_diameter", "handle_hole_center_from_handle_end"):
            record.pop(name)
    return record


@dataclass(frozen=True)
class ContourSegment:
    kind: str
    start: tuple[float, float]
    end: tuple[float, float]
    center: tuple[float, float] | None = None
    radius: float | None = None
    start_degrees: float = 0.0
    sweep_degrees: float = 0.0

    @property
    def bulge(self):
        return tan(self.sweep_degrees * pi / 720) if self.kind == "arc" else 0.0


@dataclass(frozen=True)
class PlateGeometry:
    spec: PlateSpec
    radius: float
    join_x: float
    half_handle_width: float
    segments: tuple[ContourSegment, ...]
    corner_radius: float = CORNER_RADIUS

    @property
    def outer_vertices_xyb(self):
        return tuple((*segment.start, segment.bulge) for segment in self.segments)

    def to_dict(self):
        return {
            "version": GEOMETRY_VERSION,
            "units": "inches",
            "origin": "bore center",
            "handle_axis": "+X",
            "radius": self.radius,
            "join_x": self.join_x,
            "half_handle_width": self.half_handle_width,
            "corner_radius": self.corner_radius,
            "corner_count": 4,
            "segments": [asdict(segment) for segment in self.segments],
            "outer_vertices_xyb": self.outer_vertices_xyb,
            "finished_bore_diameter": self.spec.finished_bore_diameter,
        }


def build_plate_geometry(spec: PlateSpec) -> PlateGeometry:
    R, h, r, L = (
        spec.finished_od / 2,
        spec.handle_width / 2,
        CORNER_RADIUS,
        spec.centerline_to_handle_end,
    )
    # Concave neck centers lie outside the paddle, at distance R+r from origin.
    # Their offset from each straight handle side is r.
    if h <= r:
        raise ValueError("handle width must exceed twice the corner radius")
    a = sqrt((R - h) * (R + h + 2 * r))
    if a >= L - r:
        raise ValueError("handle too short for separate tangent neck and tip radii")
    theta = atan2(h + r, a) * 180 / pi
    tx, ty = a * R / (R + r), (h + r) * R / (R + r)
    upper, lower = (tx, ty), (tx, -ty)
    segments = (
        ContourSegment("arc", upper, lower, (0.0, 0.0), R, theta, 360 - 2 * theta),
        ContourSegment("arc", lower, (a, -h), (a, -h - r), r, 180 - theta, theta - 90),
        ContourSegment("line", (a, -h), (L - r, -h)),
        ContourSegment("arc", (L - r, -h), (L, -h + r), (L - r, -h + r), r, -90, 90),
        ContourSegment("line", (L, -h + r), (L, h - r)),
        ContourSegment("arc", (L, h - r), (L - r, h), (L - r, h - r), r, 0, 90),
        ContourSegment("line", (L - r, h), (a, h)),
        ContourSegment("arc", (a, h), upper, (a, h + r), r, -90, theta - 90),
    )
    return PlateGeometry(spec, R, a, h, segments)


def rough_bore_diameter(spec: PlateSpec) -> float:
    result = float(
        Decimal(str(spec.finished_bore_diameter))
        - Decimal(str(ROUGH_BORE_DIAMETER_ALLOWANCE))
    )
    if result <= 0:
        raise ValueError(
            "rough bore must be positive after 0.125 inch diameter allowance"
        )
    if (
        spec.bore_tolerance is not None
        and result >= spec.finished_bore_diameter - spec.bore_tolerance
    ):
        raise ValueError(
            "rough bore must leave stock below minimum finished bore tolerance"
        )
    return result


def manufacturing_record(geometry: PlateGeometry):
    from section_geometry import build_section_geometry

    return {
        "section_geometry": build_section_geometry(geometry.spec).to_dict(),
        "schema_version": 4,
        "application_context": application_context(geometry.spec.application),
        "status": "PROTOTYPE - NOT RELEASED FOR MANUFACTURE",
        "specification": canonical_specification(geometry.spec),
        "geometry": geometry.to_dict(),
        "manufacturing": {
            "rough_bore_diameter": rough_bore_diameter(geometry.spec),
            "finished_bore_diameter": geometry.spec.finished_bore_diameter,
            "rough_bore_diameter_allowance": ROUGH_BORE_DIAMETER_ALLOWANCE,
            "radial_machining_stock": ROUGH_BORE_DIAMETER_ALLOWANCE / 2,
            "outer_profile": "finished nominal; no kerf compensation",
            "corner_radius": CORNER_RADIUS,
            "geometry_rule_version": GEOMETRY_VERSION,
        },
        "owner_confirmation_required": [
            "Bore tolerance, general tolerances, edge finish and bore finish",
            "Chamfer requirements (width, angle, side), marking method and placement",
            "General surface finish and inspection requirements",
        ],
    }
