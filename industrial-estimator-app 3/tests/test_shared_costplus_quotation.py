"""Regression: one cost-plus estimation path AND shared quotation features."""
from io import BytesIO
from decimal import Decimal
from docx import Document as WordDocument
from pypdf import PdfReader
from tests.test_end_to_end import (request,get,sample_project,create_ready_project,
    configure_costplus_quotation,approve_all)


def _alltext(word):
    doc=WordDocument(BytesIO(word))
    return '\n'.join(p.text for p in doc.paragraphs)+'\n'+'\n'.join(
        '|'.join(c.text for c in r.cells) for t in doc.tables for r in t.rows)


def _pdftext(raw):
    return '\n'.join(p.extract_text() for p in PdfReader(BytesIO(raw)).pages)


def test_every_new_project_exposes_costplus_and_shared_quotation():
    for code in ('fabricated_pallet','eot_crane','belt_conveyor','general_fabrication','generic_service'):
        pid=sample_project(code)
        d=get(pid)
        assert d['commercial'] is None
        assert d['quotation']['profile']['branding']['name']=='YASH ENGINEERING'
        assert d['quotation']['pricing']['subtotal_known']==d['estimate']['order_value']
        assert d['quotation']['pricing']['lines'][0]['line_total']==d['estimate']['order_value']
        assert d['quotation']['profile']['template']
        assert d['gates']['pricing_approved'] is False
        assert d['quotation']['gates']['customer_contact_confirmed'] is False
        assert next(x for x in request('GET','/api/projects').json() if x['id']==pid)['firm_ready'] is False
        assert request('GET',f'/api/projects/{pid}/quotation/preview.pdf').status_code==409
        assert request('GET',f'/api/projects/{pid}/quotation/preview.docx').status_code==409


def test_seeded_costplus_sample_has_identical_quotation_controls():
    seeded=next(x for x in request('GET','/api/projects').json() if x['ref']=='PALLET-PROOF-001')
    detail=get(seeded['id'])
    assert detail['commercial'] is None and detail['quotation'] is not None
    assert detail['quotation']['pricing']['subtotal_known']==detail['estimate']['order_value']
    assert detail['bom'] and detail['operations']


def test_named_contact_units_tax_template_and_snapshot_roundtrip():
    pid,_,_=create_ready_project()
    d=get(pid)
    assert d['quotation']['profile']['template']
    old_cost=d['estimate']['total_cost'];old_order=d['estimate']['order_value']
    term={**d['quotation']['profile']['terms'],
          'customer_attention':'Ms. Costplus Recipient',
          'customer_address':'Customer Unit 9, Industrial Park',
          'product_unit':'Pair',
          'quotation_line_description':'Fabrication per customer-approved scope',
          'delivery':'After production and inspection',
          'payment':'Within 30 days'}
    tax={'mode':'EXCLUSIVE','status':'APPROVED','basis_note':'Accountant-reviewed synthetic test basis',
         'components':[{'name':'CGST','rate':'9'}, {'name':'SGST','rate':'9'}]}
    assert request('PUT',f'/api/projects/{pid}/quotation',username='estimator',json={
       'terms':term, 'tax_config':tax}).status_code==403  # Estimator cannot approve tax.
    r=request('PUT',f'/api/projects/{pid}/quotation',username='commercial',json={
       'terms':term,'tax_config':tax})
    assert r.status_code==200,r.text
    state=r.json()
    assert state['pricing']['lines'][0]['qty']=='1'
    assert state['pricing']['lines'][0]['unit']=='Pair'
    assert state['pricing']['subtotal_known']==old_order
    assert get(pid)['estimate']['total_cost']==old_cost
    assert state['pricing']['tax_components'][0]['amount']==str(
        (Decimal(old_order)*Decimal('0.09')).quantize(Decimal('.01')))
    pdf=request('GET',f'/api/projects/{pid}/quotation/preview.pdf')
    docx=request('GET',f'/api/projects/{pid}/quotation/preview.docx')
    assert pdf.status_code==200,pdf.text if pdf.status_code!=200 else ''
    assert docx.status_code==200,docx.text if docx.status_code!=200 else ''
    assert len(PdfReader(BytesIO(pdf.content)).pages)==1
    assert 'YASH ENGINEERING' in _pdftext(pdf.content)
    for blob in (_pdftext(pdf.content),_alltext(docx.content)):
        assert 'Ms. Costplus Recipient' in blob
        assert 'Fabrication per customer-approved scope' in blob
        assert 'Purchase Team' not in blob
    assert 'PAIR' in _pdftext(pdf.content)  # Quote 73's uppercase unit style
    assert 'Pair' in _alltext(docx.content)
    assert not state['gates']['firm_ready']  # Tax alone is not release approval.
    approve_all(pid)
    assert get(pid)['quotation']['gates']['firm_ready']
    issued=request('POST',f'/api/projects/{pid}/issue',username='commercial')
    assert issued.status_code==200,issued.text
    frozen=issued.json()['issues'][0]
    assert frozen['has_docx']
    before_pdf=request('GET',f'/api/projects/{pid}/issued/{frozen["id"]}.pdf').content
    before_docx=request('GET',f'/api/projects/{pid}/issued/{frozen["id"]}.docx').content
    assert 'Ms. Costplus Recipient' in _pdftext(before_pdf)
    assert 'Ms. Costplus Recipient' in _alltext(before_docx)
    new_terms={**get(pid)['quotation']['profile']['terms'],
               'customer_attention':'Mr. New Recipient'}
    update=request('PUT',f'/api/projects/{pid}/quotation',username='estimator',json={'terms':new_terms})
    assert update.status_code==200,update.text
    assert not get(pid)['gates']['firm_ready']
    assert request('POST',f'/api/projects/{pid}/issue',username='commercial').status_code==409
    assert request('GET',f'/api/projects/{pid}/issued/{frozen["id"]}.pdf').content==before_pdf
    assert request('GET',f'/api/projects/{pid}/issued/{frozen["id"]}.docx').content==before_docx


def test_switch_quotation_format_does_not_change_estimation_workflow():
    pid=sample_project('eot_crane')
    d=get(pid)
    before=d['estimate']['order_value']
    result=request('PUT',f'/api/projects/{pid}/quotation',username='estimator',json={
      'template':'short_service', 'terms':{**d['quotation']['profile']['terms'],
      'customer_attention':'Mr. Synthetic Engineer'}})
    assert result.status_code==200,result.text
    d=get(pid)
    assert d['commercial'] is None
    assert d['quotation']['profile']['template']=='short_service'
    assert d['estimate']['order_value']==before
    assert request('GET',f'/api/projects/{pid}/quotation/preview.pdf').status_code==200
    assert request('GET',f'/api/projects/{pid}/quotation/preview.docx').status_code==200


def test_invalid_contact_or_unit_does_not_overwrite_saved_settings():
    pid=sample_project()
    previous=get(pid)['quotation']['profile']['terms']
    for value in ('Purchase Team','Procurement Department'):
        bad=request('PUT',f'/api/projects/{pid}/quotation',username='estimator',json={
           'terms':{**previous,'customer_attention':value}})
        assert bad.status_code==422
    invalid=request('PUT',f'/api/projects/{pid}/quotation',username='estimator',json={
       'terms':{**previous,'product_unit':'Nos. <script>'}})
    assert invalid.status_code==422
    assert get(pid)['quotation']['profile']['terms']==previous
