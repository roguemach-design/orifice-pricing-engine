"""Synthetic v7.1 evidence; filesystem output only, no orders or external I/O."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.review_drawing_v6 import BASE, CASES as V6_CASES, svg_for
from manufacturing_context import DrawingState
from manufacturing_drawing import DrawingMetadata, GENERATOR_VERSION
from manufacturing_files import generate_package
from frozen_plate.validation import validate_package
from plate_geometry import build_plate_geometry

CASES = {
    **V6_CASES,
    "example-carbon": replace(BASE, material="Carbon Steel"),
    "full-feature-316": replace(V6_CASES["full-feature"], material="316"),
}


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, spec in CASES.items():
        geometry = build_plate_geometry(spec)
        metadata = DrawingMetadata(
            revision="R1", state=DrawingState.CUSTOMER_CONFIRMATION,
            order_identifier="TEST-DRAWING-CHAMFER" if name.startswith("full-feature") else "TEST-DRAWING-EXAMPLE",
            order_line_revision="L1-R1", specification_revision="R1",
        )
        outputs = generate_package(geometry, directory, stem=name, metadata=metadata, include_svg=False)
        validate_package(geometry, metadata, outputs)
        svg = svg_for(spec).encode()
        (directory / (name + ".svg")).write_bytes(svg)
        outputs["svg"] = svg
        result[name] = {kind: {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
                        for kind, data in outputs.items()}
    manifest = {"generator": GENERATOR_VERSION, "package_verification": "passed", "cases": result}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(generate(sys.argv[1]), sort_keys=True))
