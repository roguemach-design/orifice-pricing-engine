"""Independent units, reconciliation, commercial controls and unavailable rush gates."""
from dataclasses import asdict
from math import pi
import copy
import pytest
import tuning_knobs as cfg
from pricing_engine import calculate_quote
from pricing_calibration import future_rush_eligibility, simulate_future_rush, TODAY_2_DAY_ID
from test_pricing_engine import valid_inputs
from test_pricing_configuration import client, snapshot, save, OWNER


@pytest.mark.parametrize('tol,spring', [(.005,0),(.002,1),(.001,2)])
def test_estimated_contours_units_and_all_components(tol, spring):
    x = valid_inputs(bore_dia=1, bore_tolerance=tol, chamfer=True, chamfer_width=.0625)
    q = calculate_quote(x)
    assert q['rough_bore_diameter_in'] == .875
    minutes = pi * ((.875 + .125/3) + (.875 + 2*.125/3) + 1 + spring) / 28
    assert q['bore_pass_count'] == 3 + spring
    assert q['bore_machining_minutes'] == pytest.approx(minutes)
    assert q['bore_time_cost'] == pytest.approx(minutes * 150/60)
    assert q['precision_bore_allowance'] == 32.5
    assert q['chamfer_pass_count'] == 1
    assert q['chamfer_time_cost'] == pytest.approx(pi*1.0625/28*150/60)
    assert q['chamfer_diameter_allowance'] == 5
    assert q['additional_chamfer_setup_cost'] == 0
    assert sum(q['manufacturing_cost_components'].values()) == pytest.approx(q['manufacturing_subtotal_unrounded'])


@pytest.mark.parametrize('days,multiplier', [(21,1), (14,1.6), (7,2.3)])
@pytest.mark.parametrize('qty,discount', [(1,1),(5,.97),(10,.95),(25,.92)])
def test_entire_subtotal_gets_lead_then_quantity(monkeypatch, days, multiplier, qty, discount):
    monkeypatch.setattr(cfg,'LEAD_TIME_MULTIPLIER',{21:1,14:1.6,7:2.3})
    q=calculate_quote(valid_inputs(quantity=qty,ships_in_days=days))
    assert q['unit_price'] == round(sum(q['manufacturing_cost_components'].values())*multiplier*discount,2)
    assert q['total_price'] == round(q['unit_price']*qty,2)


def test_no_chamfer_means_no_chamfer_cost_and_width_affects_estimate():
    a=calculate_quote(valid_inputs(chamfer=False,chamfer_width=None))
    assert a['chamfer_bore_cost'] == a['chamfer_machining_minutes'] == a['chamfer_diameter_allowance'] == 0
    b=calculate_quote(valid_inputs(chamfer_width=.03125))
    c=calculate_quote(valid_inputs(chamfer_width=.125))
    assert c['chamfer_time_cost'] > b['chamfer_time_cost']
    assert c['chamfer_diameter_allowance'] == b['chamfer_diameter_allowance']
    assert b['load_cost'] == c['load_cost'] == a['load_cost'] == 15


def test_unavailable_rush_never_grants_purchase_even_when_ready(monkeypatch):
    ready=dict(material_ready=True,blank_ready=True,capacity_confirmed=True,
               cutoff_confirmed=True,method_qualified=True,shipment_window_confirmed=True)
    assert not future_rush_eligibility()['readiness_requirements_met']
    result=future_rush_eligibility(**ready)
    assert result['readiness_requirements_met'] and not result['eligible'] and not result['available']
    assert result['service_id'] == TODAY_2_DAY_ID == 'today_2_day'
    for gate in ready:
        assert not future_rush_eligibility(**{**ready,gate:False})['readiness_requirements_met']
    for invalid in (2,0,1):
        monkeypatch.setattr(cfg,'LEAD_TIME_MULTIPLIER',{invalid:3.3})
        with pytest.raises(ValueError,match='unsupported ships_in_days'):
            calculate_quote(valid_inputs(ships_in_days=invalid))
    hypothetical=simulate_future_rush(100,5,.97,cfg.TODAY_2_DAY_MULTIPLIER)
    assert hypothetical['unit_price'] == 320.1 and hypothetical['total_price'] == 1600.5
    assert not hypothetical['available']


def test_allowances_use_existing_owner_version_history_and_restore(client):
    c,factory=client
    before=snapshot(c)
    assert before['config']['precision_bore_allowance_per_in'] == 32.5
    assert before['config']['chamfer_allowance_per_in'] == 5
    assert before['config']['today_2_day_multiplier'] == 3.3
    assert before['config']['lead_time_multipliers']['7'] == 2.3
    assert before['config']['lead_time_enabled']['7'] is False
    changed=save(c,before,precision_bore_allowance_per_in=33,chamfer_allowance_per_in=6)
    assert changed.status_code == 200
    q=c.post('/quote',headers={'x-api-key':'synthetic-quote'},json=valid_inputs().model_dump())
    assert q.status_code == 200
    result=q.json()
    assert result['precision_bore_allowance'] == 33 and result['chamfer_diameter_allowance'] == 6
    current=snapshot(c)
    assert save(c,before,chamfer_allowance_per_in=9).status_code == 409
    restore=c.post('/admin/config/restore',headers=OWNER,json={'_version':current['version'],
        '_confirmation':'RESTORE CONFIGURATION','history_id':current['history'][0]['id']})
    assert restore.status_code == 200
    restored=snapshot(c)
    assert restored['config']['precision_bore_allowance_per_in'] == 32.5
    assert restored['config']['chamfer_allowance_per_in'] == 5
    assert restored['config']['lead_time_enabled'] == before['config']['lead_time_enabled']


@pytest.mark.parametrize('field,value',[('precision_bore_allowance_per_in',-1),('chamfer_allowance_per_in',-1),('today_2_day_multiplier',0)])
def test_invalid_allowances_do_not_change_version(client,field,value):
    c,_=client
    state=snapshot(c)
    assert save(c,state,**{field:value}).status_code == 422
    assert snapshot(c)['version'] == state['version']


@pytest.mark.parametrize('hole',[False,True])
def test_cut_length_audit_matches_exported_rough_dxf(hole):
    from scripts.pricing_calibration_backtest import cut_length_audit
    x=valid_inputs(chamfer=False,chamfer_width=None,handle_hole_enabled=hole,
                   handle_hole_diameter=.375 if hole else None,
                   handle_hole_center_from_handle_end=.75 if hole else None)
    audit=cut_length_audit(x.model_dump())
    assert audit['canonical_total_cut_length_in'] == pytest.approx(
        audit['canonical_outside_length_in']+audit['rough_bore_cut_length_in']+audit['handle_hole_cut_length_in'])
    if hole: assert audit['handle_hole_cut_length_in'] == pytest.approx(pi*.375)


def test_stock_allowance_cannot_make_a_nonpositive_rough_bore():
    with pytest.raises(ValueError,match='rough bore must be positive'):
        calculate_quote(valid_inputs(bore_dia=.125))


@pytest.mark.parametrize('field',['precision_bore_allowance_per_in','chamfer_allowance_per_in','today_2_day_multiplier'])
def test_allowance_configuration_rejects_nonfinite_values(field):
    import api_app
    from pricing_configuration import project, validate
    defaults=project(api_app._default_knobs_config(),api_app._CFG_BASELINE)
    for value in (float('nan'),float('inf'),float('-inf')):
        changed=copy.deepcopy(defaults)
        changed[field]=value
        with pytest.raises(ValueError,match='finite'):
            validate(changed,defaults)
