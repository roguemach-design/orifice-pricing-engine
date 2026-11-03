"""Private My Orders UI state, scoped to the active authenticated subject.

This hint is only a cleanup boundary. API ownership checks authorize every read.
"""


def clear_orders_state(state):
    for key in list(state):
        if key.startswith("orders_") or key.startswith("archive-"):
            state.pop(key, None)


def bind_orders_owner(state, subject):
    if state.get("orders_owner") != subject or not subject:
        clear_orders_state(state)
    if subject:
        state["orders_owner"] = subject
