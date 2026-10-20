"""Read-only staging evidence and temporary local TEST-order verification.

Never contacts a customer database, sends email, or changes stored orders.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frozen_plate.repository import Repository
from scripts.generate_true_scale_review import samples, artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("expected_commit")
    parser.add_argument("--output", type=Path, default=Path("review/drawing-true-scale/staging"))
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    assert base.startswith("https://"), "HTTPS staging URL required"
    args.output.mkdir(parents=True, exist_ok=True)

    def fetch(path):
        with urlopen(base + path, timeout=50) as response:
            assert response.status == 200
            assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            return response.read()

    health = json.loads(fetch("/health"))
    assert health["commit"] == args.expected_commit
    assert health["generator"] == "op-drawing-v4-true-scale"
    assert health["mode"] == "synthetic-drawing-review"
    assert b"Synthetic TEST drawings" in fetch("/")
    evidence = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base, "health": health, "samples": {}, "test_orders": {},
        "workflow_environment": "Temporary local SQLite using exact staging PDF bytes; no external email/database/order writes",
    }
    staged = {}
    import pypdfium2 as pdfium
    for name, spec in samples().items():
        pdf, svg = artifacts(name, spec)
        remote_pdf, remote_svg = fetch(f"/samples/{name}.pdf"), fetch(f"/samples/{name}.svg")
        assert remote_pdf == pdf, name + " PDF differs from verified local renderer"
        assert remote_svg == svg.encode(), name + " SVG differs from verified local renderer"
        staged[name] = remote_pdf
        (args.output / (name + ".pdf")).write_bytes(remote_pdf)
        (args.output / (name + ".svg")).write_bytes(remote_svg)
        document = pdfium.PdfDocument(remote_pdf)
        document[0].render(scale=1.75).to_pil().save(args.output / (name + ".png"))
        document.close()
        evidence["samples"][name] = {
            "pdf_sha256": sha256(remote_pdf).hexdigest(),
            "svg_sha256": sha256(remote_svg).hexdigest(),
            "pdf_bytes": len(remote_pdf), "svg_bytes": len(remote_svg),
            "exact_local_parity": True,
        }

    # Exercise the real Frozen Plate generator and approval path, using only a
    # disposable local repository and synthetic identities matching staging.
    with TemporaryDirectory(prefix="drawing-review-test-") as private:
        repo = Repository(Path(private), secrets.token_urlsafe(48))
        for name in ("example", "handle-hole"):
            spec = samples()[name]
            order = "TEST-DRAWING-" + name.upper()
            plate = repo.create_plate(
                order_id=order, line_id="L1", configuration_id="TEST-" + name,
                customer_id="TEST-CUSTOMER", actor="TEST-REVIEW",
            )
            revision = repo.create_revision(
                plate, spec, expected_current=None, reason="Synthetic staging drawing verification",
                actor="TEST-REVIEW", source_snapshot={"test": True, "spec": asdict(spec)},
            )
            pdf_artifact = revision["artifacts"]["pdf"]
            frozen_pdf = (repo.objects / pdf_artifact["object_key"]).read_bytes()
            assert frozen_pdf == staged[name]
            delivery = repo.create_delivery(revision["id"])
            message = BytesParser(policy=policy.default).parsebytes(delivery["mime"])
            attachments = list(message.iter_attachments())
            assert len(attachments) == 1
            assert attachments[0].get_payload(decode=True) == staged[name]
            approved = repo.approve(delivery["token"], "TEST-CUSTOMER")
            assert repo.approve(delivery["token"], "TEST-CUSTOMER") == approved
            assert approved["approval"]["pdf_sha256"] == sha256(staged[name]).hexdigest()
            assert approved["approval"]["spec_sha256"] == revision["spec_sha256"]
            assert repo.plate(plate)["lifecycle"] == "CUSTOMER_APPROVED"
            evidence["test_orders"][order] = {
                "revision": "R1", "exact_staging_pdf_frozen": True,
                "captured_email_attachment_exact": True, "external_email_sent": False,
                "approval_exact_and_idempotent": True,
                "pdf_sha256": pdf_artifact["sha256"],
                "spec_sha256": revision["spec_sha256"],
            }
    path = args.output / "verification.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"commit": health["commit"], "samples_verified": len(staged),
                      "synthetic_test_orders_verified": len(evidence["test_orders"]),
                      "evidence": str(path)}, indent=2))


if __name__ == "__main__":
    main()
