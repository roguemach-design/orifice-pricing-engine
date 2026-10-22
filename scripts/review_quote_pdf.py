"""Reproduce owner sample comparisons and pagination evidence, using actual pricing."""
import json
from pathlib import Path
from datetime import date
from quote_document import render_quote_pdf
from pricing_engine import calculate_quote, QuoteInputs

OUT=Path('review/quote-phase1'); OUT.mkdir(parents=True,exist_ok=True)
p=json.loads(Path('tests/fixtures/quote-review-samples.json').read_text())
def line(key):
    inputs=p[key]['inputs']; result=calculate_quote(QuoteInputs(**inputs))
    return dict(inputs=inputs,unit_price=result['unit_price'],total_price=result['total_price'],qty_mult=result['qty_discount_multiplier'],weight=result['estimated_total_weight_lb'])
for name,keys in [('A',['A1']),('B',[f'B{i}' for i in range(1,7)]),('25',['B5']*25),('60',['B5']*60)]:
    doc=dict(sample=True,quote_id='Q-7F3A9C21D4' if name=='A' else 'Q-2C8E41B0A6',issued=date(2026,10,22),pricing_ref='pcv-2026-10-21 (sample)',customer={'company':'Example Process Co. (sample)','name':'Jordan Example','email':'j.example@example.com','phone':'+1 555-0100','addr1':'100 Sample Way','city_state_zip':'Anytown, OH 00000','country':'United States'},lines=[line(k) for k in keys])
    if name=='B':
        doc['customer']={'company':'Sample Paper Mill LLC (synthetic)','name':'Casey Sample, Maintenance Engineering','email':'c.sample@example.com','phone':'+1 555-0142','addr1':'2400 Example River Rd','addr2':'Building 7, Receiving','city_state_zip':'Sampletown, WV 00000','country':'United States','purchasing':'Morgan Example, Purchasing · purchasing@example.com'}
    (OUT/f'Quote-{name}.pdf').write_bytes(render_quote_pdf(doc))
