"""Drawing-only proposals; never feed these defaults into a stored specification."""

PROPOSED_PENDING_OWNER = True
UOS_XX = ".01"  # PROPOSED_PENDING_OWNER
UOS_XXX = ".005"  # PROPOSED_PENDING_OWNER
UOS_ANGLES = "1°"  # PROPOSED_PENDING_OWNER
DISPLAY_PRECISION = {  # PROPOSED_PENDING_OWNER
    "od": 3,
    "bore": 3,
    "thickness": 3,
    "chamfer": 3,
    "hole_diameter": 3,
    "width": 2,
    "length": 2,
    "hole_location": 2,
    "radius": 2,
}
EDGE_BREAK = ".005-.015"  # PROPOSED_PENDING_OWNER
FACE_FINISH = "MILL FINISH"  # PROPOSED_PENDING_OWNER
MARK_HEIGHT = ".12"  # PROPOSED_PENDING_OWNER
BREAK_FROM_JUNCTION = 0.45  # PROPOSED_PENDING_OWNER
MINIMUM_KEPT_TIP = 1.75  # PROPOSED_PENDING_OWNER
HOLE_TIP_CLEARANCE = 0.90  # PROPOSED_PENDING_OWNER
BREAK_GAP_POINTS = 0.30 * 72  # PROPOSED_PENDING_OWNER; paper distance
# Additional fallbacks explicitly approved by owner on 2026-10-20.
SCALE_DENOMINATORS = (1, 2, 4, 8, 16)
WEB_TEXT_SCALE = 2.15  # PROPOSED_PENDING_OWNER
PRINT_TEXT_SCALE = 1.15  # PROPOSED_PENDING_OWNER
WEB_ARROW_SCALE = 1.7  # PROPOSED_PENDING_OWNER
PRINT_ARROW_SCALE = 1.1  # PROPOSED_PENDING_OWNER
WEB_LINE_SCALE = 1.9  # PROPOSED_PENDING_OWNER
PRINT_LINE_SCALE = 1.0  # PROPOSED_PENDING_OWNER


def inch(value, places=3):
    result = f"{value:.{places}f}"
    if result.startswith("0."):
        return result[1:]
    if result.startswith("-0."):
        return "-" + result[2:]
    return result


def dimension(value, feature):
    return inch(value, DISPLAY_PRECISION[feature])
