"""Pure adapter for explicitly supplied application order snapshots; no DB calls."""

from copy import deepcopy
from plate_geometry import PlateSpec
from .repository import WorkflowError


def specification_from_order(order_snapshot, *, line_index, part_identifier):
    if not order_snapshot.get("id") or not order_snapshot.get("customer_id"):
        raise WorkflowError("order and verified customer identity required")
    payload = deepcopy(order_snapshot["quote_payload"])
    items = payload.get("cart_items")
    if type(line_index) is not int or line_index < 0:
        raise WorkflowError("explicit nonnegative order line index required")
    if items is None:
        if line_index != 0:
            raise WorkflowError("single-line order has no such line")
        config = payload
    else:
        if line_index >= len(items):
            raise WorkflowError("order line is missing")
        config = items[line_index]
    spec = PlateSpec.from_configuration(config, part_identifier=part_identifier)
    # No guessed geometry, tolerance or material defaults. Full input snapshot is
    # retained for provenance; line index is bound to this immutable source snapshot.
    return spec, {
        "order_id": order_snapshot["id"],
        "customer_id": order_snapshot["customer_id"],
        "line_index": line_index,
        "configuration": config,
    }
