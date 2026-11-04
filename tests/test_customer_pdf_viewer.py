from hashlib import sha256
from types import SimpleNamespace

import pytest
from customer_pdf_viewer import verified_content


@pytest.mark.parametrize(
    "mismatch", [None, "revision", "header", "bytes", "size", "approved", "available"]
)
def test_exact_approved_artifact_binding(mismatch):
    content = b"%PDF-synthetic"
    digest = sha256(content).hexdigest()
    revision = dict(
        id="r1",
        approved=True,
        pdf_available=True,
        pdf_size=len(content),
        pdf_sha256=digest,
    )
    response = SimpleNamespace(
        content=content,
        headers={"X-Artifact-SHA256": digest, "X-Frozen-Revision": "r1"},
    )
    if mismatch == "revision":
        response.headers["X-Frozen-Revision"] = "r2"
    if mismatch == "header":
        response.headers["X-Artifact-SHA256"] = "0" * 64
    if mismatch == "bytes":
        response.content = b"tampered"
    if mismatch == "size":
        revision["pdf_size"] += 1
    if mismatch == "approved":
        revision["approved"] = False
    if mismatch == "available":
        revision["pdf_available"] = False
    if mismatch:
        with pytest.raises(ValueError):
            verified_content(response, revision)
    else:
        assert verified_content(response, revision) is content
