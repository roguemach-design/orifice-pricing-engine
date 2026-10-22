# Commercial quotations — revision 2, Phase 1

Base: work/final-integration-production-cutover at 45ee4dc58ac9c2556a1b891c30512fa1eb28fe04. Owner package and standalone revision 2 specification were identical.

The Quote Cart remains the source of canonical configurations and authoritative /quote prices. A thin adapter renders the approved A/B commercial design. New PDF generation assigns a fresh number and uses it in the metadata, page furniture and filename. No saved-quote ordering link is emitted in this phase.

IBM Plex Sans 400/500/600/700 and the upstream OFL are vendored. Dimensions and customer/marking text wrap; whole lines and paired terms panels move to the next page. Generated sample PDFs cover 1, 6, 25 and 60 lines. Missing optional fields are omitted rather than invented, so sparse sample rows can be shorter than the mockup.

## Evidence

`review/quote-phase1/Quote-A.pdf` and `Quote-B.pdf` correspond to approved mockups A and B. PNGs show the rendered pages. `scripts/review_quote_pdf.py` regenerates these from the existing pricing engine and the supplied sample inputs. `tests/test_quote_document.py` tests pagination, intact lines, bounds, independent authoritative unit/extended prices, dates, metadata, nontruncation, numbering and deterministic rendering.

Focused PDF/cart/checkout/security/UI regression: 117 passed. Full suite: 1189 passed, 6 skipped; two obsolete old-layout assertions were updated to the new adapter and approved copy, then rerun successfully (1191 passing checks in aggregate).

## Address disposition

- `pages/3_Quote_Cart.py`: old supplier block replaced with shared Yorkville constants.
- `o-plates landing/terms.html`: Seller and contact updated; date October 22, 2026.
- `o-plates landing/privacy.html`: operator address updated; date October 22, 2026.
- `frozen_plate/presentation.py`: Yorkville footer added to newly rendered customer mail/pages only; stored captures are not read or rewritten.
- `api_app.py`: Yorkville footer added to newly generated fallback order email.
- The obsolete test-only supplier stub in `tests/test_launch_cleanup.py` was replaced with the new adapter dependencies; historical fixtures remain untouched. No other old-address matches were found in tracked content. Odoo's separately stored marketing draft is outside this repository and was not modified.

No Stripe settings, activation, prices, shipping, manufacturing geometry, stored records or production deployment changed. Handle-hole pricing remains unchanged.

## Historical PDF assertion review

Both parametrized historical cases (quantity 1 / 14 days and quantity 2 / 21 days) still exercise the actual Quote Cart PDF adapter with the same authoritative $140.39 unit price and $140.39/$280.78 extended prices. Every original customer-facing assertion has an equivalent assertion in the approved layout:

| Original assertion | Current assertion |
| --- | --- |
| Unit and extended prices | Same exact dollar values |
| `ships=14d` / `ships=21d` | Selected lead time, 14/21 calendar days (est.) |
| Subtotal | Quoted subtotal |
| Tax excluded and shipping selected at checkout | Sales tax calculated at checkout if applicable; shipping selected at checkout |
| Valid until November 18, 2026 | Issued October 19 and valid through November 18, 2026, using the business timezone |
| No staging/sandbox/debug copy | Same forbidden-copy assertions |

The tests additionally assert every customer-visible plate dimension, material, tolerance, chamfer size, marking, quantity, quote number and official address. The separate UTC-to-New-York boundary test remains. No original coverage was removed to obtain a pass.
