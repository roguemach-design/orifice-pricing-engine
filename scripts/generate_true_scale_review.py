"""Offline synthetic drawing samples; never reads orders or regenerates stored artifacts."""

from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plate_geometry import PlateSpec, build_plate_geometry
from manufacturing_drawing import render_pdf, DrawingMetadata
from manufacturing_context import DrawingState
from plate_preview import render_plate_svg


def samples():
    base = PlateSpec(
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
    return {
        "example": base,
        "handle-hole": replace(
            base,
            handle_hole_enabled=True,
            handle_hole_diameter=0.5,
            handle_hole_center_from_handle_end=0.75,
        ),
        "chamfer": replace(
            base,
            chamfer=True,
            chamfer_width=0.04,
            chamfer_angle_degrees=45,
            chamfer_side="downstream",
            flow_orientation="left-to-right",
            chamfer_width_definition="radial-angle-from-face",
        ),
        "short-handle": replace(base, centerline_to_handle_end=2),
        "large-48": replace(
            base, finished_od=48, finished_bore_diameter=19, centerline_to_handle_end=25
        ),
        "far-hole": replace(
            base,
            centerline_to_handle_end=30,
            handle_hole_enabled=True,
            handle_hole_diameter=0.5,
            handle_hole_center_from_handle_end=3.5,
        ),
    }


def artifacts(name, s):
    metadata = DrawingMetadata(
        revision="R1",
        specification_revision="R1",
        state=DrawingState.CUSTOMER_CONFIRMATION,
        order_identifier="TEST-DRAWING-" + name.upper(),
        order_line_revision="L1-R1",
    )
    svg = render_plate_svg(
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
    )
    return render_pdf(build_plate_geometry(s), metadata), svg


if __name__ == "__main__":
    import pypdfium2 as pdfium

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("review/drawing-true-scale")
    out.mkdir(parents=True, exist_ok=True)
    for name, s in samples().items():
        pdf, svg = artifacts(name, s)
        (out / (name + ".pdf")).write_bytes(pdf)
        (out / (name + ".svg")).write_text(svg)
        document = pdfium.PdfDocument(pdf)
        document[0].render(scale=1.75).to_pil().save(out / (name + ".png"))
        document.close()
