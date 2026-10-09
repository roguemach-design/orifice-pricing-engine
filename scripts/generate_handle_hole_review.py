"""Generate OFF/ON owner review evidence without database or vendor actions."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prototype_manufacturing import sample_spec
from manufacturing_files import generate_package
from plate_geometry import build_plate_geometry, canonical_specification
from plate_preview import render_plate_svg
from manufacturing_drawing import DrawingMetadata
from manufacturing_context import DrawingState

target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("review/handle-hole")
spec = replace(
    sample_spec(),
    handle_width=1,
    part_identifier="HANDLE-HOLE-REVIEW",
    bore_tolerance=0.005,
    chamfer=False,
)
metadata = DrawingMetadata(state=DrawingState.CUSTOMER_CONFIRMATION)
summary = {}
for name, current in [
    ("handle-hole-off", spec),
    (
        "handle-hole-on",
        replace(
            spec,
            handle_hole_enabled=True,
            handle_hole_diameter=0.375,
            handle_hole_center_from_handle_end=0.75,
        ),
    ),
]:
    outputs = generate_package(
        build_plate_geometry(current), target, stem=name, metadata=metadata
    )
    svg = render_plate_svg(
        paddle_dia=current.finished_od,
        bore_dia=current.finished_bore_diameter,
        handle_width=current.handle_width,
        handle_length_from_bore=current.centerline_to_handle_end,
        thickness=current.thickness,
        material=current.material,
        bore_tolerance=current.bore_tolerance,
        handle_hole_enabled=current.handle_hole_enabled,
        handle_hole_diameter=current.handle_hole_diameter,
        handle_hole_center_from_handle_end=current.handle_hole_center_from_handle_end,
    )
    (target / (name + "-configurator.svg")).write_text(svg)
    summary[name] = {
        "spec": canonical_specification(current),
        "sha256": {
            suffix: sha256(data).hexdigest() for suffix, data in outputs.items()
        },
    }
(target / "evidence.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n"
)
