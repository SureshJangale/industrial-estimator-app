"""v0.5 regression: PDF layouts and source-linked DOCX/PDF prefill.

No private customer documents are stored in the software or test fixtures.
"""
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from pypdf import PdfReader
from tests.test_end_to_end import request,sample_project,get,make_pdf


def make_docx(lines):
    from xml.sax.saxutils import escape
    xml=(
      '<?xml version="1.0" encoding="UTF-8"?>'
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
      '<w:body>'+
      ''.join('<w:p><w:r><w:t>'+escape(line)+'</w:t></w:r></w:p>' for line in lines)+
      '</w:body></w:document>'
    )
    buffer=BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as z:z.writestr('word/document.xml',xml)
    return buffer.getvalue()


def read_pdf(blob):
    reader=PdfReader(BytesIO(blob))
    text='\n'.join(p.extract_text() or '' for p in reader.pages)
    return len(reader.pages),text


def test_builtin_classic_formats_are_visible_in_template_api():
    rows=request('GET','/api/quote-templates',username='estimator').json()
    layouts={row['code']:row for row in rows}
    assert layouts['multi_annexure']['layout']['format_style']=='classic_equipment'
    assert layouts['short_service']['layout']['format_style']=='classic_service'
    assert layouts['quote73_equipment']['is_default']
    assert not layouts['multi_annexure']['is_default']
    assert any(row['is_default'] for row in rows if row['workflow']=='service_repair')
    assert layouts['simple_sales']['layout']['format_style']=='modern'
    for code in ('multi_annexure','short_service','simple_sales'):
        assert request('GET',f'/api/quote-templates/{code}/preview.pdf',username='estimator').status_code==200


def test_equipment_quote_has_cover_letter_and_annexures():
    r=request('GET','/api/quote-templates/multi_annexure/preview.pdf',username='estimator')
    assert r.status_code==200,r.text
    pages,text=read_pdf(r.content)
    assert pages>=5
    for marker in ('TECHNO COMMERCIAL OFFER','QUOTATION NO','ANNEXURE - A',
                   'ANNEXURE - B','ANNEXURE - C','TECHNICAL SPECIFICATION',
                   'PRICE SCHEDULE','COMMERCIAL TERMS','CERTIFICATION','850000'):
        assert marker in text, marker
    assert 'DRAFT - NOT FOR ISSUE' in text


def test_repair_quote_is_compact_and_has_tax_totals():
    r=request('GET','/api/quote-templates/short_service/preview.pdf',username='estimator')
    assert r.status_code==200,r.text
    pages,text=read_pdf(r.content)
    assert pages==1
    for marker in ('Work as follows','39500','6000','45500','4095','53690','CGST','SGST','Payment terms'):
        assert marker in text, marker


def equipment_project():
    r=request('POST','/api/projects',username='estimator',json={
        'customer':'Synthetic Equip Customer','title':'Sample overhead crane',
        'product_code':'eot_crane','quote_workflow':'equipment_supply'})
    assert r.status_code==200,r.text
    pid=r.json()['project']['id']
    # Backward-compatibility coverage for archived commercial crane projects.
    # New project creation itself always uses cost-plus.
    selected=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',
                     json={'workflow':'equipment_supply'})
    assert selected.status_code==200,selected.text
    return pid


def test_word_upload_prefills_unique_requirements_but_requires_review():
    pid=equipment_project()
    docx=make_docx(['SYNTHETIC TECHNICAL SPECIFICATION',
       'Span: 8.6 Mtr.','Capacity: 5 Te','Lift: 6 Mtr.',
       'Headroom: 450 mm','Painting: two coats primer',
       'Erection and Commissioning required.'])
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',
             files={'file':('engineering-design.docx',docx,
             'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert r.status_code==200,r.text
    data=r.json()
    assert data['documents'][0]['document_type']=='DOCX'
    req={r['key']:r for r in data['requirements']}
    assert req['rail_span_m']['value']=='8.6'
    assert req['rail_span_m']['status']=='PENDING'
    assert req['rail_span_m']['confidence_score'] is not None
    assert req['rail_span_m']['document_id']==data['documents'][0]['id']
    assert 'engineering-design.docx' in req['rail_span_m']['evidence']
    assert req['safe_working_load_t']['value']=='5'
    assert req['lifting_height_m']['value']=='6'
    tech=[f for sec in data['commercial']['profile']['technical'] for f in sec['fields']]
    span=next(f for f in tech if f['key']=='rail_span_m')
    assert span['value']=='8.6' and span['review_status']=='PENDING'
    operations={c['code']:c for c in data['documents'][0]['candidates'] if c['kind']=='operation'}
    assert {'paint','erect','commission'}<=set(operations)
    assert all(op['hours'] is None and op['rate'] is None for op in operations.values())
    assert not data['commercial']['gates']['firm_ready']


def test_ambiguous_technical_values_are_never_autofilled():
    pid=equipment_project()
    docx=make_docx(['Span: 40 Mtr.','Price schedule crane 25 mtr Span'])
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',
           files={'file':('conflict.docx',docx,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert r.status_code==200,r.text
    data=r.json()
    span=next(x for x in data['requirements'] if x['key']=='rail_span_m')
    assert span['value']=='' and span['document_id'] is None
    assert any(x['key']=='rail_span_m' for x in data['extraction_conflicts'])
    assert not data['commercial']['gates']['firm_ready']


def test_admin_can_choose_classic_format_for_custom_template_but_not_mismatch():
    base=request('GET','/api/quote-templates').json()
    source=next(x for x in base if x['code']=='multi_annexure')
    body={'code':'new_equip_standard','name':'Equipment standard variant','workflow':'equipment_supply','layout':source['layout']}
    r=request('POST','/api/quote-templates',username='demo',json=body)
    assert r.status_code==200,r.text
    assert r.json()['layout']['format_style']=='classic_equipment'
    wrong={**body,'code':'service_wrong_format','workflow':'service_repair'}
    assert request('POST','/api/quote-templates',username='demo',json=wrong).status_code==422


def test_packaged_synthetic_word_design_prefills_pallet_dimensions_and_operations():
    from pathlib import Path
    data=Path(__file__).resolve().parents[1].joinpath('data','SYNTHETIC_DESIGN_REQUIREMENTS.docx').read_bytes()
    r=request('POST','/api/projects',username='estimator',json={
        'customer':'Fictional pallet buyer','title':'Synthetic sample pallet',
        'product_code':'fabricated_pallet','quote_workflow':'equipment_supply'})
    assert r.status_code==200,r.text
    pid=r.json()['project']['id']
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',files={'file':
        ('SYNTHETIC_DESIGN_REQUIREMENTS.docx',data,
         'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert r.status_code==200,r.text
    requirements={x['key']:x for x in r.json()['requirements']}
    for key,value in [('length_mm','1100'),('width_mm','550'),('height_mm','750')]:
        assert requirements[key]['value']==value
        assert requirements[key]['status']=='PENDING'
        assert requirements[key]['confidence_score']<100
        assert 'SYNTHETIC_DESIGN_REQUIREMENTS.docx' in requirements[key]['evidence']
    ops={x['code']:x for x in r.json()['documents'][0]['candidates'] if x['kind']=='operation'}
    assert {'cut','weld','paint','inspect'}<=set(ops)
    assert all(v['hours'] is None and v['rate'] is None for v in ops.values())
    # The new pallet follows the original sample's cost-plus workflow.
    assert r.json()['commercial'] is None
