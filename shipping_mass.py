"""Shipping mass only, measured from the existing canonical manufacturing contours.

Does not change material purchasing envelopes, geometry records, or carrier rules.
"""
from math import isfinite, pi, radians, sin

from plate_geometry import PlateSpec, build_plate_geometry
from section_geometry import build_section_geometry

MODEL_VERSION = "finished-part-plus-packaging-v1"
PACKAGING_LB_PER_PLATE = 1.0


def finished_part_volume_in3(spec: PlateSpec) -> float:
    geometry = build_plate_geometry(spec)
    # Green's theorem: chord polygon area plus each signed circular segment.
    # This integrates the actual shared outline, including neck/tip fillets,
    # without counting the circular plate/handle overlap twice.
    twice_area = 0.0
    for segment in geometry.segments:
        x0, y0 = segment.start
        x1, y1 = segment.end
        twice_area += x0 * y1 - x1 * y0
        if segment.kind == "arc":
            sweep = radians(segment.sweep_degrees)
            twice_area += segment.radius ** 2 * (sweep - sin(sweep))
    area = abs(twice_area) / 2 - pi * (spec.finished_bore_diameter / 2) ** 2
    if spec.handle_hole_enabled:
        area -= pi * (spec.handle_hole_diameter / 2) ** 2
    volume = area * spec.thickness
    section = build_section_geometry(spec)
    if section.chamfer_drawn:
        # Revolved triangular section removed outside the finished cylinder.
        w, depth = section.chamfer_radial_width, section.chamfer_axial_depth
        volume -= pi * depth * (section.bore_radius * w + w * w / 3)
    # An incomplete quote-only chamfer has no assumed manufacturing geometry;
    # retain its material conservatively. Checkout still requires completeness.
    if not isfinite(volume) or volume <= 0:
        raise ValueError("Finished-part shipping volume must be finite and positive")
    return volume


def shipping_mass(configuration, density_lb_per_in3):
    if not isfinite(density_lb_per_in3) or density_lb_per_in3 <= 0:
        raise ValueError("Shipping density must be finite and positive")
    physical = dict(configuration)
    # Inactive quote-form values have no physical mass. This does not relax the
    # independent checkout completeness/geometry validation.
    if physical.get("chamfer") is False:
        for key in ("chamfer_width", "chamfer_angle_degrees", "chamfer_side",
                    "flow_orientation", "chamfer_width_definition"):
            physical[key] = None
    spec = PlateSpec.from_configuration(physical)
    part_lb = finished_part_volume_in3(spec) * density_lb_per_in3
    return part_lb, spec.quantity * (part_lb + PACKAGING_LB_PER_PLATE)
