import copy
import itertools
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_app as api
from pricing_configuration import project, validate
from pricing_engine import QuoteInputs, calculate_quote
from test_checkout_workflow import quote_inputs


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    api.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(api, "SessionLocal", factory)
    monkeypatch.setattr(api, "ADMIN_API_KEY", "synthetic-owner")
    monkeypatch.setattr(api, "API_KEY", "synthetic-quote")
    api._RATE_LIMITER.clear()
    with factory() as db:
        db.add(api.AppConfig(id="active", config_json=api._default_knobs_config()))
        db.commit()
    yield TestClient(api.app), factory
    engine.dispose()


OWNER = {"x-api-key": "synthetic-owner"}


def snapshot(c):
    r = c.get("/admin/config/editor", headers=OWNER)
    assert r.status_code == 200, r.text
    return r.json()


def save(c, state, **updates):
    return c.put(
        "/admin/config",
        headers=OWNER,
        json={
            **state["config"],
            **updates,
            "_version": state["version"],
            "_confirmation": "SAVE CHANGES",
        },
    )


def test_read_projection_does_not_write_active_settings(client):
    c, factory = client
    with factory() as db:
        row = db.get(api.AppConfig, "active")
        before = (copy.deepcopy(row.config_json), row.updated_at)
    state = snapshot(c)
    assert state["config"]["mill_labor_per_hr"] == 150
    with factory() as db:
        row = db.get(api.AppConfig, "active")
        assert (row.config_json, row.updated_at) == before
        assert db.query(api.AppConfig).count() == 1


def test_save_conflict_restore_and_reset_are_versioned_and_recoverable(client):
    c, factory = client
    initial = snapshot(c)
    assert save(c, initial, mill_labor_per_hr=175).status_code == 200
    assert save(c, initial, mill_labor_per_hr=200).status_code == 409
    current = snapshot(c)
    assert current["config"]["mill_labor_per_hr"] == 175
    assert len(current["history"]) == 1
    assert (
        c.post(
            "/admin/config/restore",
            headers=OWNER,
            json={
                "_version": current["version"],
                "_confirmation": "RESTORE CONFIGURATION",
                "history_id": current["history"][0]["id"],
            },
        ).status_code
        == 200
    )
    restored = snapshot(c)
    assert restored["config"]["mill_labor_per_hr"] == 150
    assert len(restored["history"]) == 2
    assert (
        c.post(
            "/admin/config/reset",
            headers=OWNER,
            json={"_version": restored["version"], "_confirmation": "RESET DEFAULTS"},
        ).status_code
        == 200
    )
    assert len(snapshot(c)["history"]) == 3


@pytest.mark.parametrize(
    "path,method",
    [
        ("/admin/config", "get"),
        ("/admin/config/editor", "get"),
        ("/admin/config", "put"),
        ("/admin/config/reset", "post"),
        ("/admin/config/restore", "post"),
    ],
)
def test_all_configuration_endpoints_require_owner(client, path, method):
    c, _ = client
    assert (
        getattr(c, method)(path, headers={"x-api-key": "synthetic-quote"}).status_code
        == 401
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("mill_labor_per_hr", -1),
        ("mill_labor_per_hr", "150"),
        ("mill_speed_ipm", 0),
        ("max_handle_label_chars", 1.5),
        ("default_lead_time_days", 7),
        ("material_enabled", {"304": "false"}),
        ("price_per_sq_in", {}),
        ("inspection_mins_by_tol", {"0.005": 6}),
        ("qty_discount_tiers", [{"min_qty": 5, "multiplier": 1}]),
        (
            "qty_discount_tiers",
            [{"min_qty": 1, "multiplier": 1}, {"min_qty": 5, "multiplier": 1.1}],
        ),
        ("max_bore_dia_in", 50),
        ("density_lb_per_in3", {"304": -0.2}),
    ],
)
def test_rejected_configuration_never_writes(client, field, value):
    c, factory = client
    state = snapshot(c)
    assert save(c, state, **{field: value}).status_code == 422
    assert snapshot(c)["version"] == state["version"]
    with factory() as db:
        assert db.query(api.AppConfig).count() == 1


@pytest.mark.parametrize("n", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_rejected(n):
    state = project(api._default_knobs_config(), api._CFG_BASELINE)
    state["price_per_sq_in"]["304"]["0.125"] = n
    with pytest.raises(ValueError):
        validate(state, project(api._default_knobs_config(), api._CFG_BASELINE))


def test_confirmation_and_version_required(client):
    c, _ = client
    state = snapshot(c)
    assert (
        c.put("/admin/config", headers=OWNER, json=state["config"]).status_code == 428
    )
    assert (
        c.put(
            "/admin/config",
            headers=OWNER,
            json={**state["config"], "_version": state["version"]},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/admin/config/reset", headers=OWNER, json={"_version": state["version"]}
        ).status_code
        == 422
    )
    assert c.put("/admin/config", headers=OWNER, content="{bad").status_code == 422


def test_disabled_availability_and_new_rates_use_same_authority(client):
    c, _ = client
    state = snapshot(c)
    baseline = api._calculate_quote_with_db_knobs(QuoteInputs(**quote_inputs()))
    assert save(c, state, mill_labor_per_hr=175).status_code == 200
    result = api._calculate_quote_with_db_knobs(QuoteInputs(**quote_inputs()))
    assert result["unit_price"] > baseline["unit_price"]
    assert api.cfg.MILL_LABOR_PER_HR == 150
    state = snapshot(c)
    material = {**state["config"]["material_enabled"], "304": False}
    assert save(c, state, material_enabled=material).status_code == 200
    with pytest.raises(ValueError, match="unknown material"):
        api._calculate_quote_with_db_knobs(QuoteInputs(**quote_inputs()))
    assert "304" not in c.get("/config/active").json()["materials"]
    state = snapshot(c)
    leads = {"7": False, "14": False, "21": True}
    assert (
        save(c, state, lead_time_enabled=leads, default_lead_time_days=21).status_code
        == 200
    )
    with pytest.raises(ValueError, match="unsupported ships_in_days"):
        api._calculate_quote_with_db_knobs(QuoteInputs(**quote_inputs(material="316")))


def test_noop_projection_exact_price_parity_matrix():
    old = api._default_knobs_config()
    new = project(old, api._CFG_BASELINE)
    count = 0
    with api._CFG_LOCK:
        try:
            for material, thickness, qty, days, chamfer, tol in itertools.product(
                ("304", "316", "Carbon Steel"),
                (0.125, 0.25, 0.375, 0.5),
                (1, 5, 10, 25, 50),
                (14, 21),
                (False, True),
                (0.005, 0.002, 0.001),
            ):
                inp = QuoteInputs(
                    **quote_inputs(
                        material=material,
                        thickness=thickness,
                        quantity=qty,
                        ships_in_days=days,
                        chamfer=chamfer,
                        bore_tolerance=tol,
                    )
                )
                api._restore_cfg_baseline()
                api._apply_cfg_from_db_config(old)
                before = calculate_quote(inp)
                api._restore_cfg_baseline()
                api._apply_cfg_from_db_config(new)
                assert calculate_quote(inp) == before
                count += 1
        finally:
            api._restore_cfg_baseline()
    assert count == 720


@pytest.mark.parametrize("cart", [False, True])
def test_actual_db_quote_and_checkout_parity_without_payments(
    client, monkeypatch, cart
):
    from test_checkout_workflow import install_idempotent_stripe

    c, factory = client
    monkeypatch.setattr(api, "APP_ENV", "test")
    monkeypatch.setattr(api, "APP_BASE_URL", "https://synthetic.example.test")
    monkeypatch.setattr(api.stripe, "api_key", "sk_test_synthetic")
    monkeypatch.setattr(
        api, "_decode_supabase_user_id_from_bearer", lambda _: "synthetic-owner"
    )
    calls = install_idempotent_stripe(monkeypatch)
    values = quote_inputs(quantity=5)
    result = c.post(
        "/quote", headers={"x-api-key": "synthetic-quote"}, json=values
    ).json()
    body = {"items": [values]} if cart else {"inputs": values}
    body["pricing_config_version"] = result["pricing_config_version"]
    path = "/checkout/cart/create" if cart else "/checkout/create"
    response = c.post(path, headers={"authorization": "Bearer synthetic"}, json=body)
    assert response.status_code == 200, response.text
    assert calls[0]["line_items"][0]["price_data"]["unit_amount"] == round(
        result["total_price"] * 100
    )
    with factory() as db:
        frozen_order = db.query(api.Order).first()
        prior = copy.deepcopy(frozen_order.quote_payload)
    state = snapshot(c)
    assert save(c, state, mill_labor_per_hr=160).status_code == 200
    assert (
        c.post(
            path, headers={"authorization": "Bearer synthetic"}, json=body
        ).status_code
        == 409
    )
    assert len(calls) == 1
    with factory() as db:
        assert db.query(api.Order).first().quote_payload == prior
    state = snapshot(c)
    state["config"]["material_enabled"]["304"] = False
    assert save(c, state).status_code == 200
    assert (
        c.post(
            path, headers={"authorization": "Bearer synthetic"}, json=body
        ).status_code
        == 422
    )
    assert len(calls) == 1


def test_owner_editor_unsaved_state_and_navigation(monkeypatch):
    from test_manufacturing_control import configure_ui
    from manufacturing_control.client import OwnerClient

    app, _, _ = configure_ui(monkeypatch)
    original = project(api._default_knobs_config(), api._CFG_BASELINE)
    original_json = OwnerClient.json

    def read(self, path, **kwargs):
        if path == "/admin/config/editor":
            return {
                "config": copy.deepcopy(original),
                "defaults": copy.deepcopy(original),
                "version": "synthetic-v1",
                "history": [],
            }
        return original_json(self, path, **kwargs)

    monkeypatch.setattr(OwnerClient, "json", read)
    writes = []
    monkeypatch.setattr(
        OwnerClient,
        "config_write",
        lambda self, action, body: writes.append((action, body)) or {"ok": True},
    )
    app.text_input[0].set_value("fixture-owner")
    next(b for b in app.button if b.label == "Unlock").click().run()
    next(r for r in app.radio if r.label == "Workspace").set_value(
        "Pricing & Availability"
    ).run()
    assert not app.exception
    assert next(b for b in app.button if b.label == "Save Changes").disabled
    next(n for n in app.number_input if n.label == "Shop rate · $ / hour").set_value(
        175
    ).run()
    assert app.session_state["mc_price_dirty"]
    assert not writes
    next(r for r in app.radio if r.label == "Workspace").set_value("Overview").run()
    assert any("Unsaved Pricing" in w.value for w in app.warning)
    next(r for r in app.radio if r.label == "Workspace").set_value(
        "Pricing & Availability"
    ).run()
    assert (
        next(n for n in app.number_input if n.label == "Shop rate · $ / hour").value
        == 175
    )
    next(c for c in app.checkbox if c.label.startswith("I reviewed")).check().run()
    next(b for b in app.button if b.label == "Save Changes").click().run()
    assert not app.exception
    assert writes[0][1]["mill_labor_per_hr"] == 175
    assert writes[0][1]["_version"] == "synthetic-v1"
