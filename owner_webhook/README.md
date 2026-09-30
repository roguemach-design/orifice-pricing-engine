# Owner-test Stripe webhook ingress

Standalone relay for the isolated owner-test environment. It does not import the
quote API, connect to a database, calculate prices, or complete orders. The
existing private API remains responsible for independent signature verification
and idempotent order persistence.

Deploy only this Dockerfile, from a separate infrastructure branch:
`owner_webhook/Dockerfile`, repository root build context, Ohio, one paid
`0.5c-512mb` instance, auto-deploy off, health route `/health`.
Configure only `STRIPE_WEBHOOK_SECRET` from the dedicated TEST destination.
No Stripe API key belongs on the relay. Never reveal secrets in browser output.

Business route: `POST /stripe/webhook`. Fixed destination:
`http://oplates-owner-acceptance-api:10000/stripe/webhook`.
The caller cannot select a destination. Redirects are not followed. The original
body and signature are forwarded only after local signature verification and an
explicit `livemode=false` check. Other signed TEST event types are acknowledged
without forwarding. Request bodies and private API responses are never logged or
returned. Access logs are disabled in the Docker command.

Limits: 1 MiB body, five-second body-read deadline, ten-second total forwarding
deadline, four concurrent handlers, eight Uvicorn connections. Capacity/upstream
failures return retryable errors; no local retry or persistent queue is used.
Payloads are retained only in request memory. TEST retries/replays are forwarded
to the existing API's order-idempotency logic; local tests prove transport replay,
not deployed payment/order integrity.

Before connecting Stripe, verify live database isolation, TEST credentials,
matching signing secrets, rejection paths, and private connectivity. Keep UI
checkout disabled until all critical live gates pass. Rollback: disable the UI
checkout switch, then disable the Stripe TEST destination or suspend this relay.
Do not change the shared staging/production network or API code.

Tests: `python -m pytest -q tests/test_owner_webhook.py`.
