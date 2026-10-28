"""Customer-safe service messages; never render provider response bodies."""


def service_message(status_code: int, *, pricing: bool = False) -> str:
    if status_code in (401, 403):
        return (
            "Please sign in again to continue, or contact sales@o-plates.com for help."
        )
    if status_code == 409:
        return "Your quote needs to be refreshed. Review the current price before continuing."
    if status_code in (400, 422) and pricing:
        return "This configuration could not be priced. Review the dimensions and selected options."
    return (
        "Pricing is temporarily unavailable. Your entries are preserved; please try again."
        if pricing
        else "We couldn’t complete that request. Please try again or contact sales@o-plates.com."
    )


# Only product specifications belong in customer order details. Operational
# metadata and artifact hashes stay in the authenticated manufacturing tools.
PRODUCT_FIELDS = {
    "material": "Material",
    "thickness": "Thickness (in.)",
    "quantity": "Quantity",
    "paddle_dia": "Plate outside diameter (in.)",
    "bore_dia": "Bore diameter (in.)",
    "bore_tolerance": "Bore tolerance (± in.)",
    "handle_width": "Handle width (in.)",
    "handle_length_from_bore": "Handle length from bore center (in.)",
    "handle_label": "Handle marking",
    "handle_hole_enabled": "Handle hole",
    "handle_hole_diameter": "Handle hole diameter (in.)",
    "handle_hole_center_from_handle_end": "Handle hole center from end (in.)",
    "chamfer": "Chamfer",
    "chamfer_width": "Chamfer size (in.)",
    "ships_in_days": "Selected lead time (calendar days)",
}


def customer_product_details(payload: dict) -> dict:
    return {
        label: payload[key] for key, label in PRODUCT_FIELDS.items() if key in payload
    }
