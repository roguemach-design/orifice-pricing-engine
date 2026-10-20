import pytest
from fastapi.testclient import TestClient
from drawing_review_app import create_app


def test_review_requires_isolation(monkeypatch):
    monkeypatch.delenv("DRAWING_REVIEW_ONLY", raising=False)
    with pytest.raises(ValueError):
        create_app()
    monkeypatch.setenv("DRAWING_REVIEW_ONLY", "true")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError):
        create_app()


def test_read_only_synthetic_review_and_matching_artifacts(monkeypatch):
    monkeypatch.setenv("DRAWING_REVIEW_ONLY", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    with TestClient(create_app()) as client:
        assert client.get("/health").json()["mode"] == "synthetic-drawing-review"
        for name in (
            "example",
            "handle-hole",
            "chamfer",
            "short-handle",
            "large-48",
            "far-hole",
        ):
            assert client.get("/", params={"sample": name}).status_code == 200
            pdf = client.get(f"/samples/{name}.pdf")
            assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
            assert pdf.content == client.get(f"/samples/{name}.pdf").content
            svg = client.get(f"/samples/{name}.svg")
            assert svg.status_code == 200 and "data-scale=" in svg.text
            assert svg.headers["x-robots-tag"] == "noindex, nofollow"
        assert client.post("/samples/example.pdf").status_code == 405
        assert client.get("/samples/unknown.pdf").status_code == 404
        assert client.get("/checkout").status_code == 404
