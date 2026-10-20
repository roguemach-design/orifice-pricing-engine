"""Temporary authenticated visual review; never part of the production release."""

import json
import os
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pricing_engine import QuoteInputs, calculate_quote

REVIEW_SERVICE = "srv-dapgr4qd0e5s73fqk4t0"
AUTH_API = "http://oplates-owner-acceptance-api:10000"
CONFIG = dict(
    materials=["304", "316", "Carbon Steel"],
    thicknesses_by_material={m: [.125, .25, .375, .5] for m in ["304", "316", "Carbon Steel"]},
    lead_times_days=[14, 21], default_lead_time_days=14,
    tolerance_options_in=[.001, .002, .005], max_paddle_dia_in=48,
    max_bore_dia_in=19, max_handle_label_chars=40,
)


def review_environment(source):
    if source.get("RENDER_SERVICE_ID") != REVIEW_SERVICE:
        raise ValueError("This review launcher is restricted to the owner-acceptance UI")
    if source.get("API_BASE", "").rstrip("/") != AUTH_API:
        raise ValueError("Expected the isolated owner-acceptance authentication API")
    if source.get("OPLATES_OWNER_ACCEPTANCE_MODE") != "true":
        raise ValueError("Owner-acceptance checkout guard is required")
    if source.get("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", "false") != "false":
        raise ValueError("Checkout must remain disabled")
    if any(source.get(k) for k in ("DATABASE_URL", "STRIPE_SECRET_KEY", "SENDGRID_API_KEY", "SUPABASE_SERVICE_ROLE_KEY")):
        raise ValueError("Data/payment/email credentials are forbidden in this review UI")
    env = dict(source)
    env.update(
        V71_REVIEW_AUTH_API_BASE=AUTH_API,
        V71_REVIEW_AUTH_API_KEY=source.get("API_KEY", ""),
        API_BASE="http://127.0.0.1:8505", API_KEY=secrets.token_urlsafe(32),
        OPLATES_DRAWING_ASSISTED_ENABLED="false",
        OPLATES_OWNER_ACCEPTANCE_MODE="true", OPLATES_OWNER_TEST_CHECKOUT_ENABLED="false",
    )
    return env


def handler_class(api_key):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self):
            if self.path == "/config/active":
                return self.reply(CONFIG)
            self.reply({"detail": "Unavailable in visual review"}, 404)

        def do_POST(self):
            if self.path != "/quote":
                return self.reply({"detail": "Unavailable in visual review"}, 405)
            if not secrets.compare_digest(self.headers.get("x-api-key", ""), api_key):
                return self.reply({"detail": "Unauthorized"}, 401)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    return self.reply({"detail": "Invalid request size"}, 400)
                data = json.loads(self.rfile.read(size))
                result = calculate_quote(QuoteInputs(**data))
                return self.reply({**result, "configuration_id": "SYNTHETIC-V71-REVIEW"})
            except (TypeError, ValueError):
                return self.reply({"detail": "Invalid synthetic configuration"}, 400)

        def log_message(self, *args):
            pass
    return Handler


def main():
    env = review_environment(os.environ)
    server = ThreadingHTTPServer(("127.0.0.1", 8505), handler_class(env["API_KEY"]))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return subprocess.call([
            sys.executable, "-m", "streamlit", "run", "review_only/app.py",
            "--server.address", "0.0.0.0", "--server.port", env.get("PORT", "10000"),
            "--server.headless", "true", "--browser.gatherUsageStats", "false",
        ], env=env)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
