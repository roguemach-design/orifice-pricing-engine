"""Render synthetic revision evidence. Does not enable any application flag."""

import json
from datetime import date
from pathlib import Path

from pricing_engine import QuoteInputs, calculate_quote
from quote_document import render_quote_pdf

out = Path("review/quote-phase2")
out.mkdir(parents=True, exist_ok=True)
inputs = json.loads(Path("tests/fixtures/quote-review-samples.json").read_text())["B5"][
    "inputs"
]
priced = calculate_quote(QuoteInputs(**inputs))
document = dict(
    sample=True,
    quote_id="Q-7F3A9C21D4-R2",
    supersedes="Q-7F3A9C21D4",
    issued=date(2026, 10, 22),
    customer={"company": "Example Process Co. (synthetic)", "name": "Jordan Example"},
    pricing_ref="pcv-2026-10-21 (sample)",
    lines=[
        dict(
            inputs=inputs,
            unit_price=priced["unit_price"],
            total_price=priced["total_price"],
            qty_mult=priced["qty_discount_multiplier"],
            weight=priced["estimated_total_weight_lb"],
        )
    ],
)
(out / "Quote-R2-links-disabled.pdf").write_bytes(render_quote_pdf(document))
(out / "Quote-R2-future-links-review.pdf").write_bytes(
    render_quote_pdf(
        {
            **document,
            "banner": "REVIEW ONLY · PDF ORDERING LINKS REMAIN DISABLED IN PRODUCTION",
            "retrieval_live": True,
            "retrieval_url": "https://quote.o-plates.com/My_Quotes?quote=Q-7F3A9C21D4-R2",
        }
    )
)
