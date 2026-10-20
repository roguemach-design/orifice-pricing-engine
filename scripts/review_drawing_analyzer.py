"""Isolated local assisted-intake review; no pricing, orders or service access."""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_intake.assisted_intake import (
    inspect_assisted_upload,
    select_assisted_candidate,
)
from drawing_intake.assisted_quote import review_assisted_quote
from drawing_intake.deterministic import DeterministicRegionRecognizer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("drawing", type=Path)
    parser.add_argument(
        "--candidate",
        help="Candidate ID from the initial review when multiple plates exist",
    )
    args = parser.parse_args()
    upload = inspect_assisted_upload(args.drawing.read_bytes(), args.drawing.name)
    result = {
        "document_review": upload.review.model_dump(mode="json"),
        "manufacturing_authority": False,
        "production_services_used": False,
    }
    candidate = args.candidate
    if candidate is None and len(upload.review.candidates) == 1:
        candidate = upload.review.candidates[0].candidate_id
    if candidate:
        if candidate in upload.regions:
            recognition = DeterministicRegionRecognizer().recognize(
                upload.document, upload.regions[candidate]
            )
            result["fields"] = {
                name: value.model_dump(mode="json")
                for name, value in recognition.extraction.fields
            }
            result["evidence"] = {
                name: value.model_dump(mode="json")
                for name, value in recognition.field_results.items()
            }
        session = select_assisted_candidate(upload, candidate)
        result["configuration_review"] = review_assisted_quote(session).model_dump(
            mode="json"
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
