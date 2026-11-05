"""Synthetic repeatable tests based on document *patterns*, not private customer files."""
import pytest
from io import BytesIO
from zipfile import ZipFile
from reportlab.pdfgen import canvas
from backend.extraction import extract_candidates, conflicts_from_docs, local_document_text
from tests.test_end_to_end import request, sample_project, get, update_req, token


def make_document(pages):
    buffer=BytesIO();can=canvas.Canvas(buffer)
    for i,content in enumerate(pages):
        y=760
        for line in content:
            can.drawString(70,y,line);y-=28
        can.showPage()
    can.save();return buffer.getvalue()


def test_rule_confidence_and_same_field_conflict():
    config={'required_fields':[{'key':'rail_span_m','label':'Rail Span','unit':'m','aliases':['Span'],'extraction_type':'number'}]}
    cs=extract_candidates(['SPAN 40 Mtr.','9 mtr Lift\n25 mtr Span'],config,[],'PDF')
    spans=[c for c in cs if c.get('key')=='rail_span_m']
    assert {c['value'] for c in spans}=={'40','25'}
    assert all(0<c['confidence_score']<100 and c['review_status']=='UNVERIFIED' for c in spans)
    d=[{'id':1,'original_name':'EXAMPLE.pdf','candidates':spans}]
    assert conflicts_from_docs(d)[0]['key']=='rail_span_m'


def test_quoted_40_25_conflict_requires_engineer():
    # Public examples are not bundled; this creates a wholly synthetic conflicting document.
    from backend.app import SessionLocal, ProductConfig
    from sqlalchemy import select
    with SessionLocal() as db:
        cfg=db.scalar(select(ProductConfig).where(ProductConfig.code=='eot_crane'))
        # Existing seeded config includes field aliases from JSON with source matching.
        assert cfg
    pid=sample_project('eot_crane')
    pdf=make_document([['SPAN 40 Mtr.','CAPACITY 40 Te','LIFT 9 Mtr.'],
        ['PRICE SCHEDULE','25 mtr Span','5,400,821 INR EXAMPLE PRICE']])
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',
       files={'file':('synthetic-conflict.pdf',pdf,'application/pdf')})
    assert r.status_code==200,r.text
    data=r.json()
    spans=[x for x in data['documents'][0]['candidates'] if x.get('key')=='rail_span_m']
    assert {x['value'] for x in spans}=={'40','25'}
    assert any(x['key']=='rail_span_m' for x in data['extraction_conflicts'])
    span_req=next(x for x in data['requirements'] if x['key']=='rail_span_m')
    assert span_req['value']=='' and span_req['confidence_score'] is None
    assert not data['commercial']['gates']['firm_ready'] if data['commercial'] else True
    # No source score itself can make the requirement APPROVED.
    assert all(r['status']=='PENDING' for r in data['requirements'])


def test_service_quote_no_bom_gst_and_immutable_pdf():
    pid=sample_project('generic_service')
    r=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',
       json={'workflow':'service_repair'})
    assert r.status_code==200,r.text
    for description,price in [('Motor rewind incl. rotor and shaft work','39500'),
                              ('Motor removal and refit','6000')]:
        x=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
          'description':description,'mode':'FIXED','price':price,'qty':'1','unit':'each','tax_applicable':True})
        assert x.status_code==200,x.text
    r=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
      'description':'Nested breakdown: rewinding 21500, rotor 16000, shaft 2000',
      'mode':'NOTE','qty':'','unit':'each','price':'','tax_applicable':False})
    assert r.status_code==200,r.text
    terms={'customer_attention':'Mr. Test Repair Contact','scope':'Repair a customer-provided hoist motor','delivery':'As agreed after inspection',
      'payment':'Immediate after completion','warranty':'Subject to agreed repair scope'}
    tax={'mode':'EXCLUSIVE','status':'APPROVED','components':[{'name':'CGST','rate':'9'},{'name':'SGST','rate':'9'}],
      'basis_note':'Confirmed in test by authorized commercial reviewer; not live legal advice'}
    r=request('PUT',f'/api/projects/{pid}/commercial',username='commercial',json={'terms':terms,'tax_config':tax})
    assert r.status_code==200,r.text
    prices=r.json()['pricing']
    assert prices['subtotal_known']=='45500.00'
    assert prices['tax_components']==[{'name':'CGST','rate':'9','amount':'4095.00'},
                                       {'name':'SGST','rate':'9','amount':'4095.00'}]
    assert prices['known_total_including_tax']=='53690.00'
    assert prices['grand_total_definitive']
    assert not r.json()['gates']['firm_ready']
    preview=request('GET',f'/api/projects/{pid}/commercial/preview.pdf').content
    assert preview.startswith(b'%PDF')
    assert request('POST',f'/api/projects/{pid}/commercial/issue',username='commercial').status_code==409
    assert request('POST',f'/api/projects/{pid}/commercial/approve/pricing',username='procurement').status_code==200
    assert request('POST',f'/api/projects/{pid}/commercial/approve/commercial',username='commercial').status_code==200
    assert request('POST',f'/api/projects/{pid}/commercial/issue',username='commercial').status_code==200
    detail=get(pid);assert detail['issues']
    issue=detail['issues'][0];blob=request('GET',f'/api/projects/{pid}/issued/{issue["id"]}.pdf').content
    assert blob.startswith(b'%PDF')
    rows=detail['commercial']['pricing']['lines']
    first=rows[0]
    change={k:first[k] for k in ('description','mode','qty','unit','price','ordinal','tax_applicable','tax_code','parent_id','notes')}
    change['price']='40000'
    assert request('PUT',f'/api/projects/{pid}/commercial/lines/{first["id"]}',username='estimator',json=change).status_code==200
    after=get(pid)
    assert not after['commercial']['gates']['firm_ready']
    assert request('GET',f'/api/projects/{pid}/issued/{issue["id"]}.pdf').content==blob


def test_line_modes_partial_totals():
    pid=sample_project('generic_service')
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'general_sale'}).status_code==200
    rows=[('Complete machine','FIXED','5400821',''),('Rail with fixing','UNIT_RATE','2675',''),
        ('Cable line with fixing','UNIT_RATE','2200',''),('Commissioning','FIXED','50000',''),('Gantry girder','FIXED','3192720',''),
        ('Transport','AT_ACTUAL','','')]
    for label,mode,price,qty in rows:
        r=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
           'description':label,'mode':mode,'price':price,'qty':qty,'unit':'m'})
        assert r.status_code==200,r.text
    c=get(pid)['commercial']['pricing']
    assert c['subtotal_known']=='8643541.00'
    assert len(c['unpriced_lines'])==2
    assert c['additional_at_actual']==['Transport']
    assert not c['grand_total_definitive']
    assert not get(pid)['commercial']['gates']['firm_ready']


def test_docx_local_no_cloud_no_fake_page_numbers():
    # A valid small DOCX archive whose words are in table/paragraph XML.
    xml=b'''<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>SPAN</w:t></w:r></w:p><w:p><w:r><w:t>8.6 Mtr.</w:t></w:r></w:p></w:body></w:document>'''
    stream=BytesIO()
    with ZipFile(stream,'w') as f:f.writestr('word/document.xml',xml)
    pages,kind=local_document_text('sample.docx',stream.getvalue())
    assert kind=='DOCX' and len(pages)==1
    config={'required_fields':[{'key':'rail_span_m','label':'Span','unit':'m'}]}
    matches=extract_candidates(pages,config,[],'DOCX')
    assert matches and matches[0]['value']=='8.6'
    assert 'logical section' in matches[0]['source_location']


def test_customer_price_schedule_must_match_reviewed_technical_dimensions():
    pid=sample_project('eot_crane')
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',
       json={'workflow':'equipment_supply'}).status_code==200
    update_req(pid,'rail_span_m','40')
    r=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
        'description':'Synthetic crane offered with 25 mtr Span',
        'mode':'FIXED','price':'5400821','qty':'1','unit':'each'})
    assert r.status_code==200,r.text
    findings=r.json()['quality_findings']
    assert any(x['key']=='rail_span_m' and x['expected']=='40' and x['observed']=='25' for x in findings)
    assert not r.json()['gates']['firm_ready']
    line=r.json()['pricing']['lines'][0]
    payload={k:line[k] for k in ('description','mode','price','qty','unit','ordinal','tax_applicable','tax_code','parent_id','notes')}
    payload['description']='Synthetic crane offered with 40 mtr Span'
    updated=request('PUT',f'/api/projects/{pid}/commercial/lines/{line["id"]}',username='estimator',json=payload)
    assert updated.status_code==200,updated.text
    assert not updated.json()['quality_findings']


def test_single_girder_offer_known_subtotal_and_actual_transport():
    pid=sample_project('generic_service')
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'general_sale'}).status_code==200
    for desc,mode,price in [('Synthetic 5-ton machine, 8.6 m span','FIXED','850000'),
                            ('Erection and commissioning','FIXED','25000'),
                            ('Transportation at actual','AT_ACTUAL','')]:
        r=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
            'description':desc,'mode':mode,'price':price,'qty':'1' if mode=='FIXED' else '', 'unit':'each'})
        assert r.status_code==200,r.text
    calc=get(pid)['commercial']['pricing']
    assert calc['subtotal_known']=='875000.00'
    assert not calc['grand_total_definitive']
    assert calc['additional_at_actual']==['Transportation at actual']
