"""Exact-PDF production delivery with a durable, immutable one-attempt claim.

Provider-ambiguous attempts require operator reconciliation, never a blind resend.
No customer email is sent from staging or merely by mounting the API routes.
"""

import base64
from email import policy
from email.parser import BytesParser
import json
import os
import re
from urllib.parse import urlsplit

import requests

from .presentation import APPROVAL_COPY, BUTTON
from .repository import WorkflowError, digest
from .runtime import PRODUCTION_API


def _journal(repo, key):
    if hasattr(repo.storage, "get_optional"):
        raw = repo.storage.get_optional(key)
        return None if raw is None else json.loads(raw)
    # In-memory test stores use a missing-key WorkflowError.
    try:
        return json.loads(repo.storage.get(key))
    except WorkflowError:
        return None


def send_confirmation(repo, snapshot, revision_id, *, environ=None, post=requests.post):
    env = os.environ if environ is None else environ
    if (
        env.get("APP_ENV") != "production"
        or env.get("FROZEN_PLATE_ENABLED") != "true"
        or env.get("RENDER_SERVICE_ID") != "srv-d51l6ch5pdvs73ealnh0"
        or env.get("FROZEN_PLATE_EMAIL_MODE") != "send"
        or repo.delivery_origin != PRODUCTION_API
    ):
        raise WorkflowError("production email delivery configuration required")
    key = env.get("SENDGRID_API_KEY", "")
    recipient = snapshot.get("customer_email", "")
    sender = env.get("FROM_EMAIL", "orders@o-plates.com")
    if (
        not key
        or sender not in {"orders@o-plates.com", "no-reply@o-plates.com"}
        or not isinstance(recipient, str)
        or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", recipient)
    ):
        raise WorkflowError("verified order recipient and production sender required")
    prefix = "email-delivery/" + revision_id + "/"
    # Workflow writes share this lock: revision supersession cannot race the send.
    with repo.transaction() as db:
        revision, artifacts, contents = repo._verified(db, revision_id)
        plate = repo._one(
            db, "SELECT * FROM frozen_plates WHERE id=?", (revision["plate_id"],)
        )
        if (
            plate["order_id"] != snapshot["id"]
            or plate["customer_id"] != snapshot["customer_id"]
            or plate["current_revision"] != revision_id
        ):
            raise WorkflowError("current order/customer/revision binding required")
        delivery = db.execute(
            "SELECT * FROM frozen_plate_deliveries WHERE revision_id=? ORDER BY generated_at DESC",
            (revision_id,),
        ).fetchone()
        if (
            not delivery
            or delivery["recipient_id"] != snapshot["customer_id"]
            or delivery["pdf_id"] != artifacts["pdf"]["id"]
        ):
            raise WorkflowError("exact captured confirmation required")
        raw = repo.storage.get("confirmation/" + delivery["id"] + ".eml")
        if digest(raw) != delivery["mime_sha256"]:
            raise WorkflowError("captured confirmation integrity failure")
        message = BytesParser(policy=policy.default).parsebytes(raw)
        attachments = list(message.iter_attachments())
        if (
            len(attachments) != 1
            or attachments[0].get_content_type() != "application/pdf"
            or attachments[0].get_payload(decode=True) != contents["pdf"]
            or attachments[0].get_filename() != artifacts["pdf"]["filename"]
        ):
            raise WorkflowError("exact PDF-only attachment required")
        html = message.get_body(preferencelist=("html",)).get_content()
        links = re.findall(r'href="([^"]+)"', html)
        if (
            len(links) != 1
            or not links[0].startswith(PRODUCTION_API + "/approve/")
            or urlsplit(links[0]).netloc != urlsplit(PRODUCTION_API).netloc
            or APPROVAL_COPY not in html
            or BUTTON not in html
        ):
            raise WorkflowError("exact production approval landing required")
        audit = {
            "order_id": snapshot["id"],
            "customer_id": snapshot["customer_id"],
            "revision_id": revision_id,
            "delivery_id": delivery["id"],
            "recipient_sha256": digest(recipient.encode()),
            "pdf_sha256": artifacts["pdf"]["sha256"],
            "spec_sha256": revision["spec_sha256"],
            "mime_sha256": delivery["mime_sha256"],
        }
        accepted = _journal(repo, prefix + "accepted.json")
        if accepted is not None:
            if accepted != audit:
                raise WorkflowError("email acceptance binding differs")
            return {
                "revision_id": revision_id,
                "state": "PROVIDER_ACCEPTED",
                "replayed": True,
            }
        # New sends require a valid current token; accepted replays remain idempotent.
        repo._resolve(db, links[0].split("/approve/", 1)[1], snapshot["customer_id"])
        payload = {
            "personalizations": [{"to": [{"email": recipient}]}],
            "from": {"email": sender, "name": "O-Plates"},
            "subject": str(message["Subject"]),
            "content": [{"type": "text/html", "value": html}],
            "attachments": [
                {
                    "content": base64.b64encode(contents["pdf"]).decode("ascii"),
                    "type": "application/pdf",
                    "filename": artifacts["pdf"]["filename"],
                    "disposition": "attachment",
                }
            ],
            "tracking_settings": {
                "click_tracking": {"enable": False, "enable_text": False}
            },
        }
        encoded = json.dumps(audit, sort_keys=True).encode()
        try:
            repo.storage.put(prefix + "claimed.json", encoded)
        except WorkflowError:
            # Atomic no-upsert claim: a replay or uncertain attempt cannot send twice.
            return {"revision_id": revision_id, "state": "RECONCILIATION_REQUIRED"}
        try:
            response = post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": "Bearer " + key},
                timeout=30,
                allow_redirects=False,
            )
            if response.status_code != 202:
                return {"revision_id": revision_id, "state": "RECONCILIATION_REQUIRED"}
            repo.storage.put(prefix + "accepted.json", encoded)
        except (requests.RequestException, WorkflowError):
            return {"revision_id": revision_id, "state": "RECONCILIATION_REQUIRED"}
        return {
            "revision_id": revision_id,
            "state": "PROVIDER_ACCEPTED",
            "replayed": False,
        }


def deliver_completed_order(repo, snapshot, states):
    if any(item["state"] == "HOLD" for item in states):
        # Do not silently send only the valid lines of a partially held order.
        return [{"state": "HOLD"}]
    return [send_confirmation(repo, snapshot, item["revision_id"]) for item in states]


def delivery_status(repo, revision_id):
    """Internal operational status; no MIME, recipient address or bearer token."""
    with repo.connect() as db:
        revision, artifacts, _ = repo._verified(db, revision_id)
    prefix = "email-delivery/" + revision_id + "/"
    for filename, state in (
        ("accepted.json", "PROVIDER_ACCEPTED"),
        ("claimed.json", "RECONCILIATION_REQUIRED"),
    ):
        audit = _journal(repo, prefix + filename)
        if audit is None:
            continue
        if (
            audit["revision_id"] != revision_id
            or audit["pdf_sha256"] != artifacts["pdf"]["sha256"]
            or audit["spec_sha256"] != revision["spec_sha256"]
        ):
            raise WorkflowError("email audit binding differs")
        return {"revision_id": revision_id, "state": state}
    return {"revision_id": revision_id, "state": "NOT_ATTEMPTED"}
