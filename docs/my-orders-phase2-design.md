# OP-IMP-013 — Phase 2 reorder architecture (design only)

No reorder action, endpoint, persistence, button or checkout behavior is implemented
by Phase 1. This document is not authorization to build or deploy Phase 2.

## Exact plate

1. Existing customer authentication and ownership authorize the source order/line.
2. Server resolves an explicitly selected approved revision and verifies the
   immutable specification, source and approval/PDF bindings. Use canonical Frozen
   Plate fields, not an old quote payload or display text.
3. Map canonical geometry into the existing configurator schema using a versioned,
   round-trip-tested adapter. Preserve material/thickness, OD/bore, tolerance,
   handle geometry/hole, marking, chamfer angle/face/flow/radial-width semantics.
   Missing/unsupported historical fields block instant reorder; do not default them.
4. Customer chooses a new quantity and currently available lead time. Validate
   against current geometry/material/capacity rules and get a fresh authoritative
   quote/version. Historical prices, payment sessions and approvals are never reused.
5. Existing quote/cart/checkout creates new identities. The new paid order creates
   new Frozen Plate revisions and requires fresh deliberate drawing approval.

## With changes

Load an owned approved source through that same server-controlled adapter into the
existing configurator. Preserve configuration across authentication using the
existing mechanism. Every edit is a new specification; validate/reprice normally.
No special bypass for source approval, old availability, unknown fields or TEST.

## One / selected / all lines

The selected source lines each carry their own approved revision. A new cart has
new line IDs and quantities. Server rechecks every source ownership/revision and
availability when quoting and checking out. Define how to handle a source revision
superseded after selection: block/review rather than silently switching revisions.
Unavailable lines remain visible with explanations; no silent substitutions.

## Provenance and isolation

Proposed new-line provenance: source_order_id, source_line_id,
source_revision_id, source_spec_sha256 and adapter_version, stored by the server
separately from editable dimensions. A source pointer grants no access by itself.
Never mutate the source record, copy an approval, reuse a Stripe payment, infer
shipment, trigger sourcing or release manufacturing. TEST/LIVE restrictions and
stale-price rejection apply normally to every new checkout.

Before implementation, review whether the existing immutable new-order source
snapshot safely supports these additive provenance fields. If a new database
constraint/schema or buyer authorization model is required, stop and request
separate scope approval. No such change is included in Phase 1.

## Phase 2 acceptance proposal

Canonical round-trip tests for all supported options/tolerances and standard
chamfer; exact and changed single/multiple plates; current price/availability
changes; stale versions; superseded/incomplete legacy sources; cross-customer
source attacks; TEST/LIVE isolation; independent new identities and new approvals;
unchanged source records and protected artifact hashes. Quote #42 integration is
an explicit dependency if saved quotes become part of the chosen journey.
