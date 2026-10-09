"""Deterministic finished longitudinal section; no renderer or application I/O."""

from dataclasses import dataclass
from math import tan, radians, isfinite, isclose

SECTION_VERSION = "longitudinal-section-v1"


@dataclass(frozen=True)
class SectionGeometry:
    polygons: tuple
    status: str
    missing: tuple[str, ...]
    thickness: float
    bore_radius: float
    chamfer_radial_width: float | None
    chamfer_axial_depth: float | None
    straight_land: float | None
    angle_degrees: float | None
    face: str | None
    flow_orientation: str | None

    @property
    def chamfer_drawn(self):
        return self.status == "CONFIGURED"

    def to_dict(self):
        from dataclasses import asdict

        return {"version": SECTION_VERSION, **asdict(self)}


def build_section_geometry(spec):
    """Longitudinal bore/handle-center section, x through thickness, y radial.

    Radial width w and angle alpha measured from face define axial depth
    d=w*tan(alpha). For explicit axial-depth convention, w=d/tan(alpha).
    Both require an explicit convention; no existing app width is reinterpreted.
    """
    s = spec
    R = s.finished_od / 2
    b = s.finished_bore_diameter / 2
    t = s.thickness
    upper = (
        (0, b),
        (t, b),
        (t, s.centerline_to_handle_end),
        (0, s.centerline_to_handle_end),
    )
    lower = ((0, -R), (t, -R), (t, -b), (0, -b))
    required = (
        "chamfer_width",
        "chamfer_angle_degrees",
        "chamfer_side",
        "flow_orientation",
        "chamfer_width_definition",
    )
    missing = (
        tuple(name for name in required if getattr(s, name) is None)
        if s.chamfer
        else ()
    )
    status = (
        "NONE"
        if s.chamfer is False
        else (
            "NOT SPECIFIED - HOLD"
            if s.chamfer is None
            else "INCOMPLETE - HOLD" if missing else "CONFIGURED"
        )
    )
    w = d = land = angle = face = None
    if status == "CONFIGURED":
        angle = s.chamfer_angle_degrees
        if s.chamfer_width_definition == "radial-angle-from-face":
            w = s.chamfer_width
            d = w * tan(radians(angle))
        else:
            d = s.chamfer_width
            w = d / tan(radians(angle))
        if (
            not all(isfinite(v) and v > 0 for v in (w, d))
            or w >= R - b
            or d >= t
            or isclose(d, t, rel_tol=0, abs_tol=1e-12)
            or isclose(w, R - b, rel_tol=0, abs_tol=1e-12)
        ):
            raise ValueError(
                "chamfer does not fit finished section with positive land and wall"
            )
        land = t - d
        # Left face is upstream only when physical flow is left-to-right.
        left = (s.chamfer_side == "upstream") == (s.flow_orientation == "left-to-right")
        face = "left" if left else "right"
        top = s.centerline_to_handle_end
        if left:
            upper = ((0, b + w), (d, b), (t, b), (t, top), (0, top))
            lower = ((0, -R), (t, -R), (t, -b), (d, -b), (0, -b - w))
        else:
            upper = ((0, b), (t - d, b), (t, b + w), (t, top), (0, top))
            lower = ((0, -R), (t, -R), (t, -b - w), (t - d, -b), (0, -b))
    polygons = (upper, lower)
    if s.handle_hole_enabled:
        center = s.centerline_to_handle_end - s.handle_hole_center_from_handle_end
        low, high = center - s.handle_hole_diameter / 2, center + s.handle_hole_diameter / 2
        upper = tuple((x, low if y == s.centerline_to_handle_end else y) for x, y in upper)
        tip = ((0, high), (t, high), (t, s.centerline_to_handle_end), (0, s.centerline_to_handle_end))
        polygons = (upper, lower, tip)
    return SectionGeometry(
        polygons,
        status,
        missing,
        t,
        b,
        w,
        d,
        land,
        angle,
        face,
        s.flow_orientation,
    )
