Customers need to recover a saved quotation and let a verified purchasing colleague order the original plate configurations through the existing Quote Cart and checkout.

Adds immutable saved quote/PDF versions, My Quotes, authenticated number lookup, exact-email purchasing invitations and revocation, current-price/lead-time review, expiry repricing and quote-to-paid-order association. The purchaser remains the order, Frozen Plate and approval identity.

Owner review corrections: ordinary A1/B5 single-plate initial/R2 PDFs fit one page in eight regression cases; complete specifications remain; absent optional features explicitly say None; printed route omits https:// and the full quote number stays together. Future links use the implemented authenticated My Quotes route and remain disabled in production.

Validation: 184 focused correction checks passed, then 8 checks for ordinary direct/cart checkout with saved quotes enabled/disabled and UI. Counts overlap. The 51 regenerated protected manufacturing hashes and separate 42 stored historical artifact hashes all match. PDF samples are in review/quote-phase2; scope reconciliation and exact evidence limits are in docs/quote-review-corrections.md.

CI adds disposable PostgreSQL competing-buyer, immutability and access-control coverage plus browser captures for retrieval, captured email return, sharing, wrong/expired/revoked invitations and existing cart handoff. Provider authentication/payment responses in local tests are simulated. Real staged Supabase identity, Stripe TEST payment/webhook, staged Frozen Plate approval and email sending readiness remain acceptance gates. SendGrid sending authorization has not been assumed from billing evidence.

Keep DRAFT. No merge, production deployment/migration, LIVE Stripe changes, customer emails or historical artifact alteration. All production saved-quote flags remain off; PDF ordering links require the real route to pass production acceptance and owner release approval.
