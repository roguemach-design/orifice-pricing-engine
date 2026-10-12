# Landing page and configurator convergence

The accepted public landing copy remains in `o-plates landing/index.html`.
Its three configure CTAs now scroll to an embedded instance of the canonical
customer configurator, immediately after the hero. `/Quote` remains a direct,
compatible route; success, approval, account, cart, recovery, and internal
sourcing URL paths are retained.

## Source and scope

- Branch: `work/landing-configurator-convergence`.
- Accepted configurator/analyzer/handle-hole baseline: `a97a664686ca91d8edaa42f223542ac284b78c34`.
- Existing production private API binding retained from `d55a682af59cb52966abf1455360a0af6c26a15a`.
- Landing copy retained from `80b288fc10e34c6270968fcddb8666a14fe96bb4`, matching fetched public HTML.
- The requested eyebrow is restored; existing purchasing, documentation, FAQ,
  engineering contact, and How it works copy is preserved.

Material, thickness, tolerance, lead time, chamfer, and handle-hole selections
use native single-select segmented controls, with wrapping and required
selection semantics. Unresolved analyzer values remain unresolved. Options
come from the same active availability configuration. Explicit chamfer side,
flow orientation, and width-definition choices also use buttons. Dimensions,
marking, quantity, fraction parsing, and analyzer review remain unchanged.

Customer navigation advertises Configure your plate, My Orders, and Quote Cart.
Success, Drawing Approval, and Internal Sourcing are registered hidden routes;
their server authorization and deliberate approval checks are unchanged.
Embedded customers receive an in-page Account panel using the existing session
restore, refresh, and login code. Standalone customers retain their sidebar.

## Embed behavior

The static page embeds `https://quote.o-plates.com/Quote?embed=true&integrated=1`.
The configurator emits only content height, never form, order, or authentication
data. The parent accepts heights only from its own configurator frame or direct
child component with the exact quote origin and a bounded finite value. The
fallback frame is generous and remains scrollable if automatic sizing fails.
The direct configurator link remains available. No auth tokens are placed in
the frame URL.

## Validation

The unchanged accepted baseline passed 617 tests with five private-corpus skips.
The baseline fixture records actual pre-change UI requests for:

1. 304 / 0.125 inch / ±0.005 / 21 days / no chamfer / no hole.
2. 316 / 0.250 inch / ±0.002 / 14 days / no chamfer / handle hole.
3. Carbon steel / 0.375 inch / ±0.001 / 21 days / explicit chamfer / handle hole.

New controls reproduce those exact request dictionaries, pricing results,
canonical spec hashes, and SVG/PDF/DXF fingerprints. Existing analyzer,
manual fallback, confirmation invalidation, order recovery, auth, approval,
sourcing authorization, and Frozen Plate tests remain included in the full suite.
The final local suite passed **626 tests with five private-corpus skips**.
Python compilation, JavaScript syntax, and whitespace checks passed.

Additional checks cover material-specific thickness availability, unresolved
choices, root routing, compatible hidden routes, and embed message validation.

## Deployment verification

The owner confirmed Render workspace `roguemachine`
(`roguemach@gmail.com`, `tea-d51l4np5pdvs73eakerg`). The original integration
commit `98f7f0e4fb8db4b49298eb47817b8a284c3762b2` was deployed to the production
UI and landing services using exact-commit manual deployment. No service branch,
environment variable, API deployment, or maintenance setting was changed.

Live verification exposed a cold-start defect: direct `/Quote` entry could run
before the root initialized `st.navigation`, exposing legacy navigation and
omitting the integrated shell. Customer shell rendering now runs from the shared
account renderer on every customer page, and Streamlit legacy sidebar navigation
is disabled at configuration level. Session, authorization, pricing, and artifact
behavior remain unchanged. Customer UI tests now register the actual route set,
rather than treating individual page scripts as isolated applications. The fix
passed 128 focused navigation/auth/configurator/analyzer/cart/handle-hole tests.

The production API remains at `a97a664686ca91d8edaa42f223542ac284b78c34`, with
maintenance ON. UI maintenance remains OFF. Checkout was visibly disabled on
the public configurator. The embedded frame loaded and resized automatically.
Final corrected UI deployment and authenticated/responsive checks are pending.


## Focused configurator UX refinement

Based on the verified convergence head `917e1cbc526aeb1e7c730e8a96cccee89efde87e`.
Signed-in customers receive an inline identity and tertiary Log out control.
Signed-out customers retain the existing OTP form in a compact Account expander,
without a duplicate heading. Cookie restore, refresh, OTP calls, authorization,
and logout/session clearing are unchanged.

Configure your plate is the primary heading below customer navigation and account
status. The upload area is an unbordered section with customer-facing instructions,
file selection/status and Analyze drawing controls. The existing upload validation,
auth gate, analyzer review, failure handling and manual reset remain intact.

Material uses the same required, single-select native control and state key with
richer selectable card labels and scoped texture/selected-state styling. Only
options supplied by current availability are rendered; canonical values remain
`304`, `316`, and `Carbon Steel`. Thickness, tolerance, delivery, chamfer and handle
hole controls remain unchanged. Pricing, geometry, artifacts, spec hashes and
Frozen Plate implementation are untouched.

Deployment is currently blocked: the Render connector cannot specify the new
commit, while the exact-commit Dashboard deployment path requires a signed-in
session. Both production UI and landing remain on `917e1cbc526a`. No environment,
maintenance, API, Stripe, SendGrid or sourcing settings were modified. No vendor
submission or manufacturing release occurred. Owner sign-in and public browser
verification were not requested or performed in this refinement task.

Validation: final suite **629 passed, 5 private-corpus skips**. All three
accepted pricing/request and SVG/PDF/DXF/spec golden cases remain identical.
Compact signed-in status/logout and unresolved/canonical material-card selection
are covered by application tests. Python compilation and whitespace checks pass.
