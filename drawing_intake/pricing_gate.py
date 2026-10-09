"""Owner-test handoff from a confirmed drawing into the ordinary quote request."""

from typing import Any, Mapping

from pricing_engine import QuoteInputs

from .assisted_quote import (
    AssistedQuoteSession,
    CanonicalFormAvailability,
    build_pricing_handoff_preview,
)
from .classification import DrawingDocumentClass

_QUOTE_SPECIFIC_CLASSES = {
    DrawingDocumentClass.SINGLE_PLATE_DRAWING,
    DrawingDocumentClass.MULTI_PLATE_DRAWING,
    DrawingDocumentClass.TABLE_DRIVEN_PLATE_SCHEDULE,
}


def confirmed_drawing_quote_inputs(
    session: AssistedQuoteSession,
    form_payload: Mapping[str, Any],
    *,
    availability: CanonicalFormAvailability,
) -> dict[str, Any]:
    """Return the existing QuoteInputs payload only for a selected, current review.

    Recognition evidence stays in the session; it is never sent to pricing.
    The form and the confirmed snapshot must agree, including customer edits.
    """

    if (
        session.document_class not in _QUOTE_SPECIFIC_CLASSES
        or not session.selected_candidate_id
        or not session.candidate_count
        or session.selection_required
    ):
        raise ValueError("a quote-specific plate must be selected")
    confirmed = build_pricing_handoff_preview(
        session, availability=availability
    ).quote_request
    current = QuoteInputs(**dict(form_payload)).model_dump()
    if current != confirmed:
        raise ValueError("the confirmed configuration differs from the current form")
    return current
