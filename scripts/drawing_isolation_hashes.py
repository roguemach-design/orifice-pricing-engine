"""Byte baselines for artifacts outside the drawing presentation change."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manufacturing_files import generate_package
from plate_geometry import build_plate_geometry
from prototype_manufacturing import sample_spec
from haas_generator.contract import from_dict
from haas_generator.generator import generate as haas
from packaging_generator.generator import Configuration, generate as packaging

ROOT = Path(__file__).resolve().parents[1]


def hashes():
    result = {}

    def add(prefix, files):
        for name, data in sorted(files.items()):
            result[prefix + "/" + name] = sha256(
                data.encode() if isinstance(data, str) else data
            ).hexdigest()

    config = Configuration(
        **json.loads((ROOT / "examples/final4/packaging-config.json").read_text())
    )
    base = replace(sample_spec(), bore_tolerance=0.005, chamfer=False)
    cases = {
        "standard": base,
        "long": replace(base, centerline_to_handle_end=30),
        "hole": replace(
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
    }
    for name, spec in cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            files = generate_package(build_plate_geometry(spec), Path(tmp))
        add(name, {k: v for k, v in files.items() if k != "pdf"})
        add(name + "/packaging", packaging(spec, config, {"revision": "SYNTHETIC-R1"}))
    r, p = from_dict(
        json.loads((ROOT / "examples/haas/record.json").read_text()),
        json.loads((ROOT / "examples/haas/profile.json").read_text()),
    )
    add("haas", haas(r, p))
    return result


if __name__ == "__main__":
    print(json.dumps(hashes(), indent=2, sort_keys=True))
