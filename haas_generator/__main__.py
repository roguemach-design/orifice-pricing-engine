"""Trusted local-admin CLI; optional localhost-only authenticated service."""

import argparse
import os
from pathlib import Path
from .contract import MachineProfile, ReviewedRecord, construct, loads
from .generator import generate


def main():
    parser = argparse.ArgumentParser(description="Generate Haas REVIEW ONLY artifacts")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    profile = construct(MachineProfile, loads(args.profile.read_text()))
    if args.serve:
        import uvicorn
        from .web import create_app

        app = create_app(admin_key=os.environ.get("HAAS_ADMIN_KEY"), profile=profile)
        uvicorn.run(app, host="127.0.0.1", port=8091, access_log=False)
        return
    if args.record is None or args.output is None:
        parser.error("--record and --output required unless --serve")
    record = construct(ReviewedRecord, loads(args.record.read_text()))
    files = generate(record, profile)
    # Fail rather than overwrite an earlier review package.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, contents in files.items():
        (args.output / name).write_bytes(contents.encode("ascii"))


if __name__ == "__main__":
    main()
