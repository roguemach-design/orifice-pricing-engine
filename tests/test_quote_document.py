from copy import deepcopy
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import pdfplumber
import pytest
from quote_document import render_quote_pdf, spec_rows, new_quote_meta, quote_filename, document_from_cart

SAMPLES=json.loads(Path('tests/fixtures/quote-review-samples.json').read_text())
def document(n=1):
    p=SAMPLES['B5']
    return dict(quote_id='Q-1234567890',issued=date(2026,10,22),pricing_ref='test-current',customer={},lines=[dict(inputs=dict(p['inputs'],handle_label=f'PLATE-{i:03d}'),unit_price=12.34,total_price=37.01,qty_mult=.9,weight=2) for i in range(n)])

@pytest.mark.parametrize('n',[1,6,25,60])
def test_pagination_complete_specs_and_authoritative_totals(n):
    doc=document(n)
    with pdfplumber.open(BytesIO(render_quote_pdf(doc))) as pdf:
        texts=[p.extract_text() for p in pdf.pages]
        all_text='\n'.join(texts)
        assert f'${37.01*n:,.2f}' in all_text
        for i in range(n):
            matches=[t for t in texts if f'PLATE-{i:03d}' in t]
            assert len(matches)==1
            assert 'ITEM AND SPECIFICATION' in matches[0]
            assert '0.0625 in' in matches[0]
        for i,t in enumerate(texts,1):
            assert f'Page {i} of {len(texts)}' in t
            assert '400 Public Rd, Yorkville, OH 43971' in t
        for copy in ['Quotation only','revalidated at checkout','Selected at checkout']:
            assert copy in all_text
        for bad in ['Wheeling','Stone and Shannon','Grand total','Thank you for the opportunity','View or order this quote']:
            assert bad not in all_text
        # Every glyph stays inside paper and above the footer content floor.
        for page in pdf.pages:
            assert all(39 <= c['x0'] and c['x1'] <= 573 for c in page.chars)

def test_new_numbers_filename_and_deterministic_snapshot():
    a,b=new_quote_meta(),new_quote_meta()
    assert a['quote_id']!=b['quote_id']
    d=document(); d['quote_id']=a['quote_id']
    payload=render_quote_pdf(d)
    assert payload==render_quote_pdf(d)
    assert quote_filename(a['quote_id'])==f"O-Plates_Quote_{a['quote_id']}.pdf"
    with pdfplumber.open(BytesIO(payload)) as pdf:
        assert a['quote_id'] in pdf.pages[0].extract_text()
        assert pdf.metadata['Title']==f"O-Plates Quotation {a['quote_id']}"

@pytest.mark.parametrize('customer',[{}, {'name':'Partial'}, {'company':'Long customer name '*6,'email':'a'*65+'@example.test','purchasing_name':'Buyer','purchasing_email':'buyer@example.test'}])
def test_partial_long_customer_and_marking(customer):
    d=document();d['customer']=customer;d['lines'][0]['inputs']['handle_label']='LONG_UNBROKEN_MARKING_'*4
    with pdfplumber.open(BytesIO(render_quote_pdf(d))) as pdf:
        text=''.join(p.extract_text().replace('\n','') for p in pdf.pages)
        assert 'LONG_UNBROKEN_MARKING_'*4 in text
        assert all(c['x1']<=573 for p in pdf.pages for c in p.chars)

def test_only_present_fields_no_defaulted_geometry():
    assert spec_rows({'chamfer':True,'handle_label':'No label'})==[('Handle hole','None'),('Chamfer','Selected; size per confirmation drawing'),('Handle marking','None')]
    assert spec_rows({})==[('Handle hole','None'),('Chamfer','None'),('Handle marking','None')]

@pytest.mark.parametrize('sample',['A1','B5'])
@pytest.mark.parametrize('revision',[1,2])
@pytest.mark.parametrize('live',[False,True])
def test_ordinary_single_plate_is_one_page_with_every_specification(sample,revision,live):
    d=document()
    d['lines'][0]['inputs']=deepcopy(SAMPLES[sample]['inputs'])
    d['customer']={'company':'Example Process Co.','name':'Jordan Example','addr1':'100 Sample Way','city_state_zip':'Anytown, OH 00000','country':'United States','email':'j.example@example.test','phone':'+1 555-0100'}
    if revision==2:
        d['supersedes']=d['quote_id'];d['quote_id']+='-R2'
    d['retrieval_live']=live
    d['retrieval_url']='https://quote.o-plates.com/My_Quotes?quote='+d['quote_id']
    with pdfplumber.open(BytesIO(render_quote_pdf(d))) as pdf:
        assert len(pdf.pages)==1
        text=' '.join(pdf.pages[0].extract_text().split())
        # Read columns independently: whole-page extraction interleaves the
        # left specification label into wrapped values in the right column.
        columns=[' '.join(pdf.pages[0].crop(box).extract_text().split()) for box in
                 ((76,0,328,705),(328,0,570,705))]
        for label,value in spec_rows(d['lines'][0]['inputs']):
            assert label in text
            assert any(' '.join(value.split()) in column for column in columns)
        assert 'HOW TO ORDER FROM THIS QUOTATION' in text and 'QUOTATION TERMS' in text
        assert 'https://' not in text
        if live:
            assert 'find '+d['quote_id']+' under My Quotes' in text
            assert 'quote.o-plates.com/My_Quotes' in text
            assert any(a.get('uri')==d['retrieval_url'] for a in pdf.pages[0].annots)
        else:
            assert 'quote.o-plates.com/My_Quotes' not in text
        # Panel text must remain above the footer, not merely inside the page.
        assert all(c['bottom'] < 705 for c in pdf.pages[0].chars if c['top'] < 700)

def test_timezone_and_cart_adapter_does_not_reprice():
    d=document(); l=d['lines'][0]
    view=dict(inputs=l['inputs'],unit_price=1.01,line_total=3.02,qty_discount_multiplier=.95,estimated_total_weight_lb=4)
    doc=document_from_cart([view],{},dict(quote_id='Q-EXAMPLE',created_at=datetime(2026,10,23,1,tzinfo=timezone.utc)),'current')
    assert doc['issued']==date(2026,10,22)
    assert doc['lines'][0]['total_price']==3.02
    assert doc['lines'][0]['qty_mult']==.95
