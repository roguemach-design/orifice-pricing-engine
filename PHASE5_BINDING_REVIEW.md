# Phase 5 staging binding investigation — 2026-09-30

## Verified current state

- Main and local `work/frozen-plate-staging-integration`: `94731f295fd842cdac8dbbbea44cc0e54f1832e8`. The branch was created from freshly fetched main, not the obsolete local publication snapshot.
- Render workspace: `roguemachine`, `tea-d51l4np5pdvs73eakerg`.
- Staging UI: `srv-d9rj427avr4c739dufkg`, `oplates-customer-ui-staging`.
- Staging API: `srv-d9ritcijobas73didpbg`, `oplates-pricing-api-staging`.
- Both services track `work/stack-merge-readiness-audit` and show deployed commit `84f2593222f38ba50aa301bf8986584a87666c92`.
- UI API_BASE: `https://oplates-pricing-api-staging.onrender.com`.
- UI SUPABASE_URL: `https://ixhnanttetuhpzvrnvdc.supabase.co`.
- API APP_ENV: `staging`; APP_BASE_URL: `https://oplates-customer-ui-staging.onrender.com`.
- API issuer: `https://ixhnanttetuhpzvrnvdc.supabase.co/auth/v1`; JWKS: same origin plus `/auth/v1/.well-known/jwks.json`; audience: `authenticated`.
- API DATABASE_URL hostname: `dpg-d9qte9ad0e5s73b35qng-a`. Verified by a read-only runtime command that printed only hostname and project-match booleans. No database credential was displayed or copied.
- Render resource inventory maps that exact host to `oplates-staging-db`, database `oplates_staging_db`, Staging environment `evm-d9qstc1t0dsc738ln9kg`. Production database is a distinct resource.
- Supabase connector confirms `ixhnanttetuhpzvrnvdc`, O-Plates Staging, ACTIVE_HEALTHY. Private artifact bucket is absent. Earlier empty-schema finding remains the baseline; no schema mutation performed.
- API runtime has no SENDGRID/SMTP/EMAIL-named configuration and no Supabase storage key. UI has a key named SENDGRID, but its value was not exposed and its delivery capability was not validated. The API code expects SENDGRID_API_KEY.
- Separate owner-acceptance UI/API services use `work/drawing-intake-phase1h-owner-acceptance`; these are not the target named staging pair and were not changed.

## Integration consequence

The application intentionally has two staging providers: Render Postgres for orders and Supabase for customer authentication. A correct Supabase authentication binding does not mean DATABASE_URL uses Supabase. Preserve the existing order database. Use a separate backend-only connection for the requested Frozen Plate schema in Supabase, and a separate private storage credential. Do not repoint DATABASE_URL or migrate existing orders to Supabase as incidental setup.

## Credential boundary / proposed next action

The staging API currently has no privileged Supabase backend credential. Provisioning access is necessary before deployed Frozen Plate database/storage integration can run. Proposed scope:

1. Dedicated staging-only Postgres login restricted to the Frozen Plate schema; no production access and no unrelated schema grants.
2. Existing staging Supabase server secret for private Storage API access, stored only in the staging API environment; never in the UI, chat, repository, reports, or logs. This secret has project-wide privileges and bypasses RLS; application authorization and server-only handling remain mandatory.
3. Dedicated random approval-signing key on the staging API, without rotation of existing credentials.
4. Mail defaults to disabled/capture until a delivery provider and authorized test recipient are configured.

Browser policy requires action-time confirmation when creating or materially expanding security-sensitive access. No credential was transferred or provisioned. The earlier request to reveal DATABASE_URL was rejected by automatic review; the safer hostname-only runtime check succeeded.

## Work status

No application implementation, migration, storage mutation, environment correction, deploy, push, merge, email, vendor submission, or production modification occurred. Tests were not rerun because application code is unchanged. This is verified infrastructure evidence, not Phase 5 acceptance completion.
