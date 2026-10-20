"""Server-to-server selected-part attestation; never a pricing input."""

import hashlib
import hmac
import json

from pricing_engine import QuoteInputs

QUOTE_CLASSES = {
    "single_plate_drawing",
    "multi_plate_drawing",
    "table_driven_plate_schedule",
}


def validate_context(context):
    if not isinstance(context, dict) or set(context) != {
        "document_class",
        "selected_candidate_id",
        "candidate_count",
        "selection_required",
    }:
        raise ValueError("Invalid selected-part context")
    if (
        context["document_class"] not in QUOTE_CLASSES
        or not isinstance(context["selected_candidate_id"], str)
        or not context["selected_candidate_id"]
        or len(context["selected_candidate_id"]) > 256
        or type(context["candidate_count"]) is not int
        or context["candidate_count"] < 1
        or context["selection_required"] is not False
    ):
        raise ValueError("A quote-specific selected part is required")
    return dict(context)


def selected_part_context(session):
    if not session.confirmation_fingerprint:
        raise ValueError("Current purchaser confirmation is required")
    return validate_context(
        {
            "document_class": getattr(
                session.document_class, "value", session.document_class
            ),
            "selected_candidate_id": session.selected_candidate_id,
            "candidate_count": session.candidate_count,
            "selection_required": session.selection_required,
        }
    )


def _signature(context, inputs, customer_id, secret):
    if not secret or not customer_id:
        raise ValueError("Server credential and purchaser identity required")
    payload = {
        "version": "selected-part:v1",
        "customer_id": customer_id,
        "inputs": QuoteInputs(**inputs).model_dump(),
        "context": validate_context(context),
    }
    return hmac.new(
        secret.encode(),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()


def attest_context(context, inputs, customer_id, secret):
    return {
        "context": validate_context(context),
        "signature": _signature(context, inputs, customer_id, secret),
    }


def verify_context(envelope, inputs, customer_id, secret):
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"context", "signature"}
        or not isinstance(envelope["signature"], str)
    ):
        raise ValueError("Invalid selected-part attestation")
    expected = _signature(envelope["context"], inputs, customer_id, secret)
    if not hmac.compare_digest(expected, envelope["signature"]):
        raise ValueError("Selected-part attestation does not match purchaser inputs")
    return validate_context(envelope["context"])
