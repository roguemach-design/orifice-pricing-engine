from customer_orders_state import bind_orders_owner, clear_orders_state


def test_owner_change_logout_and_anonymous_clear_only_orders_state():
    state = {
        "orders_owner": "a",
        "orders_selected": "private",
        "orders_confirmation_r1": {"token": "private"},
        "orders_pdf_selection": ("private", "r1"),
        "archive-x": "private",
        "quote_form_snapshot": {"chamfer": False},
        "auth": {"user": "b"},
    }
    bind_orders_owner(state, "a")
    assert state["orders_selected"] == "private"
    bind_orders_owner(state, "b")
    assert state == {
        "orders_owner": "b",
        "quote_form_snapshot": {"chamfer": False},
        "auth": {"user": "b"},
    }
    state["orders_pdf_bytes"] = b"private"
    bind_orders_owner(state, None)
    assert not any(k.startswith("orders_") for k in state)
    assert state["quote_form_snapshot"]["chamfer"] is False
    clear_orders_state(state)
