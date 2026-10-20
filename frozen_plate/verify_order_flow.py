"""Synthetic deployed-code acceptance against real staging databases/private storage.

Run only on the staging API. Customer dependency overrides are confined to this
separate process: browser sign-in and public JWT validation remain separate checks.
No Stripe requests, customer emails, vendor submissions or manufacturing release.
Only boolean checks and synthetic record identifiers are printed.
"""

import os
import json
import time
import hmac
from hashlib import sha256
from uuid import uuid4
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from email import policy
from urllib.parse import urlsplit

from fastapi.testclient import TestClient


def main():
    checks = {}
    try:
        assert os.environ.get("APP_ENV") == "staging"
        assert os.environ.get("FROZEN_PLATE_EMAIL_MODE") == "capture"
        assert urlsplit(os.environ["DATABASE_URL"]).hostname.startswith(
            "dpg-d9qte9ad0e5s73b35qng-a"
        )
        assert os.environ["FROZEN_PLATE_STORAGE_KEY"].startswith("sb_secret_")
        import api_app as app
        from .api import repository

        repo = repository()
        customer = "staging-accept-" + uuid4().hex[:16]
        oid = str(uuid4())
        session = "cs_test_phase5_" + uuid4().hex
        config = {
            "paddle_dia": 5.0,
            "bore_dia": 1.548,
            "handle_width": 2.0,
            "handle_length_from_bore": 10.5,
            "material": "304 Stainless Steel",
            "thickness": 0.125,
            "bore_tolerance": 0.002,
            "chamfer": False,
            "handle_label": "STAGING TEST",
            "quantity": 1,
        }
        with app.SessionLocal() as db:
            db.add(
                app.Order(
                    id=oid,
                    stripe_session_id=session,
                    customer_id=customer,
                    status="pending",
                    quote_payload=config,
                )
            )
            db.commit()
        event = {
            "id": "evt_phase5_" + uuid4().hex,
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {
                "object": {
                    "id": session,
                    "payment_status": "paid",
                    "amount_total": 10000,
                    "amount_subtotal": 10000,
                    "metadata": {"customer_id": customer},
                }
            },
        }
        raw = json.dumps(event).encode()
        ts = str(int(time.time()))
        sig = hmac.new(
            app.WEBHOOK_SECRET.encode(), ts.encode() + b"." + raw, sha256
        ).hexdigest()
        headers = {"stripe-signature": f"t={ts},v1={sig}"}
        admin = {"x-api-key": app.ADMIN_API_KEY}
        with TestClient(app.app, raise_server_exceptions=False) as client:
            with patch.object(
                app.stripe.checkout.Session,
                "retrieve",
                side_effect=RuntimeError("synthetic test"),
            ), patch.object(
                app, "_send_email", side_effect=AssertionError("email attempted")
            ):
                response = client.post("/stripe/webhook", content=raw, headers=headers)
                checks["completed_order_trigger"] = response.status_code == 200
                checks["completion_replay"] = (
                    client.post(
                        "/stripe/webhook", content=raw, headers=headers
                    ).status_code
                    == 200
                )
            with app.SessionLocal() as db:
                checks["real_render_order_completed"] = (
                    db.get(app.Order, oid).status == "completed"
                )
            plates = client.get(
                "/admin/frozen-plates", params={"order_id": oid}, headers=admin
            ).json()
            assert len(plates) == 1
            plate = plates[0]
            revision = repo.revision(plate["current_revision"])
            checks["stable_order_line"] = (
                plate["order_id"] == oid
                and plate["line_id"] == "line-1"
                and revision["number"] == 1
            )
            checks["customer_unauthenticated_rejected"] = (
                client.post(
                    "/me/frozen-plates/inspect", json={"token": "test"}
                ).status_code
                == 401
            )
            checks["admin_unauthenticated_rejected"] = (
                client.get("/admin/frozen-plates/" + plate["id"]).status_code == 401
            )
            app.app.dependency_overrides[app._require_customer_user_id] = (
                lambda: customer
            )
            delivery = client.post(
                "/me/frozen-plates/" + plate["id"] + "/confirmation", json={}
            ).json()
            token = delivery["token"]
            pdf = client.post("/me/frozen-plates/pdf", json={"token": token})
            checks["owner_exact_pdf"] = (
                pdf.status_code == 200
                and sha256(pdf.content).hexdigest()
                == revision["artifacts"]["pdf"]["sha256"]
            )
            for method in ("get", "head"):
                response = getattr(client, method)("/approve/" + token)
                checks["passive_" + method] = (
                    response.status_code == 200
                    and repo.plate(plate["id"])["lifecycle"]
                    == "READY_FOR_CUSTOMER_CONFIRMATION"
                )
            detail = client.get(
                "/admin/frozen-plates/" + plate["id"], headers=admin
            ).json()
            capture = client.get(
                "/admin/frozen-plates/deliveries/"
                + detail["deliveries"][-1]["id"]
                + "/capture",
                headers=admin,
            )
            message = BytesParser(policy=policy.default).parsebytes(capture.content)
            attachments = list(message.iter_attachments())
            checks["captured_email_exact_attachment"] = (
                capture.status_code == 200
                and len(attachments) == 1
                and attachments[0].get_payload(decode=True) == pdf.content
            )
            app.app.dependency_overrides[app._require_customer_user_id] = (
                lambda: customer + "other"
            )
            checks["wrong_customer_rejected"] = (
                client.post(
                    "/me/frozen-plates/approve", json={"token": token}
                ).status_code
                == 409
            )
            app.app.dependency_overrides[app._require_customer_user_id] = (
                lambda: customer
            )
            checks["tamper_rejected"] = (
                client.post(
                    "/me/frozen-plates/approve", json={"token": token + "x"}
                ).status_code
                == 409
            )
            approved = client.post("/me/frozen-plates/approve", json={"token": token})
            checks["deliberate_approval_success"] = (
                approved.status_code == 200
                and "YOUR ORDER IS IN PRODUCTION" in approved.json()["success_html"]
            )
            checks["approval_idempotent"] = (
                client.post(
                    "/me/frozen-plates/approve", json={"token": token}
                ).status_code
                == 200
            )
            for route in ("SENDCUTSEND", "ALRO", "ROGUE_INTERNAL"):
                selected = client.post(
                    "/admin/frozen-plates/revisions/" + revision["id"] + "/source",
                    json={"route": route},
                    headers=admin,
                )
                checks["source_" + route] = (
                    selected.status_code == 200 and selected.json()["released"] is False
                )
            dxf = client.get(
                "/admin/frozen-plates/revisions/" + revision["id"] + "/dxf",
                headers=admin,
            )
            checks["exact_approved_dxf"] = (
                dxf.status_code == 200
                and sha256(dxf.content).hexdigest()
                == revision["artifacts"]["dxf"]["sha256"]
            )
            checks["customer_dxf_denied"] = (
                client.get(
                    "/admin/frozen-plates/revisions/" + revision["id"] + "/dxf"
                ).status_code
                == 401
            )
            r2 = client.post(
                "/admin/frozen-plates/orders/" + oid,
                headers=admin,
                json={
                    "line_index": 0,
                    "part_identifier": "STAGING-R2",
                    "expected_current": revision["id"],
                    "reason": "Synthetic R2 acceptance",
                },
            ).json()
            checks["r2_immutable_history"] = (
                r2["number"] == 2
                and repo.revision(revision["id"])["artifacts"] == revision["artifacts"]
            )
            checks["r1_does_not_approve_r2"] = (
                client.post("/me/frozen-plates/approve", json={"token": token}).json()[
                    "context"
                ]["revision"]
                == "R1"
                and repo.plate(plate["id"])["lifecycle"]
                == "READY_FOR_CUSTOMER_CONFIRMATION"
            )
            checks["stale_sourcing_denied"] = (
                client.post(
                    "/admin/frozen-plates/revisions/" + revision["id"] + "/source",
                    json={"route": "ALRO"},
                    headers=admin,
                ).status_code
                == 409
            )
            checks["stale_dxf_denied"] = (
                client.get(
                    "/admin/frozen-plates/revisions/" + revision["id"] + "/dxf",
                    headers=admin,
                ).status_code
                == 409
            )
            current = client.post(
                "/me/frozen-plates/" + plate["id"] + "/confirmation", json={}
            ).json()
            checks["r2_deliberate_approval"] = (
                client.post(
                    "/me/frozen-plates/approve", json={"token": current["token"]}
                ).status_code
                == 200
            )
            with ThreadPoolExecutor(max_workers=3) as pool:
                statuses = list(
                    pool.map(
                        lambda _: client.post(
                            "/admin/frozen-plates/orders/" + oid + "/complete",
                            headers=admin,
                        ).status_code,
                        range(3),
                    )
                )
            checks["concurrent_completion_retries"] = (
                statuses == [200] * 3
                and repo.plate(plate["id"])["current_revision"] == r2["id"]
            )
            app.app.dependency_overrides.clear()
        checks["capture_only"] = os.environ["FROZEN_PLATE_EMAIL_MODE"] == "capture"
        print(
            json.dumps(
                {
                    "verification_completed": all(checks.values()),
                    "checks": checks,
                    "synthetic_order_id": oid,
                    "synthetic_plate_id": plate["id"],
                    "customer_auth": "synthetic principal; real browser sign-in remains required",
                },
                sort_keys=True,
            )
        )
        if not all(checks.values()):
            raise SystemExit(1)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "verification_completed": False,
                    "checks": checks,
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
