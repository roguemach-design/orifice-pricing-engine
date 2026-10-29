"""Ambiguous/infeasible parts must never reach Stripe; existing quotes remain usable."""
import copy
import pytest
import api_app
from checkout_geometry import STANDARD_CHAMFER, checkout_geometry_error
from test_checkout_workflow import database, checkout_client, checkout_body, quote_inputs
from test_quote_field_validation import quote_page
from test_landing_convergence import select


@pytest.mark.parametrize("missing", list(STANDARD_CHAMFER) + ["chamfer_width"])
@pytest.mark.parametrize("cart", [False, True])
def test_every_required_chamfer_field_blocks_before_stripe(monkeypatch, checkout_client, database, missing, cart):
    monkeypatch.setattr(api_app, "_decode_supabase_user_id_from_bearer", lambda _: "owner-test")
    calls = []
    monkeypatch.setattr(api_app.stripe.checkout.Session, "create", lambda **kw: calls.append(kw))
    invalid = quote_inputs()
    invalid.pop(missing)
    body = {"items": [quote_inputs(), invalid]} if cart else checkout_body(inputs=invalid)
    retained = copy.deepcopy(body)
    response = checkout_client.post("/checkout/cart/create" if cart else "/checkout/create", json=body,
                                    headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == 422 and not calls
    assert body == retained
    if cart:
        assert response.json()["detail"]["line"] == 2
    with database() as db:
        assert db.query(api_app.Order).count() == 0


@pytest.mark.parametrize("change", [{"chamfer_width": .125}, {"chamfer_width": 2}, {"chamfer_angle_degrees": 89.9}])
def test_existing_positive_land_and_wall_constraints_are_not_bypassed(change):
    assert checkout_geometry_error(quote_inputs(**change))


def test_only_bore_edge_choice_sets_standard_geometry_and_clears_inactive_fields(quote_page):
    app, calls = quote_page
    select(app, "quote_field_chamfer", True)
    app.run()
    assert not app.exception
    assert not any(r.label == "Chamfer specification" for r in app.radio)
    assert all(calls[-1][key] == value for key, value in STANDARD_CHAMFER.items())
    assert checkout_geometry_error(calls[-1]) is None
    app.number_input(key="quote_field_chamfer_width").set_value(0.04).run()
    assert calls[-1]["chamfer_width"] == 0.04
    select(app, "quote_field_chamfer", False)
    app.run()
    assert calls[-1]["chamfer"] is False
    assert calls[-1]["chamfer_width"] is None
    assert all(key not in calls[-1] for key in STANDARD_CHAMFER)
    assert all(app.session_state["quote_field_" + key] is None for key in STANDARD_CHAMFER)
    select(app, "quote_field_chamfer", True)
    app.run()
    assert not app.exception
    assert calls[-1]["chamfer_width"] == 0.04
    assert all(calls[-1][key] == value for key, value in STANDARD_CHAMFER.items())
    assert checkout_geometry_error(calls[-1]) is None


@pytest.mark.parametrize("cart", [False, True])
def test_automatic_customer_specification_survives_single_and_cart_checkout(
    monkeypatch, quote_page, checkout_client, database, cart
):
    from test_checkout_workflow import install_idempotent_stripe
    from frozen_plate.order_adapter import specification_from_order
    from plate_geometry import canonical_specification

    app, calls = quote_page
    select(app, "quote_field_chamfer", True)
    app.run()
    app.number_input(key="quote_field_chamfer_width").set_value(0.04).run()
    values = copy.deepcopy(calls[-1])
    assert all(values[key] == value for key, value in STANDARD_CHAMFER.items())
    monkeypatch.setattr(api_app, "_decode_supabase_user_id_from_bearer", lambda _: "owner-test")
    stripe_calls = install_idempotent_stripe(monkeypatch)
    response = checkout_client.post(
        "/checkout/cart/create" if cart else "/checkout/create",
        json={"items": [values]} if cart else {"inputs": values},
        headers={"Authorization": "Bearer synthetic"},
    )
    assert response.status_code == 200 and len(stripe_calls) == 1
    with database() as db:
        order = db.query(api_app.Order).one()
        snapshot = {"id": order.id, "customer_id": order.customer_id, "quote_payload": order.quote_payload}
        spec, _ = specification_from_order(snapshot, line_index=0, part_identifier="TEST")
    canonical = canonical_specification(spec)
    assert canonical["chamfer_width"] == 0.04
    assert all(canonical[key] == value for key, value in STANDARD_CHAMFER.items())


def test_non_chamfer_payload_and_geometry_are_unchanged():
    values = quote_inputs(chamfer=False, chamfer_width=None)
    assert checkout_geometry_error(values) is None
    from pricing_engine import QuoteInputs
    assert all(key not in QuoteInputs(**values).model_dump() for key in STANDARD_CHAMFER)


def test_geometry_survives_confirmed_handoff_and_is_bound_to_recovery_signature():
    from test_drawing_phase1k import complete_session, available
    from drawing_intake.pricing_gate import confirmed_drawing_quote_inputs
    from drawing_intake.checkout_context import selected_part_context, attest_context, verify_context
    values = quote_inputs()
    session = complete_session(values)
    handoff = confirmed_drawing_quote_inputs(session, values, availability=available())
    assert all(handoff[key] == value for key, value in STANDARD_CHAMFER.items())
    context = selected_part_context(session)
    envelope = attest_context(context, handoff, "synthetic-customer", "synthetic-key")
    assert verify_context(envelope, handoff, "synthetic-customer", "synthetic-key") == context
    for key, value in dict(chamfer_angle_degrees=30, chamfer_side="upstream",
                          flow_orientation="right-to-left", chamfer_width_definition="axial-depth-angle-from-face").items():
        with pytest.raises(ValueError):
            verify_context(envelope, {**handoff, key:value}, "synthetic-customer", "synthetic-key")
