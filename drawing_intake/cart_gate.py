"""Verify the confirmed drawing quote before creating a normal cart snapshot."""

from collections.abc import Mapping
from typing import Any

from pricing_engine import QuoteInputs

from .assisted_quote import AssistedQuoteSession, CanonicalFormAvailability
from .pricing_gate import confirmed_drawing_quote_inputs


def verified_assisted_cart_inputs(
    session: AssistedQuoteSession,
    form_payload: Mapping[str, Any],
    quote_result: Mapping[str, Any],
    *,
    availability: CanonicalFormAvailability,
) -> dict[str, Any]:
    """Keep recognition evidence out of the existing cart and checkout payloads.

    The checkout API independently validates and reprices this canonical snapshot.
    The quote reference is a UI audit identity, not a price authorization token.
    """

    confirmed = confirmed_drawing_quote_inputs(
        session, form_payload, availability=availability
    )
    try:
        normalized = QuoteInputs(
            **quote_result["normalized_configuration"]
        ).model_dump()
    except (KeyError, TypeError) as exc:
        raise ValueError("the authoritative quote has no canonical inputs") from exc
    if normalized != confirmed:
        raise ValueError("the verified price belongs to a different configuration")
    validation = quote_result.get("validation")
    if not isinstance(validation, Mapping) or validation.get("valid") is not True:
        raise ValueError("the authoritative quote has not passed validation")
    if (
        quote_result.get("currency") != "USD"
        or not quote_result.get("configuration_id")
        or not quote_result.get("pricing_config_version")
        or quote_result.get("unit_price") is None
        or quote_result.get("total_price") is None
    ):
        raise ValueError("the authoritative quote is incomplete")
    return confirmed
