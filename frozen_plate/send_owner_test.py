"""Explicit one-attempt OP-0012 email test; never invoked by order processing.

Run on the staging API only: python -m frozen_plate.send_owner_test --send
The private immutable claim prevents concurrent sends and ambiguous retries.
Capture-only configuration and existing captured MIME remain unchanged.
"""
import argparse
import base64
import json
import os
from email import policy
from email.parser import BytesParser
from urllib.parse import urlsplit

import requests

from .presentation import APPROVAL_COPY, BUTTON
from .repository import WorkflowError, digest
from .staging import API_ORIGIN, StagingRepository

ORDER_ID = "f5be30bb-8335-4342-893b-27f3344d55be"
REVISION_ID = "de7c31f9-adbc-4364-8c33-40f45720bd15"
DELIVERY_ID = "20646d0e-816c-4930-bc58-04df29f22027"
OWNER_ID = "bc3d20fc-9507-4c7f-bd24-664a8908e3a4"
RECIPIENT = "roguemach@gmail.com"
PDF_SHA256 = "25abad54203ec972279666bbdace01ec35313199cb6994c69280d1cbf79a8a53"
JOURNAL = "owner-test-email/OP-0012/"


def run(*, send=False, environ=None, repository=None, post=requests.post):
    env = os.environ if environ is None else environ
    if (env.get("APP_ENV") != "staging"
        or env.get("RENDER_SERVICE_ID") != "srv-d9ritcijobas73didpbg"
        or env.get("FROZEN_PLATE_EMAIL_MODE") != "capture"):
        raise WorkflowError("isolated staging API in capture mode required")
    key = env.get("SENDGRID_API_KEY")
    if not key:
        raise WorkflowError("staging email-provider credential required")
    sender = env.get("FROM_EMAIL", "orders@o-plates.com")
    if sender not in {"orders@o-plates.com", "no-reply@o-plates.com"}:
        raise WorkflowError("approved O-Plates sender required")
    repo = repository or StagingRepository()
    with repo.connect() as db:
        plate = db.execute("SELECT * FROM frozen_plates WHERE order_id=?", (ORDER_ID,)).fetchone()
        revision, artifacts, contents = repo._verified(db, REVISION_ID)
        delivery = db.execute("SELECT * FROM frozen_plate_deliveries WHERE id=?", (DELIVERY_ID,)).fetchone()
        if (not plate or plate["customer_id"] != OWNER_ID
            or plate["current_revision"] != REVISION_ID
            or revision["plate_id"] != plate["id"] or revision["number"] != 1
            or not delivery or delivery["revision_id"] != REVISION_ID
            or delivery["recipient_id"] != OWNER_ID
            or delivery["pdf_id"] != artifacts["pdf"]["id"]
            or artifacts["pdf"]["sha256"] != PDF_SHA256):
            raise WorkflowError("exact owner/order/revision binding required")
    raw = repo.storage.get("confirmation/" + DELIVERY_ID + ".eml")
    if digest(raw) != delivery["mime_sha256"]:
        raise WorkflowError("captured email integrity failure")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    attachments = list(message.iter_attachments())
    if (len(attachments) != 1 or attachments[0].get_content_type() != "application/pdf"
        or attachments[0].get_payload(decode=True) != contents["pdf"]
        or digest(contents["pdf"]) != PDF_SHA256):
        raise WorkflowError("exact PDF-only attachment required")
    html = message.get_body(preferencelist=("html",)).get_content()
    import re
    links = re.findall(r'href="([^"]+)"', html)
    approval_links = [link for link in links if urlsplit(link).path.startswith("/approve/")]
    if (len(approval_links) != 1 or not approval_links[0].startswith(API_ORIGIN + "/approve/")
        or len(links) != 1 or APPROVAL_COPY not in html or BUTTON not in html):
        raise WorkflowError("locked copy and safe staging landing link required")
    payload = {
        "personalizations": [{"to": [{"email": RECIPIENT}]}],
        "from": {"email": sender, "name": "O-Plates staging test"},
        "subject": "[STAGING TEST OP-0012] " + str(message["Subject"]),
        "content": [{"type": "text/html", "value": html}],
        "attachments": [{"content": base64.b64encode(contents["pdf"]).decode("ascii"),
                         "type": "application/pdf", "filename": artifacts["pdf"]["filename"],
                         "disposition": "attachment"}],
        "tracking_settings": {"click_tracking": {"enable": False, "enable_text": False}},
    }
    result = {"preflight_passed": True, "capture_default_preserved": True,
              "order": "OP-0012", "pdf_sha256": PDF_SHA256, "sent": False}
    if not send:
        return result
    # No upsert: this atomic durable write must succeed before any provider call.
    audit = json.dumps({"order_id": ORDER_ID, "revision_id": REVISION_ID,
                        "delivery_id": DELIVERY_ID, "pdf_sha256": PDF_SHA256}).encode()
    repo.storage.put(JOURNAL + "claimed.json", audit)
    try:
        response = post("https://api.sendgrid.com/v3/mail/send", json=payload,
                        headers={"Authorization": "Bearer " + key}, timeout=30,
                        allow_redirects=False)
    except requests.RequestException:
        raise WorkflowError("email outcome unknown; claim retained; do not retry") from None
    if response.status_code != 202:
        raise WorkflowError("provider did not accept; claim retained; do not retry")
    repo.storage.put(JOURNAL + "accepted.json", audit)
    result.update(sent=True, provider_accepted=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(send=args.send), sort_keys=True))
    except Exception:
        # Never print provider exceptions, request bodies, headers or bearer links.
        print(json.dumps({"completed": False, "send_not_confirmed": True,
                          "retry_requires_review": args.send}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
