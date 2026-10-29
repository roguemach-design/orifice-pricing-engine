"""Finished geometry mass, unchanged commercial costs, and authoritative checkout rates."""
import hashlib
import itertools
import json
from dataclasses import replace
from math import cos, pi, radians, sin
from pathlib import Path

import pytest

import tuning_knobs as cfg
from plate_geometry import PlateSpec, build_plate_geometry
from pricing_engine import QuoteInputs, calculate_quote, _ups_rule_shipping_cents
from shipping_mass import finished_part_volume_in3, shipping_mass, MODEL_VERSION
from test_pricing_configuration import client
from test_checkout_workflow import install_idempotent_stripe, quote_inputs

OP19 = dict(quantity=1, material="304", thickness=.25, handle_width=1,
            handle_length_from_bore=13.125, paddle_dia=14.25, bore_dia=8.5,
            bore_tolerance=.005, chamfer=False, chamfer_width=None, ships_in_days=14,
            handle_hole_enabled=True, handle_hole_diameter=.375,
            handle_hole_center_from_handle_end=.625)
SHIPPING_KEYS = {"estimated_unit_weight_lb", "estimated_total_weight_lb", "shipping"}


def representative_inputs():
    for material, thickness, shape, qty, chamfer in itertools.product(
        ("304", "316", "Carbon Steel"), (.125, .25, .375, .5),
        ((3, 1, 1, 9), (14.25, 8.5, 1, 13.125), (24, 19, 1.5, 25)),
        (1, 5, 10, 25), (False, True),
    ):
        od, bore, width, length = shape
        yield quote_inputs(material=material, thickness=thickness, paddle_dia=od,
                           bore_dia=bore, handle_width=width, handle_length_from_bore=length,
                           quantity=qty, chamfer=chamfer, chamfer_width=.03125 if chamfer else None)


def commercial_digest(calculate=calculate_quote):
    results = [{k: v for k, v in calculate(QuoteInputs(**x)).items() if k not in SHIPPING_KEYS}
               for x in representative_inputs()]
    return hashlib.sha256(json.dumps(results, sort_keys=True, allow_nan=False).encode()).hexdigest()


def test_op19_reproduces_old_weight_and_compares_measured_packed_weight():
    old_weight = 14.25 * (13.125 + 14.25 / 2) * .25 * .289
    assert old_weight == pytest.approx(20.848640625)
    q = calculate_quote(QuoteInputs(**OP19))
    assert q["estimated_unit_weight_lb"] == 7.85
    assert q["estimated_total_weight_lb"] == 8.85
    assert q["estimated_total_weight_lb"] - 8.6 == pytest.approx(.25)
    assert q["estimated_package_in"] == dict(length=24.25, width=18.25, height=1.0)
    assert _ups_rule_shipping_cents(old_weight, 24.25, 18.25, 1) == dict(
        ups_ground_cents=3195, ups_2day_cents=5911, ups_nextday_cents=9106)
    assert q["shipping"] == dict(ups_ground_cents=2055, ups_2day_cents=3802, ups_nextday_cents=5857)
    assert q["area_sq_in"] == 288.5625  # rectangular material purchasing envelope
    assert q["unit_price"] == 685.35


def test_contour_integral_matches_independent_dense_tessellation():
    spec = PlateSpec.from_configuration(OP19)
    vertices = []
    for segment in build_plate_geometry(spec).segments:
        if segment.kind == "line":
            vertices.append(segment.start)
        else:
            for i in range(20000):
                angle = radians(segment.start_degrees + segment.sweep_degrees * i / 20000)
                vertices.append((segment.center[0] + segment.radius * cos(angle),
                                 segment.center[1] + segment.radius * sin(angle)))
    area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(vertices, vertices[1:]+vertices[:1]))) / 2
    area -= pi * (8.5/2)**2 + pi * (.375/2)**2
    assert finished_part_volume_in3(spec) == pytest.approx(area*.25, abs=1e-6)


def test_hole_and_bore_remove_only_their_finished_material():
    spec = PlateSpec.from_configuration(OP19)
    no_hole = replace(spec, handle_hole_enabled=False, handle_hole_diameter=None,
                      handle_hole_center_from_handle_end=None)
    assert finished_part_volume_in3(no_hole)-finished_part_volume_in3(spec) == pytest.approx(pi*(.375/2)**2*.25)
    larger = replace(spec, finished_bore_diameter=9.5)
    assert finished_part_volume_in3(spec)-finished_part_volume_in3(larger) == pytest.approx(pi*(9.5**2-8.5**2)/4*.25)


def test_complete_chamfer_removal_uses_existing_section_and_never_invents_missing_geometry():
    plain = PlateSpec.from_configuration(OP19)
    complete = replace(plain, chamfer=True, chamfer_width=.0625,
                       chamfer_angle_degrees=45, chamfer_side="downstream",
                       flow_orientation="left-to-right", chamfer_width_definition="radial-angle-from-face")
    expected = pi*.0625*((8.5/2)*.0625+.0625**2/3)
    assert finished_part_volume_in3(plain)-finished_part_volume_in3(complete) == pytest.approx(expected)
    axial = replace(complete, chamfer_width_definition="axial-depth-angle-from-face")
    assert finished_part_volume_in3(axial) == pytest.approx(finished_part_volume_in3(complete))
    incomplete = replace(plain, chamfer=True, chamfer_width=.0625)
    assert finished_part_volume_in3(incomplete) == finished_part_volume_in3(plain)
    with pytest.raises(ValueError, match="positive land and wall"):
        finished_part_volume_in3(replace(complete, chamfer_width=.25))


@pytest.mark.parametrize("density", [0, -1, float("nan"), float("inf")])
def test_invalid_density_never_returns_a_shipping_price(density):
    with pytest.raises(ValueError, match="density"):
        shipping_mass(OP19, density)


def test_representative_matrix_preserves_all_non_shipping_results_and_quantity_mass():
    expected = json.loads((Path(__file__).parent/"fixtures/shipping-mass-baseline.json").read_text())
    assert commercial_digest() == expected["commercial_sha256"]
    for values in representative_inputs():
        x = QuoteInputs(**values)
        part, packed = shipping_mass(x.model_dump(), cfg.DENSITY_LB_PER_IN3[x.material])
        assert packed == x.quantity*(part+1)
        assert part > 0
        q = calculate_quote(x)
        assert q["estimated_total_weight_lb"] == round(packed, 2)
        package = q["estimated_package_in"]
        assert q["shipping"] == _ups_rule_shipping_cents(packed, **{
            "length_in":package["length"], "width_in":package["width"], "height_in":package["height"]})


@pytest.mark.parametrize("cart", [False, True])
def test_quote_and_checkout_use_same_authoritative_shipping_and_reject_pre_correction_version(client, monkeypatch, cart):
    import api_app as api
    c, factory = client
    monkeypatch.setattr(api, "APP_ENV", "test")
    monkeypatch.setattr(api, "APP_BASE_URL", "https://synthetic.example.test")
    monkeypatch.setattr(api.stripe, "api_key", "sk_test_synthetic")
    monkeypatch.setattr(api, "_decode_supabase_user_id_from_bearer", lambda _: "synthetic-owner")
    calls = install_idempotent_stripe(monkeypatch)
    items = [OP19, {**OP19, "material":"316", "quantity":5}] if cart else [OP19]
    quotes = [c.post("/quote", headers={"x-api-key":"synthetic-quote"}, json=x).json() for x in items]
    version = quotes[0]["pricing_config_version"]
    body = {"items":items} if cart else {"inputs":items[0]}
    body["pricing_config_version"] = version.replace(":"+MODEL_VERSION, "")
    path = "/checkout/cart/create" if cart else "/checkout/create"
    headers = {"authorization":"Bearer synthetic"}
    rejected = c.post(path, headers=headers, json=body)
    assert rejected.status_code == 409 and calls == []
    with factory() as db: assert db.query(api.Order).count() == 0
    body["pricing_config_version"] = version
    accepted = c.post(path, headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    amounts = [x["shipping_rate_data"]["fixed_amount"]["amount"] for x in calls[0]["shipping_options"]]
    assert amounts == [sum(q["shipping"][key] for q in quotes)
                       for key in ("ups_ground_cents","ups_2day_cents","ups_nextday_cents")]


def test_inactive_quote_chamfer_values_do_not_add_or_remove_material():
    assert shipping_mass({**OP19, "chamfer_width":.0625}, .289) == shipping_mass(OP19, .289)
