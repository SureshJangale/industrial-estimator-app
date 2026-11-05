"""Default Quote 73 has the source's fixed geometry; no historic data copied."""
from copy import deepcopy
from io import BytesIO
import pytest
from pypdf import PdfReader
from fastapi import HTTPException
from backend.quote73_exact import render_quote73, LayoutOverflow, PAGE_W, PAGE_H
from backend.word_quote_templates import synthetic_quote73_context, synthetic_pallet_context


def text_for(context):
    raw=render_quote73(context)
    r=PdfReader(BytesIO(raw))
    assert len(r.pages)==1
    assert abs(float(r.pages[0].mediabox.width)-PAGE_W)<1
    assert abs(float(r.pages[0].mediabox.height)-PAGE_H)<1
    return r.pages[0].extract_text()


def test_reference_pattern_and_total_are_dynamic():
    context=synthetic_quote73_context()
    t=text_for(context)
    for label in ('QUOTATION','Work as follows :-','Sr.No.','Particulars','Qty',
                  'ADD-CGST','ADD-SGST','TOTAL','18,290.00','15,500.00',
                  'YASH ENGINEERING', 'Works Add :-',
                  'OUR G.S.T IN.NO.', 'Sample Industrial Area'):
        assert label in t,label
    assert 'Reliable Aototech' not in t
    assert '31/10/2026' not in t
    assert 'Quot No.73/YE' not in t
    # Fixed letter wording follows supplied Quote 73; it is not rewritten.
    assert 'countesy extended to the undersigned' in t
    assert 'kind persual.' in t
    assert 'valid for next 15 days from quote date' in t
    context2=deepcopy(context)
    context2['scalars']['buyer.name']='TEST DIFFERENT CUSTOMER'
    context2['scalars']['quote.number']='TEST-002'
    context2['scalars']['seller.gstin']='NOTA-REAL-GSTIN'
    context2['scalars']['seller.works_address']='New test workshop'
    context2['scalars']['pricing.total']='INR 45678.00'
    context2['scalars']['pricing.subtotal']='INR 40000.00'
    context2['tax_lines']=[{'name':'CGST','rate':'7','amount':'INR 2800.00'},
                           {'name':'SGST','rate':'7','amount':'INR 2800.00'}]
    t2=text_for(context2)
    for present in ('TEST DIFFERENT CUSTOMER','TEST-002','NOTA-REAL-GSTIN',
                    'New test workshop','45,678.00','7%'):
        assert present in t2,present
    assert 'SAMPLE-001/YE' not in t2
    assert '18,290.00' not in t2


def test_missing_values_are_not_silently_zero():
    t=text_for(synthetic_pallet_context())
    assert 'PENDING' in t
    assert 'DRAFT / SYNTHETIC PREVIEW - NOT FOR ISSUE' in t
    assert '0.00' not in t  # total is withheld while price/tax verification is pending


def test_do_not_clip_long_quotations_or_too_many_taxes():
    ctx=synthetic_quote73_context()
    ctx['price_lines']=[dict(ctx['price_lines'][0]) for _ in range(21)]
    with pytest.raises(LayoutOverflow,match='one-page'):
        render_quote73(ctx)
    ctx=synthetic_quote73_context()
    ctx['tax_lines']=[{'name':str(i),'rate':'10','amount':'10'} for i in range(3)]
    with pytest.raises(LayoutOverflow,match='two tax rows'):
        render_quote73(ctx)
