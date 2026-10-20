"""Shared display names for the configurator's unchanged material codes."""

MATERIAL_COPY = {
    "304": ("304 SS", "General-purpose stainless."),
    "316": ("316 SS", "Added corrosion resistance."),
    "Carbon Steel": ("Carbon Steel", "Cost-effective steel."),
}


def drawing_material_name(value):
    """Expand the card abbreviation for drawings; never change pricing inputs."""
    label = MATERIAL_COPY.get(value, (value, ""))[0]
    return label.removesuffix(" SS").upper() + (
        " STAINLESS STEEL" if label.endswith(" SS") else ""
    )
