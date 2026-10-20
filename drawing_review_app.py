"""Isolated, read-only synthetic drawing review. No customer/order integrations."""

import os
from functools import lru_cache
from html import escape
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from manufacturing_drawing import GENERATOR_VERSION
from scripts.generate_true_scale_review import samples, artifacts


def create_app():
    if (
        os.environ.get("DRAWING_REVIEW_ONLY") != "true"
        or os.environ.get("APP_ENV") == "production"
    ):
        raise ValueError("isolated drawing review environment required")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    cases = samples()

    @lru_cache(maxsize=6)
    def output(name):
        if name not in cases:
            raise HTTPException(404, "Unknown sample")
        return artifacts(name, cases[name])

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "generator": GENERATOR_VERSION,
            "commit": os.environ.get("RENDER_GIT_COMMIT", "local"),
            "mode": "synthetic-drawing-review",
        }

    @app.get("/", response_class=HTMLResponse)
    def index(sample: str = "example"):
        if sample not in cases:
            raise HTTPException(404, "Unknown sample")
        options = "".join(
            f'<option value="{escape(n)}"'
            + (" selected" if n == sample else "")
            + f'>{escape(n.replace("-"," ").title())}</option>'
            for n in cases
        )
        return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>O-Plates drawing review</title><style>body{{font:16px Arial,sans-serif;margin:24px auto;max-width:1200px;padding:0 18px;color:#172033;background:#f3f5f7}}h1{{font-size:26px}}p{{line-height:1.5}}form{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}select,button,a{{font:inherit}}button,a{{padding:10px 14px;background:white;border:1px solid #687786;border-radius:5px;color:#172033}}select{{padding:10px}}img{{width:100%;height:auto;background:white;margin-top:22px;border:1px solid #d7dde4}}small{{color:#526174}}</style>
<h1>O-Plates drawing review</h1><p>Synthetic TEST drawings. Review the configurator image and its matching confirmation PDF.</p>
<form><label for="sample">Sample</label><select id="sample" name="sample">{options}</select><button>Show drawing</button><a href="/samples/{sample}.pdf" target="_blank">Open PDF</a></form>
<img src="/samples/{sample}.svg" alt="Plate configuration drawing"><p><small>Visual review only. These samples are not released for manufacture.</small></p></html>"""

    @app.get("/samples/{name}.pdf")
    def pdf(name: str):
        return Response(
            output(name)[0],
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="TEST-{name}-R1.pdf"'},
        )

    @app.get("/samples/{name}.svg")
    def svg(name: str):
        return Response(output(name)[1], media_type="image/svg+xml")

    return app
