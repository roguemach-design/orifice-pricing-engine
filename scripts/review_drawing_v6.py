"""Offline, synthetic review samples. No orders, external I/O or credentials."""

from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plate_geometry import PlateSpec, build_plate_geometry
from manufacturing_drawing import DrawingMetadata, render_pdf
from manufacturing_context import DrawingState
from plate_preview import render_plate_svg

ROOT = Path(__file__).resolve().parents[1] / "review/drawing-v6"
BASE = PlateSpec(
    3,
    1,
    1.5,
    9,
    "304",
    0.125,
    bore_tolerance=0.005,
    chamfer=False,
    part_identifier="PRD-a04088158d8767b4-1",
)
CASES = {
    "example": BASE,
    "full-feature": replace(
        BASE,
        chamfer=True,
        chamfer_width=0.04,
        handle_hole_enabled=True,
        handle_hole_diameter=0.5,
        handle_hole_center_from_handle_end=0.75,
        marking="FE-101",
    ),
    "short-handle": replace(BASE, centerline_to_handle_end=2),
    "far-hole": replace(
        BASE,
        centerline_to_handle_end=30,
        handle_hole_enabled=True,
        handle_hole_diameter=0.5,
        handle_hole_center_from_handle_end=3.5,
        marking="FE-101",
    ),
    "large-48": replace(
        BASE, finished_od=48, finished_bore_diameter=19, centerline_to_handle_end=25
    ),
    "wide-handle": replace(
        BASE,
        finished_od=5,
        finished_bore_diameter=1.548,
        handle_width=4.8,
        centerline_to_handle_end=6,
    ),
}


def svg_for(s):
    return render_plate_svg(
        paddle_dia=s.finished_od,
        bore_dia=s.finished_bore_diameter,
        handle_width=s.handle_width,
        handle_length_from_bore=s.centerline_to_handle_end,
        thickness=s.thickness,
        material=s.material,
        bore_tolerance=s.bore_tolerance,
        chamfer=s.chamfer,
        chamfer_width=s.chamfer_width,
        handle_hole_enabled=s.handle_hole_enabled,
        handle_hole_diameter=s.handle_hole_diameter,
        handle_hole_center_from_handle_end=s.handle_hole_center_from_handle_end,
        handle_label=s.marking or "No label",
    )


if __name__ == "__main__":
    for name, s in CASES.items():
        metadata = DrawingMetadata(
            revision="R1",
            state=DrawingState.CUSTOMER_CONFIRMATION,
            order_identifier=(
                "TEST-DRAWING-CHAMFER"
                if name == "full-feature"
                else "TEST-DRAWING-EXAMPLE"
            ),
            order_line_revision="L1-R1",
            specification_revision="R1",
        )
        (ROOT / (name + ".pdf")).write_bytes(
            render_pdf(build_plate_geometry(s), metadata)
        )
        (ROOT / (name + ".svg")).write_text(svg_for(s))
    print("Generated six synthetic PDF/SVG pairs")
