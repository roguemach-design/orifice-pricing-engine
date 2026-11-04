"""Session-delivered verified PDFs; never registers a private media URL."""

from base64 import b64encode
from hashlib import sha256
from pathlib import Path

import streamlit.components.v1 as components

_component = components.declare_component(
    "oplates_approved_pdf", path=str(Path(__file__).parent / "frontend")
)


def verified_content(response, revision):
    content = response.content
    if (
        not revision.get("approved")
        or not revision.get("pdf_available", True)
        or response.headers.get("X-Artifact-SHA256") != revision.get("pdf_sha256")
        or response.headers.get("X-Frozen-Revision") != revision.get("id")
        or len(content) != revision.get("pdf_size")
        or sha256(content).hexdigest() != revision.get("pdf_sha256")
    ):
        raise ValueError("Drawing verification failed")
    return content


def approved_pdf(content, revision, owner):
    # Content travels only over the active Streamlit session. No st.image,
    # st.pdf(bytes), st.download_button, shared cache, storage URL or JWT.
    _component(
        pdf=b64encode(content).decode("ascii"),
        digest=revision["pdf_sha256"],
        size=len(content),
        filename=revision["filename"],
        revision=revision["id"],
        key="orders_viewer_"
        + sha256(
            (str(owner) + ":" + revision["id"] + ":" + revision["pdf_sha256"]).encode()
        ).hexdigest(),
        height=1000,
        default=None,
    )
