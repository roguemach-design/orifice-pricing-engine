"""Run: python prototype_manufacturing.py [--output prototype_output]."""

import argparse
from dataclasses import replace
from pathlib import Path
from plate_geometry import PlateSpec, build_plate_geometry
from manufacturing_files import generate_job_package


def sample_spec():
    return PlateSpec.from_configuration(
        {
            "paddle_dia": 5.0,
            "bore_dia": 1.548,
            "handle_width": 2.0,
            "handle_length_from_bore": 10.5,
            "material": "304 stainless steel",
            "thickness": 0.125,
            "quantity": 1,
        }
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("prototype_output/current"))
    parser.add_argument(
        "--chamfer-review",
        action="store_true",
        help="Also generate explicit illustrative chamfer package; values are not defaults",
    )
    args = parser.parse_args()
    spec = replace(sample_spec(), part_identifier="PROTOTYPE-001")
    generate_job_package(build_plate_geometry(spec), args.output)
    if args.chamfer_review:
        example = replace(
            spec,
            chamfer=True,
            chamfer_width=0.04,
            chamfer_angle_degrees=45,
            chamfer_side="downstream",
            flow_orientation="left-to-right",
            chamfer_width_definition="radial-angle-from-face",
            part_identifier="EXAMPLE-CHAMFER-NOT-DEFAULT",
        )
        generate_job_package(
            build_plate_geometry(example), args.output.parent / "chamfer-review"
        )
    print(f"Prototype package written to {args.output}")


if __name__ == "__main__":
    main()
