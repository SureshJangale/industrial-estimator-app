"""Word template upload, review and rendering (synthetic project data only)."""
from io import BytesIO
from pathlib import Path
import uuid
from docx import Document
from pypdf import PdfReader
from tests.test_end_to_end import request, sample_project, get
from backend.word_quote_templates import (safe_docx, render_word, synthetic_pallet_context,
    docx_to_pdf, ALLOWED, REQUIRED, extract_tokens)

SRC=Path(__file__).resolve().parents[1]/'data'/'Pallet_Quotation_Reusable_Template.docx'

def test_pallet_template_placeholder_registry_and_dynamic_rows():
    blob=SRC.read_bytes()
    fields=safe_docx(blob)
    assert REQUIRED.issubset(set(fields))
    assert 'spec.length_mm' in fields and 'spec.height_mm' in fields
    assert 'material_lines.description' in fields and 'price_lines.amount' in fields
    assert set(fields)<=ALLOWED
    completed=render_word(blob,synthetic_pallet_context())
    doc=Document(BytesIO(completed))
    text='\n'.join(p.text for p in doc.paragraphs)
    assert '{{' not in text
    tables=['\n'.join(c.text for r in t.rows for c in r.cells) for t in doc.tables]
    combined='\n'.join(tables)
    for sample in ('SQ TUBE 40X40X3MM','MS FLAT 40X8MM','MS ANGLE 40X40X5MM','MS FLAT 25X3MM',
                   'MS MESH 1inchX1inch','MS ANGLE 40X40X3MM','MS SHEET 1.6MM THK'):
        assert sample in combined
    assert '1100 (UNVERIFIED)' in combined
    assert 'NOT FINAL' in combined
    assert '{{' not in combined
    assert len([r for t in doc.tables for r in t.rows if 'SQ TUBE' in '\t'.join(c.text for c in r.cells)])==1


def test_word_quotation_import_preview_replacement_and_binding():
    code='pallet_word_'+uuid.uuid4().hex[:7]
    b=SRC.read_bytes()
    data={'code':code,'name':'Pallet DOCX layout','workflow':'equipment_supply'}
    assert request('POST','/api/quote-templates/import-docx',username='estimator',data=data,
         files={'file':('pallet.docx',b,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')}).status_code==403
    response=request('POST','/api/quote-templates/import-docx',username='demo',data=data,
         files={'file':('pallet.docx',b,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code==200,response.text
    assert response.json()['source_type']=='docx'
    assert 'material_lines.description' in response.json()['placeholders']
    file_response=request('GET',f'/api/quote-templates/{code}/source.docx')
    assert file_response.status_code==200 and file_response.content==b
    assert request('GET',f'/api/quote-templates/{code}/source.docx',username='estimator').status_code==403
    pdf=request('GET',f'/api/quote-templates/{code}/preview.pdf')
    assert pdf.status_code==200,pdf.text if pdf.status_code!=200 else ''
    rendered='\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
    assert 'ANNEXURE A - TECHNICAL SPECIFICATION' in rendered
    assert 'SQ TUBE 40X40X3MM' in rendered
    assert 'PENDING REVIEW' in rendered
    pid=sample_project('fabricated_pallet')
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'equipment_supply','template':code}).status_code==200
    terms=get(pid)['commercial']['profile']['terms']
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'terms':{**terms,'customer_attention':'Ms. Word Template Tester'}}).status_code==200
    project_quote=request('GET',f'/api/projects/{pid}/commercial/preview.pdf')
    assert project_quote.status_code==200,project_quote.text if project_quote.status_code!=200 else ''
    ptext='\n'.join(page.extract_text() for page in PdfReader(BytesIO(project_quote.content)).pages)
    assert 'ANNEXURE C - COMMERCIAL TERMS' in ptext
    assert 'NOT FINAL' in ptext
    fp=get(pid)['commercial']['gates']['fingerprint']
    reup=request('PUT',f'/api/quote-templates/{code}/replace-docx',username='demo',
         files={'file':('pallet-updated.docx',b,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert reup.status_code==200,reup.text
    assert reup.json()['version']==2
    assert fp!=get(pid)['commercial']['gates']['fingerprint']


def test_invalid_word_templates_blocked():
    code='invalid_word_'+uuid.uuid4().hex[:8]
    data={'code':code,'name':'Invalid sample','workflow':'equipment_supply'}
    assert request('POST','/api/quote-templates/import-docx',username='demo',data=data,
        files={'file':('fake.docx',b'not a zip','application/octet-stream')}).status_code==422
    doc=Document();doc.add_paragraph('{{buyer.name}} {{quote.number}}')
    b=BytesIO();doc.save(b)
    assert request('POST','/api/quote-templates/import-docx',username='demo',data=data,
        files={'file':('missing.docx',b.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')}).status_code==422
    doc=Document();doc.add_paragraph('{{buyer.name}} {{quote.number}} {{product.name}} {{pricing.total}} {{seller.evil_code}}')
    b=BytesIO();doc.save(b)
    assert request('POST','/api/quote-templates/import-docx',username='demo',data=data,
        files={'file':('unknown.docx',b.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')}).status_code==422


def test_design_document_and_quotation_layout_are_separate_uploads():
    from backend.app import Document as DesignRecord, SessionLocal
    from backend.word_quote_templates import WordTemplateAsset
    from sqlalchemy import select
    pid=sample_project('fabricated_pallet')
    before=request('GET','/api/quote-templates').json()
    design=(SRC.parent/'SYNTHETIC_DESIGN_REQUIREMENTS.docx').read_bytes()
    saved=request('POST',f'/api/projects/{pid}/documents',username='estimator',
        files={'file':('source_design.docx',design,
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert saved.status_code==200,saved.text
    assert any(d['original_name']=='source_design.docx' for d in get(pid)['documents'])
    assert len(request('GET','/api/quote-templates').json())==len(before)
    code='pallet_layout_'+uuid.uuid4().hex[:7]
    imported=request('POST','/api/quote-templates/import-docx',username='demo',
        data={'code':code,'name':'Reviewed pallet template','workflow':'equipment_supply'},
        files={'file':('reusable_quote.docx',SRC.read_bytes(),
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert imported.status_code==200,imported.text
    assert len(get(pid)['documents'])==1
    assert any(t['code']==code for t in request('GET','/api/quote-templates').json())
    with SessionLocal() as db:
        design_rows=db.scalars(select(DesignRecord).where(DesignRecord.project_id==pid)).all()
        assert len(design_rows)==1
        assert len(db.scalars(select(WordTemplateAsset)).all())>=1
    example=request('GET','/api/quote-templates/example-pallet.docx',username='demo')
    assert example.status_code==200
    assert 'material_lines.description' in safe_docx(example.content)
    assert request('GET','/api/quote-templates/example-pallet.docx',username='estimator').status_code==403
