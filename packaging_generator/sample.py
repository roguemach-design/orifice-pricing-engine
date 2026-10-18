"""Generate an explicitly synthetic prototype and audit the serialized DXF."""

import argparse
from dataclasses import asdict
from hashlib import sha256
from io import StringIO
import json
from math import atan, pi
from pathlib import Path
import ezdxf
from ezdxf.math import bulge_to_arc
from plate_geometry import PlateSpec, canonical_specification, build_plate_geometry
from .generator import Configuration, generate, layout
from .contour import svg_path, transform
from .audit import inspect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = Configuration(
        **json.loads((root / "examples/final4/packaging-config.json").read_text())
    )
    spec = PlateSpec(
        5,
        1.548,
        2,
        10.5,
        "304 Stainless Steel",
        0.5,
        bore_tolerance=0.001,
        chamfer=False,
        part_identifier="PACKAGING-PROTOTYPE-5IN",
    )
    canonical = json.dumps(
        canonical_specification(spec), sort_keys=True, separators=(",", ":")
    ).encode()
    parent = dict(
        order_id="SYNTHETIC-NOT-A-CUSTOMER-ORDER",
        line_id="SAMPLE-L1",
        plate_id="SYNTHETIC-PACKAGING-5IN",
        revision_id="SYNTHETIC-R1",
        revision="R1",
        spec_sha256=sha256(canonical).hexdigest(),
        source_sha256=sha256(canonical).hexdigest(),
    )
    files = generate(spec, config, parent)
    if files != generate(spec, config, parent):
        raise RuntimeError("nondeterministic generation")
    report = inspect(files["packaging.dxf"])
    report.update(
        deterministic_all_bundle_bytes=True,
        packaging_dxf_sha256=sha256(files["packaging.dxf"]).hexdigest(),
        synthetic_sample=True,
        physical_validation="REQUIRED",
        configuration=asdict(config),
    )
    args.destination.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.destination / name).write_bytes(content)
    (args.destination / "dxf-audit.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    # Enlargement reads actual DXF vertices and bulges, independently of export.
    doc = ezdxf.read(StringIO(files["packaging.dxf"].decode()))
    e = doc.modelspace().query('LWPOLYLINE[layer=="CUT_NEST"]')[0]
    d = layout(spec, config)
    W, H = d["panel_width"], d["panel_height"]
    xoff = d["center_x"]
    vertices = list(e.get_points("xyb"))
    path = [f"M {vertices[0][0]-xoff} {vertices[0][1]}"]
    for i, (x, y, b) in enumerate(vertices):
        end = vertices[(i + 1) % len(vertices)][:2]
        if b:
            _, _, _, r = bulge_to_arc((x, y), end, b)
            sweep = 4 * atan(b)
            path.append(
                f"A {r} {r} 0 {int(abs(sweep)>pi)} {int(b>0)} {end[0]-xoff} {end[1]}"
            )
        else:
            path.append(f"L {end[0]-xoff} {end[1]}")
    path.append("Z")
    steel = transform(
        build_plate_geometry(spec).segments, W / 2, config.margin + spec.finished_od / 2
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="880" height="1360" viewBox="-2 -1 {W+4} {H+2}">
<rect x="-2" y="-1" width="{W+4}" height="{H+2}" fill="#fff"/>
<g transform="translate(0,{H}) scale(1,-1)">
<rect width="{W}" height="{H}" fill="#e9d2ae" stroke="#705638" stroke-width=".025"/>
<path d="{' '.join(path)}" fill="white" stroke="#b13d20" stroke-width=".03"/>
<path d="{svg_path(steel)}" fill="#b7c7d4" stroke="#3b5363" stroke-width=".015"/>
</g>
<g font-family="sans-serif" font-size=".19" fill="#233543">
<text x="0" y="-.55">5-inch paddle / 2-inch handle / 0.500-inch plate</text>
<text x="0" y="-.22">Actual DXF contour - LEFT long-edge finger access</text>
<text x="0" y="{H+.45}">PROTOTYPE / ENGINEERING REVIEW - physical validation required</text>
</g>"""
    for relief in d["geometry_report"]["finger_reliefs"]:
        x, y = relief["center_plate_coordinates"]
        px = W / 2 - y
        py = H - (x + config.margin + spec.finished_od / 2)
        svg += f'<path d="M -1.6 {py} H {px-.42}" stroke="#233543" stroke-width=".015"/><text x="-1.8" y="{py-.15}" font-family="sans-serif" font-size=".18">{relief["position"]}</text>'
    svg += "</svg>"
    (args.destination / "center-nest.svg").write_text(svg)
    print(
        json.dumps(
            {
                "destination": str(args.destination),
                "nest_layers": report["nest_count"],
                "dxf_sha256": report["packaging_dxf_sha256"],
                "audit": "PASS",
            }
        )
    )


if __name__ == "__main__":
    main()
