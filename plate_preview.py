"""Configurator view of the same immutable drawing scene used by the PDF."""

from plate_geometry import PlateSpec, build_plate_geometry
from drawing_presentation import WEB, build_views, svg_scene, web_title_block


def render_plate_svg(
    *,
    paddle_dia: float,
    bore_dia: float,
    handle_width: float,
    handle_length_from_bore: float,
    thickness: float,
    material: str,
    bore_tolerance: float | None = None,
    handle_label: str = "No label",
    chamfer: bool = False,
    chamfer_width: float | None = None,
    handle_hole_enabled: bool = False,
    handle_hole_diameter: float | None = None,
    handle_hole_center_from_handle_end: float | None = None,
    units: str = "in.",
) -> str:
    spec = PlateSpec(
        finished_od=float(paddle_dia),
        finished_bore_diameter=float(bore_dia),
        handle_width=float(handle_width),
        centerline_to_handle_end=float(handle_length_from_bore),
        thickness=float(thickness),
        material=str(material),
        bore_tolerance=bore_tolerance,
        marking=handle_label or None,
        chamfer=chamfer,
        chamfer_width=chamfer_width,
        handle_hole_enabled=handle_hole_enabled,
        handle_hole_diameter=handle_hole_diameter,
        handle_hole_center_from_handle_end=handle_hole_center_from_handle_end,
    )
    scene, view, _ = build_views(build_plate_geometry(spec), profile=WEB)
    web_title_block(scene, view)
    description = f"Configuration preview — Not an approved manufacturing drawing. {material}, {units}; marking {handle_label}. Same geometry as the confirmation PDF."
    return svg_scene(scene, view, description)
