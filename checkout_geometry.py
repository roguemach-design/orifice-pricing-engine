"""Checkout preflight using the existing canonical manufacturing geometry.

No historical snapshots, renderers, prices or artifacts are changed here.
"""
from plate_geometry import PlateSpec, build_plate_geometry
from section_geometry import build_section_geometry

STANDARD_CHAMFER = {
    "chamfer_angle_degrees": 45.0,
    "chamfer_side": "downstream",
    "flow_orientation": "left-to-right",
    "chamfer_width_definition": "radial-angle-from-face",
}
STANDARD_DESCRIPTION = (
    "Standard 45° Chamfer: downstream face; flow is shown left to right in the section. "
    "Width is measured radially at the plate face, with the angle measured from that face."
)


def checkout_geometry_error(values):
    if values.get("chamfer") is not True:
        return None
    try:
        spec = PlateSpec.from_configuration(values)
        build_plate_geometry(spec)
        section = build_section_geometry(spec)
        if "HOLD" in section.status:
            return "Chamfer specification requires review: " + ", ".join(section.missing) + "."
    except (KeyError, ValueError, TypeError) as exc:
        return "Chamfer specification requires review: " + str(exc)
    return None
