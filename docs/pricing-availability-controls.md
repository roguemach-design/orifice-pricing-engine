# Pricing & Availability consolidation

## Authority and unchanged behavior

The existing `app_config` row named `active` remains the sole active database configuration. Editor reads project existing code defaults in memory without writing them, resetting values, or changing the pricing version. Saving writes a complete validated configuration and preserves the prior raw configuration in a `pricing-history-<uuid>` row in the same transaction. No new database/schema is required. History rows are never consulted when calculating prices.

Pricing formulas, rounding, shipping formulas, quote/order storage, Frozen Plate evidence, manufacturing artifacts, Stripe configuration, and checkout activation gates remain unchanged. Direct Quote, embedded Quote, direct checkout and cart checkout use the existing API calculation path. Invalid availability at checkout now returns 422 rather than an unhandled calculation exception. A cart rejects a configuration-version change between its lines.

## Controls and audit

| Parameter | Before | New owner control | Existing code default |
| --- | --- | --- | --- |
| Material availability | Database and legacy UI | Migrated | 304/316/Carbon Steel enabled; Monel/Hastelloy disabled |
| Thickness availability | Database and legacy UI | Migrated | Existing catalog and toggles preserved |
| Material price / square inch | Database and legacy UI | Migrated | Existing 12 prices unchanged |
| Lead-time availability | Database and legacy UI | Migrated | 14 and 21 enabled; 7 disabled |
| Default lead time | Database and legacy UI | Migrated | 14 days |
| Laser cost / linear inch | Code only | Database override on explicit save | 0.826 |
| Mill labor / hour | Code only | Database override on explicit save | 150 |
| Mill / chamfer speed | Code only | Database override on explicit save | 28 / 28 inches per minute |
| Load time | Code only | Database override on explicit save | 6 minutes |
| Inspection times | Code only | Database override on explicit save | 0.005: 6; 0.002: 12; 0.001: 18 minutes |
| Quantity tiers | Code only | Database override on explicit save | 1: 1.00; 5: .97; 10: .95; 25: .92; 50: .90 |
| Effective lead-time multipliers | Code only | Database override on explicit save | 14: 1.6; 21: 1.0 |
| Density | Database, no legacy UI | Editable | 304/316: .289; carbon: .283; Monel: .319; Hastelloy: .322 |
| Weight multipliers | Database, not used by pricing formula | Read-only, preserved | 304/316: 1.06; carbon: 1.00 |
| Plate/bore/marking limits | Database, no legacy UI | Editable | 48 inches / 19 inches / 40 characters |
| Shipping constants/package allowances | Code only | Not exposed | Unchanged |
| Geometry/process formula constants | Code only | Not exposed | Unchanged |

The master 7-day multiplier is 2.3 in `tuning_knobs.py`, but the current runtime removes it before API baseline capture. It remains unavailable in this release. Enabling unsupported materials or lead times requires a separately reviewed capability change. No proposed additional lead-time margins are introduced.

## Validation and recovery

- Owner authorization and rate limits remain enforced by the API, including history, reset and restore routes.
- All writes require a read version and explicit action confirmation. Conditional database update provides cross-process concurrent-edit protection; stale saves return 409.
- Input validation rejects malformed/nonfinite/negative/incomplete configurations, nonboolean toggles, unsupported catalogs, missing prices or densities for enabled materials, disabled defaults, zero machining speeds, incompatible bore limits and invalid quantity tiers. Numeric values above 1,000,000 are rejected as outside the supported range.
- Save displays a before/after summary and requires confirmation tied to the current draft. Drafts survive workspace navigation; warnings identify unsaved changes. Reload/discard requires acknowledgement when dirty. Browser closure can still lose an unsaved draft.
- Reset requires `RESET DEFAULTS`; restore requires `RESTORE CONFIGURATION`. Both require the current version, show differences, validate the target, and preserve the previous configuration transactionally.
- The editor shows the latest 50 recovery snapshots; older records remain in the database. No prior history is invented.
- Legacy admin remains available. Its compatibility patch supplies versioned, confirmed writes and a cached editing snapshot. It must be deployed with this API change.

## Acceptance

All write testing uses an isolated in-memory database and mocked Stripe. A 720-case pricing matrix compares every output across supported materials, thicknesses, lead times, quantity tiers, chamfer choices and tolerances. New tests exercise read-without-write, save/conflict/restore/reset, input rejection, owner authorization, real database quote/checkout parity with Stripe mocked, unchanged stored order payloads, and UI confirmation/draft retention.

Production acceptance must remain read-only. Do not save, reset or restore active production settings for testing. Do not retire the legacy admin without explicit owner authorization.
