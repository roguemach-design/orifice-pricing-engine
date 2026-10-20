"""Drawing-only policy. These values do not change specs or manufacturing geometry."""

PROPOSED_PENDING_OWNER = True
UOS_XX = ".01"
UOS_XXX = ".005"
UOS_ANGLES = "1°"
BORE_POSITION_DIAMETER = ".010"  # RFS, primary face A, secondary OD B
DISPLAY_PRECISION = {
    "od": 3,
    "bore": 3,
    "width": 2,
    "length": 2,
    "hole_location": 2,
    "hole_diameter": 3,
    "radius": 2,
}
HANDLE_HOLE_TOLERANCE = "block tolerance; no feature control frame"
EDGE_BREAK = ".005-.015"
FACE_FINISH = "MILL FINISH"
# Owner approved the two additional fallbacks on 2026-10-20.
SCALE_DENOMINATORS = (1, 2, 4, 8, 16)


def inch(value, places=3):
    """Inch decimal convention; preserve significant trailing decimal places."""
    result = f"{value:.{places}f}"
    if result.startswith("0."):
        return result[1:]
    if result.startswith("-0."):
        return "-" + result[2:]
    return result


def dimension(value, feature):
    return inch(value, DISPLAY_PRECISION[feature])
