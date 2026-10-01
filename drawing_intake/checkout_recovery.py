"""Authenticated cancellation recovery, without browser-persistent drawing data."""

from __future__ import annotations

import re
from typing import Mapping

import requests

from .assisted_quote import (
    AssistedQuoteSession,
    CanonicalFieldValue,
    ConfigurationValueOrigin,
)


def fetch_checkout_recovery(api_base: str, reference: str, headers: Mapping[str, str]):
    if not re.fullmatch(r"[0-9a-f]{64}", reference) or not headers.get(
        "Authorization", headers.get("authorization")
    ):
        raise ValueError("Sign in to recover your configuration.")
    try:
        response = requests.get(
            f"{api_base.rstrip('/')}/checkout/recovery/{reference}",
            headers=dict(headers),
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        if (
            result.get("kind") not in {"direct", "cart"}
            or not isinstance(result.get("items"), list)
            or not result["items"]
        ):
            raise ValueError("Invalid recovery response")
        return result
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise ValueError(
            "Recovery is unavailable or expired. Your current entries have not been changed."
        ) from exc


def recovered_quote_session(values):
    # Saved inputs are purchaser values; never re-run OCR or restore old confirmation.
    return AssistedQuoteSession(
        configuration={
            field: CanonicalFieldValue(
                value=value, origin=ConfigurationValueOrigin.CUSTOMER
            )
            for field, value in values.items()
            if value is not None
        },
    )


def restore_quote_editor(state, values):
    """Install a purchaser snapshot before widgets render, without cached price/evidence."""
    for field, value in values.items():
        state[f"quote_field_{field}"] = value
    state["phase1g_form_origins"] = {field: "customer" for field in values}
    state["phase1g_form_snapshot"] = dict(values)
    state["phase1g_assisted_session"] = recovered_quote_session(values)
    state["phase1g_customer_confirmation"] = False
    state["phase1g_merge_conflicts"] = []
