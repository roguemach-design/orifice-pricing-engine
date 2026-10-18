"""Reproducible synthetic shop-review examples, not real order/manufacturing authority."""

from dataclasses import replace, asdict
from pathlib import Path
import json
from haas_generator.contract import from_dict
from haas_generator.engineering import Parameters, engineering_bundle
from packaging_generator.generator import Configuration, generate
from plate_geometry import PlateSpec

ROOT = Path(__file__).resolve().parents[1]


def main():
    root = ROOT / "examples/final4/output"
    r, p = from_dict(
        json.loads((ROOT / "examples/haas/record.json").read_text()),
        json.loads((ROOT / "examples/haas/profile.json").read_text()),
    )
    params = Parameters(
        **json.loads((ROOT / "examples/final4/machining-parameters.json").read_text())
    )
    c = Configuration(
        **json.loads((ROOT / "examples/final4/packaging-config.json").read_text())
    )
    parent = {
        "order_id": "SYNTHETIC-001",
        "line_id": "L1",
        "plate_id": "SYNTHETIC-PLATE",
        "revision_id": "SYNTHETIC-R1",
        "revision": "R1",
        "spec_sha256": "0" * 64,
        "source_sha256": "0" * 64,
    }
    for label, record in [
        ("haas-thin-chamfer", r),
        ("haas-half-inch", replace(r, thickness=0.5, top_chamfer_width=0)),
    ]:
        dest = root / label
        dest.mkdir(parents=True, exist_ok=True)
        for name, data in engineering_bundle(record, p, params, parent).items():
            (dest / name).write_text(data, encoding="ascii")
    s = PlateSpec(
        finished_od=5,
        finished_bore_diameter=1.548,
        handle_width=2,
        centerline_to_handle_end=10.5,
        material=r.material,
        thickness=0.125,
        bore_tolerance=0.001,
        chamfer=False,
    )
    samples = {
        "packaging-thin": s,
        "packaging-thick": replace(s, thickness=0.5),
        "packaging-small": replace(
            s,
            finished_od=1,
            finished_bore_diameter=0.3,
            handle_width=0.25,
            centerline_to_handle_end=3,
        ),
        "packaging-long": replace(s, centerline_to_handle_end=30, thickness=0.375),
        "packaging-wide": replace(
            s, handle_width=4.8, centerline_to_handle_end=6, thickness=0.25
        ),
    }
    for label, spec in samples.items():
        dest = root / label
        dest.mkdir(parents=True, exist_ok=True)
        for name, data in generate(spec, c, parent).items():
            (dest / name).write_bytes(data)
    (root / "README.md").write_text(
        "# Synthetic Final 4 prototypes\n\nNO MACHINE OR SHIPPING RELEASE.\nRegenerate with `python -m final4.samples` in requirements-final4.txt environment.\nSource hashes of all zeroes identify fixtures, not authoritative real Frozen Plates.\n",
        encoding="ascii",
    )


if __name__ == "__main__":
    main()
