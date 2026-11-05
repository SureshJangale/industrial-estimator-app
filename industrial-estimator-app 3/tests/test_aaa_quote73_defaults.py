"""Verify the latest uploaded Quote 73 style is the actual bootstrap default.

This test is executed before any tests that deliberately change workflow defaults.
"""
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader
from sqlalchemy import select
from tests.test_end_to_end import request, sample_project, get
from backend.app import SessionLocal
from backend.templates import QuoteTemplate
from backend.word_quote_templates import WordTemplateAsset, safe_docx, synthetic_quote73_context, render_word

def test_quote73_defaults_are_installed_for_all_workflows():
    defaults={'equipment_supply':'quote73_equipment',
              'service_repair':'quote73_service','general_sale':'quote73_general'}
    for wf,code in defaults.items():
        rows=request('GET','/api/quote-templates').json()
        active=[x for x in rows if x['workflow']==wf and x['is_default']]
        assert [x['code'] for x in active]==[code]
        assert active[0]['source_type']=='docx'
        assert 'tax_lines.amount' in active[0]['placeholders']
        assert 'price_lines.description' in active[0]['placeholders']
        preview=request('GET',f'/api/quote-templates/{code}/preview.pdf')
        assert preview.status_code==200,preview.text if preview.status_code!=200 else ''
        t=' '.join(page.extract_text() for page in PdfReader(BytesIO(preview.content)).pages)
        assert 'Pallet lifting chain (sample supply)' in t
        assert '18,290.00' in t
        assert 'CGST' in t and 'SGST' in t
        assert 'SAMPLE CUSTOMER' in t
        assert 'Reliable Aototech' not in t
        assert 'Quot No.73/YE' not in t
    with SessionLocal() as db:
        assert len(db.scalars(select(WordTemplateAsset)).all())>=3

def test_new_projects_select_quote73_format_automatically():
    for wf,product in [('equipment_supply','fabricated_pallet'),
                       ('service_repair','generic_service'),
                       ('general_sale','fabricated_pallet')]:
        pid=sample_project(product)
        r=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':wf})
        assert r.status_code==200,r.text
        assert get(pid)['commercial']['profile']['template']=={
            'equipment_supply':'quote73_equipment',
            'service_repair':'quote73_service',
            'general_sale':'quote73_general'}[wf]

def test_quote73_placeholders_are_safe_and_rendered_without_historic_customer():
    p=Path(__file__).resolve().parents[1]/'data'/'Quote73_One_Page_Reusable_Template.docx'
    raw=p.read_bytes();names=safe_docx(raw)
    assert {'quote.number','buyer.name','product.name','pricing.total','tax_lines.name'}<=set(names)
    assert b'Reliable Autotech' not in raw
    filled=render_word(raw,synthetic_quote73_context())
    assert b'Not specified' not in filled[:100]  # DOCX ZIP payload starts as PK archive
