# OP-IMP-013 — My Orders Phase 1

## Focused release corrections

Order-number search accepts ASCII decimal order numbers (with optional `OP-`
and surrounding whitespace). Unicode numeric characters such as superscript
`²` previously passed `str.isdigit()` but failed `int()`. Unsupported forms now
return no matches; owned-order filtering and parameterized queries are unchanged.

An isolated Chromium trace of the prior UI caught a required lead time changing
from 14 to `None` during the conditional chamfer-widget rerun, **before** the
sign-in capture or cookie write. Its committed form snapshot still held 14.
The later missing quote metrics therefore did not establish lost credentials or
a database persistence regression. This is a native widget/remount state race.
The lead-time control now recovers an empty native value only from a still-valid
committed snapshot. A current valid edit takes priority; drawing-required `None`
and disabled/removed choices are never defaulted. Authentication, cookie/session
rotation, and API availability controls are unchanged.

Regression coverage includes Unicode searches, preserved current/default lead
times, intentionally unresolved/removed options, and both 14/21-day real-browser
journeys on direct/embedded routes with/without chamfer. Lead-time assertions run
before and after sign-in and inspect the actual quote payload; original auth,
revocation, logout and archive assertions remain intact.

PostgreSQL `permission denied` messages in CI correspond to the five prohibited
checkout-control statements and four prohibited analytics statements inside
`pytest.raises(DBAPIError)` in `test_checkout_control_postgres.py` and
`test_journey_postgres.py`. These are deliberate security gates on disposable
loopback CI databases, not uncaught production application failures.

Refs #65. Development/PR only; no merge, deploy, migrations, production writes,
checkout changes or staging recovery. Reorder is design-only in the separate
`my-orders-phase2-design.md`.

## Baselines and exact release dependencies

This is a customer-based review branch, with public source parent
`edee47e53ee35f47f3b4c52ccec96b279c752df5`. It must **never be deployed as an
entire API image**: that could lose separately approved backend pricing/shipping
changes. Exact operational baselines and deployment IDs are reported privately.

Before an owner-approved release, integrate only these backend paths onto the
independently verified API release: `api_app.py` (the additive history endpoints
and router callback), `customer_order_history.py`, `frozen_plate/api.py`,
`frozen_plate/customer_archive.py`. Preserve all existing shipping and pricing
model identifiers. Test that isolated API integration before issuing an exact
release SHA. Deploy API first, then customer UI. Manufacturing Control, landing
and obsolete standalone `my-orders` need no deployment. No deferred worker,
quote PRs or quality-document implementation is included.

## Verified causes and existing infrastructure

Canonical route: `/My_Orders`, implemented by `pages/2_My_Orders.py` within the
existing Streamlit navigation. The legacy `my_orders_app.py`/`customer_portal.py`
redirectors remain unchanged. The old page uses an order table plus a separate
selection dropdown and a maximum of 200 records. Existing `/me/orders` and
`/me/orders/{id}` expose only completed owned orders and are retained unchanged
for compatibility.

The old UI immediately `continue`s after CUSTOMER_APPROVED/READY_FOR_RELEASE,
removing drawing actions. The old PDF endpoint requires a token, and creating a
new confirmation delivery is only allowed for the current pending revision.
An existing approved token can read a PDF until expiry/revocation; there was no
permanent authenticated archive independent of that token.

Frozen Plates and approvals are in the existing protected
`frozen_plate_production` schema; PDFs are in the existing private production
bucket. The new read routes reuse the repository and existing bearer identity.
No public Storage URLs, signed-link service, new identities, corporate access,
new role, tables, grants, migrations, geometry generators or token renewal.
Manufacturing Control's compact order/detail/revision organization is a design
reference only. Its client, admin credentials and permissions are not imported.

## Current versus proposed

| Capability | Existing | Phase 1 |
|---|---|---|
| Find orders | Table and separate dropdown | Order cards, exact order-number search, four sort orders, 20-row pagination over owned history |
| Pending records | Excluded | Clearly distinguished from payment recorded; missing totals remain unknown |
| Navigation | Choose again from dropdown | Open detail / return to retained filters and page |
| Multi-plate | Raw input tables | Separate numbered plate panels, original purchased specifications and quantity |
| Prices | Order total | Recorded subtotal/shipping/total; missing line/unit snapshots explicitly unavailable |
| Approved drawings | Controls disappear | Read-only current and historical approved PDF archive |
| Pending drawings | Token-based approval | Same deliberate confirmation/PDF/approval pathway |
| Revisions | Current lifecycle only | Number/date/current/historical/approval state and customer-safe frozen specifications |
| Preview | None | Page 1 rasterized from the exact verified stored PDF; download all original PDF bytes |
| Fulfillment | Approval could imply production | Approval never asserts manufactured, inspected, certified or shipped |
| Quality documents | No released customer document records | Honest unavailable state; #64 remains a separate integration |
| Reorder | None | Not implemented; separate Phase 2 architecture |

## Desktop/mobile proposal and implementation

Desktop: My Orders title and short purpose; Start a quote action; search and sort;
compact bordered order cards showing number/date, plate-entry count, recorded
amount, payment state and conspicuous TEST label. View order opens its detail.
Detail has Back, order summary, recorded amounts, separate plate panels, original
purchased specification table, drawing state and revision expanders. Selecting an
approved revision displays its actual stored PDF page 1, SHA-256 and exact PDF
download. Shipping/document details are secondary.

Mobile uses the same canonical route and single-column flow. Native Streamlit
columns stack; tables scroll within their own container. Actions have text
labels and no hover-only behavior. Test viewports are 1280 and 390 pixels; browser
gates check no page overflow, exact downloaded bytes, visible preview and logout.
The CI browser artifact contains list and drawing screenshots at both sizes.
No public UI displays sourcing, Haas NC, DXF, source JSON, internal notes, token
fingerprints, recipient registries or administrative prices.

## API surfaces

| Route | Purpose / authority |
|---|---|
| GET `/me/order-history` | Existing verified customer identity; owned orders only, bounded pagination, validated search/sort; safe projection |
| GET `/me/order-history/{id}` | Explicit order ownership; allowlisted purchased specifications, recorded totals and address |
| GET `/me/orders/{id}/drawing-archive` | Business-order ownership plus matching Frozen Plate customer/order; read-only revision metadata |
| GET `/me/orders/{id}/drawings/{revision}/pdf` | Recheck order/revision/customer ownership, canonical parent hashes and complete approval binding; read and SHA-256/size-check only the PDF |

Unauthorized private object access is denied before Storage reads. Only approved
revisions can use the archive PDF route; historical unapproved revisions display
metadata without download. Original approval endpoints and transition protections
remain unchanged. GETs create no deliveries, confirmation tokens, revisions or
approvals. Responses contain no private object keys. PDF responses are private,
no-store, nosniff, with exact revision/hash headers; frontend verifies both and
byte length before showing or downloading. No shared PDF/data cache is added.

## Historical record policy

Operational record findings are reported privately, rather than publishing
production order states, totals, artifact identities or approval fingerprints.
The tests use isolated synthetic records for approved, pending two-line and
incomplete historical cases. The page displays persisted states and exceptions;
no historical repair/backfill, inferred approval, repricing or regenerated
artifact is attempted. Historical approval discrepancies are not forced to match.

## Gaps and decisions

* Historical line/unit accepted prices are not retained in the inspected snapshots.
  Display the recorded order amounts without dividing, reallocating or repricing.
  Persisting future accepted per-line snapshots is a separate checkout/data-scope
  decision; no migration or historical write is proposed here.
* Trustworthy customer shipment/tracking, material-cert and final-inspection
  records are not integrated. Show unavailable, never complete/pending assertions
  unsupported by records. Quality-document release is dependent on #64.
* Corporate/invited-buyer ownership and reorder provenance storage are outside
  Phase 1. Existing individual ownership is preserved.
* A PDF preview requires the existing PDFium dependency and a readable stored PDF;
  failed preview still permits a verified original PDF download. Integrity failure
  permits neither preview nor download.

## Acceptance and release gates

Automated tests cover current and historical approvals, expiry-independent archive,
identity and hash bindings, missing/ambiguous historical records, two-line orders,
unauthenticated/cross-customer access, no object read before authorization, exact
PDF bytes and no DXF downloads, unchanged repository rows, search/sort/pagination,
pending amounts, privacy-safe projections, UI navigation, tampered PDF suppression,
actual desktop/mobile routes, download SHA-256 and logout. Full regression and the
51-hash protected-output test are required.

Owner review and separate exact-commit release authorization remain required.
Production browser acceptance has not been performed. No TEST purchases are
required for historical archive acceptance; use existing owned records. Staging
stays suspended, checkout remains TEST, LIVE stays unavailable.
