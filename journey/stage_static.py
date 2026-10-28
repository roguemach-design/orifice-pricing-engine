"""Build-only staging bindings. Never run for the production static service."""

from pathlib import Path

root = Path(__file__).resolve().parents[1] / "o-plates landing"
p = root / "index.html"
s = p.read_text().replace(
    "https://quote.o-plates.com/Quote",
    "https://oplates-customer-ui-staging.onrender.com/Quote",
)
p.write_text(s)
(root / "journey-config.js").write_text(
    "window.OPLATES_JOURNEY={enabled:true,endpoint:'https://oplates-pricing-api-staging.onrender.com'};\n"
)
