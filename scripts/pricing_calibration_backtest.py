"""Offline comparison to the pinned deployed engine; no database or network writes."""
import argparse
import csv
import itertools
import json
from math import atan, hypot, pi, sin
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tuning_knobs as cfg
from pricing_engine import QuoteInputs, calculate_quote
from pricing_calibration import simulate_future_rush
from plate_geometry import PlateSpec, build_plate_geometry, rough_bore_diameter
from manufacturing_files import dxf_bytes
from io import StringIO
import ezdxf

BASE = "a9615a1e4d2b2013b0be7ddbf40ff409385c50ac"


def legacy_engine():
    module = types.ModuleType("pricing_accepted_baseline")
    sys.modules[module.__name__] = module
    source = subprocess.check_output(["git", "show", BASE + ":pricing_engine.py"], cwd=ROOT).decode()
    exec(compile(source, "accepted_pricing_engine.py", "exec"), module.__dict__)
    return module


def cut_length_audit(payload):
    spec = PlateSpec.from_configuration(payload)
    geometry = build_plate_geometry(spec)
    outer = sum(hypot(s.end[0]-s.start[0], s.end[1]-s.start[1]) if s.kind=='line'
                else s.radius * abs(s.sweep_degrees)*pi/180 for s in geometry.segments)
    bore = pi * rough_bore_diameter(spec)
    hole = pi * spec.handle_hole_diameter if spec.handle_hole_enabled else 0
    # Independent read of the actual generated DXF entities, including bulges.
    doc = ezdxf.read(StringIO(dxf_bytes(geometry).decode('ascii')))
    measured = 0
    for e in doc.modelspace():
        if e.dxftype() == 'CIRCLE':
            measured += 2*pi*e.dxf.radius
        elif e.dxftype() == 'LWPOLYLINE':
            pts=list(e.get_points('xyb'))
            for i,(x,y,b) in enumerate(pts):
                nx,ny,_=pts[(i+1)%len(pts)]
                chord=hypot(nx-x,ny-y)
                angle=4*atan(abs(b))
                measured += chord if not b else chord/(2*sin(angle/2))*angle
        else:
            raise AssertionError('Unexpected cut entity: '+e.dxftype())
    assert abs(measured-(outer+bore+hole)) < 1e-8
    return dict(canonical_outside_length_in=outer,rough_bore_cut_length_in=bore,
                handle_hole_cut_length_in=hole,canonical_total_cut_length_in=measured)


def compare(payload, service, old):
    previous=old.calculate_quote(old.QuoteInputs(**payload))
    proposed=calculate_quote(QuoteInputs(**payload))
    for key in ('material_cost','laser_cost','load_cost','inspection_cost','shipping',
                'estimated_unit_weight_lb','estimated_total_weight_lb','estimated_package_in'):
        assert previous[key] == proposed[key], (key,payload)
    old_subtotal = (
        payload['paddle_dia']*(payload['handle_length_from_bore']+payload['paddle_dia']/2)*cfg.PRICE_PER_SQ_IN[payload['material']][payload['thickness']]
        + (payload['handle_width']+2*payload['handle_length_from_bore']+payload['paddle_dia']/2*3.14)*cfg.LASER_PER_LINEAR_IN
        + 3.14*payload['bore_dia']*cfg.MILL_LABOR_PER_HR/cfg.MILL_SPEED_IPM*2
        + (3.14*payload['bore_dia']*cfg.MILL_LABOR_PER_HR/cfg.CHAMFER_SPEED_IPM*2 if payload['chamfer'] else 0)
        + cfg.LOAD_TIME_MINS*cfg.MILL_LABOR_PER_HR/60
        + cfg.INSPECTION_MINS_BY_TOL[payload['bore_tolerance']]*cfg.MILL_LABOR_PER_HR/60)
    assert round(old_subtotal, 2) == previous['subtotal_pre_multiplier']
    if service == 'today_2_day':
        p=simulate_future_rush(proposed['manufacturing_subtotal_unrounded'],payload['quantity'],proposed['qty_discount_multiplier'],cfg.TODAY_2_DAY_MULTIPLIER)
        previous_price=round(old_subtotal*cfg.TODAY_2_DAY_MULTIPLIER*previous['qty_discount_multiplier'],2)
        proposed_price=p['unit_price']
        multiplier=p['multiplier']
    else:
        previous_price,proposed_price=previous['unit_price'],proposed['unit_price']
        multiplier=proposed['lead_time_multiplier']
    change=proposed_price-previous_price
    return {**payload,'service_id':service,'lead_time_multiplier':multiplier,
            'quantity_discount':proposed['qty_discount_multiplier'],
            **{k:proposed[k] for k in ('material_cost','laser_cost','load_cost','inspection_cost')},
            'previous_bore_charge':previous['machine_bore_cost'],
            'proposed_bore_time_cost':proposed['bore_time_cost'],
            'proposed_bore_allowance':proposed['precision_bore_allowance'],
            'proposed_bore_charge':proposed['machine_bore_cost'],
            'previous_chamfer_charge':previous['chamfer_bore_cost'],
            'proposed_chamfer_time_cost':proposed['chamfer_time_cost'],
            'proposed_chamfer_allowance':proposed['chamfer_diameter_allowance'],
            'proposed_chamfer_charge':proposed['chamfer_bore_cost'],
            'proposed_chamfer_pass_count':proposed['chamfer_pass_count'],
            'proposed_chamfer_minutes':proposed['chamfer_machining_minutes'],
            'proposed_bore_pass_count':proposed['bore_pass_count'],
            'proposed_bore_minutes':proposed['bore_machining_minutes'],
            'previous_subtotal':previous['subtotal_pre_multiplier'],
            'proposed_subtotal':proposed['subtotal_pre_multiplier'],
            'previous_unit_price':previous_price,'proposed_unit_price':proposed_price,
            'previous_total':round(previous_price*payload['quantity'],2),
            'proposed_total':round(proposed_price*payload['quantity'],2),
            'unit_difference':round(change,2),'percent_difference':change/previous_price*100}


def main():
    out=ROOT/'review/pricing-calibration'
    out.mkdir(parents=True,exist_ok=True)
    old=legacy_engine()
    # Read-only production snapshot; apply only to this offline process.
    parser=argparse.ArgumentParser()
    parser.add_argument('--active-settings',type=Path,help='Owner-private read-only snapshot; never commit it')
    args=parser.parse_args()
    snapshot=json.loads(args.active_settings.read_text()) if args.active_settings else None
    if snapshot:
        import api_app
        api_app._apply_cfg_from_db_config(snapshot['config'])
    original=cfg.LEAD_TIME_MULTIPLIER
    cfg.LEAD_TIME_MULTIPLIER={21:1,14:1.6,7:2.3}  # offline hypotheses only
    rows=[]
    try:
        mt=[(m,t) for m,ts in cfg.PRICE_PER_SQ_IN.items() for t in ts]
        for (material,thickness),od,fraction,tol,width,qty,service in itertools.product(
            mt,(3,8,14.25),(.2,.6),(.005,.002,.001),(None,.015625,.03125,.062),
            (1,5,10,25),(21,14,7,'today_2_day')):
            payload=dict(quantity=qty,material=material,thickness=thickness,
                         handle_width=min(2,od/2),handle_length_from_bore=od/2+6,
                         paddle_dia=od,bore_dia=round(od*fraction,6),bore_tolerance=tol,
                         chamfer=width is not None,chamfer_width=width,
                         ships_in_days=21 if service=='today_2_day' else service)
            rows.append(compare(payload,service,old))
        with (out/'OPlates_Pricing_Backtest_13824.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator="\n");w.writeheader();w.writerows(rows)
        reference=[]
        for material,chamfer,service in itertools.product(('304','316'),(False,True),(21,14,7,'today_2_day')):
            p=dict(quantity=1,material=material,thickness=.25,handle_width=1,
                   handle_length_from_bore=13.125,paddle_dia=14.25,bore_dia=8.5,
                   bore_tolerance=.005,chamfer=chamfer,chamfer_width=.062 if chamfer else None,
                   handle_hole_enabled=True,handle_hole_diameter=.375,
                   handle_hole_center_from_handle_end=.625,
                   ships_in_days=21 if service=='today_2_day' else service)
            reference.append(compare(p,service,old))
        with (out/'reference.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(reference[0]),lineterminator="\n");w.writeheader();w.writerows(reference)
        summary=dict(baseline=BASE,config_basis='Owner-private active snapshot' if snapshot else 'Bundled repository defaults',
                     cases=len(rows),unchanged_components_reconciled=True,
                     cut_length=cut_length_audit(p),
                     ranges={name:dict(cases=len(group),minimum_percent=min(r['percent_difference'] for r in group),
                                      maximum_percent=max(r['percent_difference'] for r in group))
                             for name,group in [('non_chamfer',[r for r in rows if not r['chamfer']]),
                                                ('chamfer',[r for r in rows if r['chamfer']])]})
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps(summary,indent=2))
    finally:
        cfg.LEAD_TIME_MULTIPLIER=original


if __name__=='__main__': main()
