import pytest

from pricing_engine import QuoteInputs, calculate_quote
import tuning_knobs as cfg


def valid_inputs(**overrides) -> QuoteInputs:
    values = {
        "quantity": 1,
        "material": "304",
        "thickness": 0.125,
        "handle_width": 1.5,
        "handle_length_from_bore": 9.0,
        "paddle_dia": 3.0,
        "bore_dia": 1.0,
        "bore_tolerance": 0.005,
        "chamfer": True,
        "chamfer_width": None,
        "handle_label": "No label",
        "ships_in_days": 21,
    }
    values.update(overrides)
    return QuoteInputs(**values)


def test_baseline_quote_is_deterministic():
    result = calculate_quote(valid_inputs())

    assert result["unit_price"] == 121.38
    assert result["total_price"] == 121.38
    assert result["estimated_total_weight_lb"] == 1.14
    assert result["estimated_package_in"] == {
        "length": 14.5,
        "width": 7.0,
        "height": 1.0,
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"quantity": 0}, "quantity must be >= 1"),
        ({"handle_width": 0}, "handle_width must be > 0"),
        ({"paddle_dia": 0}, "paddle_dia must be > 0"),
        ({"bore_dia": 0}, "bore_dia must be > 0"),
        ({"paddle_dia": 3, "bore_dia": 3}, "bore_dia must be smaller"),
        (
            {"paddle_dia": 4, "handle_length_from_bore": 2},
            "handle_length_from_bore must be longer",
        ),
        ({"chamfer_width": 0}, "chamfer_width must be > 0"),
    ],
)
def test_rejects_invalid_geometry(overrides, message):
    with pytest.raises(ValueError, match=message):
        calculate_quote(valid_inputs(**overrides))


def test_quantity_tier_is_applied_reproducibly():
    result = calculate_quote(valid_inputs(quantity=10))

    assert result["qty_discount_multiplier"] == 0.95
    assert result["quantity"] == 10
    assert result["total_price"] == round(result["unit_price"] * 10, 2)


def test_disabled_or_unknown_material_is_rejected():
    with pytest.raises(ValueError, match="unknown material"):
        calculate_quote(valid_inputs(material="Monel"))


@pytest.mark.parametrize(
    ("material", "thickness"),
    [
        (material, thickness)
        for material, thicknesses in cfg.PRICE_PER_SQ_IN.items()
        for thickness in thicknesses
    ],
)
def test_every_enabled_material_thickness_prices(material, thickness):
    result = calculate_quote(valid_inputs(material=material, thickness=thickness))

    assert result["unit_price"] > 0
    assert result["total_price"] == result["unit_price"]


@pytest.mark.parametrize("ships_in_days", sorted(cfg.LEAD_TIME_MULTIPLIER))
def test_every_enabled_lead_time_prices(ships_in_days):
    result = calculate_quote(valid_inputs(ships_in_days=ships_in_days))

    assert result["lead_time_multiplier"] == cfg.LEAD_TIME_MULTIPLIER[ships_in_days]


@pytest.mark.parametrize("bore_tolerance", sorted(cfg.INSPECTION_MINS_BY_TOL))
def test_every_supported_tolerance_prices(bore_tolerance):
    result = calculate_quote(valid_inputs(bore_tolerance=bore_tolerance))

    assert result["inspection_cost"] > 0


def test_chamfer_can_be_disabled():
    with_chamfer = calculate_quote(valid_inputs(chamfer=True))
    without_chamfer = calculate_quote(
        valid_inputs(chamfer=False, chamfer_width=None)
    )

    assert with_chamfer["chamfer_bore_cost"] > 0
    assert without_chamfer["chamfer_bore_cost"] == 0
    assert without_chamfer["unit_price"] < with_chamfer["unit_price"]


@pytest.mark.parametrize("paddle_dia", [47.999, 48.0])
def test_paddle_diameter_at_or_below_maximum_is_accepted(paddle_dia):
    result = calculate_quote(
        valid_inputs(paddle_dia=paddle_dia, handle_length_from_bore=25.0)
    )
    assert result["unit_price"] > 0


def test_paddle_diameter_above_maximum_is_rejected():
    with pytest.raises(
        ValueError,
        match=r"Maximum configurable plate outside diameter is 48 in\.",
    ):
        calculate_quote(
            valid_inputs(paddle_dia=48.001, handle_length_from_bore=25.0)
        )


@pytest.mark.parametrize("bore_dia", [18.999, 19.0])
def test_bore_diameter_at_or_below_maximum_is_accepted(bore_dia):
    result = calculate_quote(
        valid_inputs(
            paddle_dia=24.0,
            bore_dia=bore_dia,
            handle_length_from_bore=13.0,
        )
    )
    assert result["unit_price"] > 0


def test_bore_diameter_above_maximum_is_rejected():
    with pytest.raises(
        ValueError,
        match=r"Maximum configurable bore diameter is 19 in\.",
    ):
        calculate_quote(
            valid_inputs(
                paddle_dia=24.0,
                bore_dia=19.001,
                handle_length_from_bore=13.0,
            )
        )


@pytest.mark.parametrize("bore_dia", [3.0, 3.001])
def test_bore_equal_to_or_greater_than_paddle_is_rejected(bore_dia):
    with pytest.raises(ValueError, match="bore_dia must be smaller than paddle_dia"):
        calculate_quote(valid_inputs(paddle_dia=3.0, bore_dia=bore_dia))


@pytest.mark.parametrize("length", [39, 40])
def test_handle_marking_at_or_below_limit_is_accepted(length):
    result = calculate_quote(valid_inputs(handle_label="A" * length))
    assert result["handle_label"] == "A" * length


def test_handle_marking_above_limit_is_rejected():
    with pytest.raises(ValueError, match="Handle marking must be 40 characters or fewer"):
        calculate_quote(valid_inputs(handle_label="A" * 41))


def test_chamfer_operation_does_not_require_or_invent_width():
    result = calculate_quote(valid_inputs(chamfer=True, chamfer_width=None))
    assert result["chamfer_bore_cost"] > 0
    assert result["chamfer_width"] is None
