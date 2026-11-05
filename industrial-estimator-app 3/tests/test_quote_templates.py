"""Admin-managed quotation layout library regression tests (synthetic data only)."""
import json
import uuid
from io import BytesIO

from pypdf import PdfReader

from tests.test_end_to_end import get, request, sample_project


def payload(name='custom_template'):
    code=name+'_'+uuid.uuid4().hex[:7]
    return {'code':code,'name':'Custom Test Quotation','workflow':'service_repair',
        'layout':{'title':'BESPOKE REPAIR OFFER','tagline':'Testing data only',
          'primary_color':'#152F42','accent_color':'#087E75',
          'intro':'For project {project} of {customer}',
          'closing':'Thank you for your enquiry','footer':'Controlled synthetic template',
          'sections':[{'key':'pricing','title':'LABOUR AND MATERIALS','enabled':True},
                      {'key':'terms','title':'PAYMENT AND DELIVERY','enabled':True},
                      {'key':'certifications','title':'SUPPORTING NOTES','enabled':False}]}}


def test_builtin_templates_available_and_accessible():
    rows=request('GET','/api/quote-templates').json()
    assert {'multi_annexure','short_service','simple_sales'}<={x['code'] for x in rows}
    assert {x['workflow'] for x in rows if x['is_default']}=={'equipment_supply','service_repair','general_sale'}
    for x in rows:
        pdf=request('GET',f'/api/quote-templates/{x["code"]}/preview.pdf').content
        assert pdf.startswith(b'%PDF') and len(pdf)>1000
    assert request('POST','/api/quote-templates',username='estimator',json=payload()).status_code==403
    assert request('PUT','/api/quote-templates/multi_annexure',json={'name':'Changed','layout':payload()['layout']}).status_code==403


def test_custom_template_crud_preview_and_version():
    body=payload()
    created=request('POST','/api/quote-templates',username='demo',json=body)
    assert created.status_code==200,created.text
    assert created.json()['version']==1 and not created.json()['is_builtin']
    filename=body['code']
    export=request('GET',f'/api/quote-templates/{filename}/export.json')
    assert export.status_code==200
    assert json.loads(export.content)['layout']['title']=='BESPOKE REPAIR OFFER'
    pdf=request('GET',f'/api/quote-templates/{filename}/preview.pdf').content
    assert 'BESPOKE REPAIR OFFER' in PdfReader(BytesIO(pdf)).pages[0].extract_text()
    newer={**body['layout'],'title':'UPDATED INDUSTRIAL REPAIR OFFER'}
    updated=request('PUT',f'/api/quote-templates/{filename}',username='demo',json={'name':'Revised design','layout':newer})
    assert updated.status_code==200,updated.text
    assert updated.json()['version']==2
    history=request('GET',f'/api/quote-templates/{filename}/history').json()
    assert history['past_versions'][0]['version']==1
    assert history['past_versions'][0]['layout']['title']=='BESPOKE REPAIR OFFER'
    assert 'UPDATED INDUSTRIAL REPAIR OFFER' in PdfReader(BytesIO(request('GET',f'/api/quote-templates/{filename}/preview.pdf').content)).pages[0].extract_text()


def test_json_import_and_validation():
    body=payload('imported')
    upload=request('POST','/api/quote-templates/import',username='demo',
       files={'file':('template.json',json.dumps(body).encode(),'application/json')})
    assert upload.status_code==200,upload.text
    assert upload.json()['code']==body['code']
    untrusted=payload('badscript')
    untrusted['layout']['evil_js']='<script>alert(1)</script>'
    blocked=request('POST','/api/quote-templates',username='demo',json=untrusted)
    assert blocked.status_code==422
    invalid=payload('nosale');invalid['layout']['sections']=[{'key':'pricing','title':'Only prices','enabled':True}]
    assert request('POST','/api/quote-templates',username='demo',json=invalid).status_code==422
    huge=b'{' + b' ' * 32000 + b'}'
    assert request('POST','/api/quote-templates/import',username='demo',
       files={'file':('large.json',huge,'application/json')}).status_code==413
    assert request('POST','/api/quote-templates/import',username='estimator',
       files={'file':('template.json',json.dumps(payload('forbidden')).encode(),'application/json')}).status_code==403


def test_template_default_selection_and_quote_binding():
    data=payload('setdefault')
    resp=request('POST','/api/quote-templates',username='demo',json=data)
    assert resp.status_code==200
    assigned=request('POST',f'/api/quote-templates/{data["code"]}/default',username='demo')
    assert assigned.status_code==200
    assert assigned.json()['default']['is_default'] is True
    pid=sample_project('generic_service')
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'service_repair'}).status_code==200
    assert get(pid)['commercial']['profile']['template']==data['code']
    # Workflow binding blocks selecting an equipment template in service quote.
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',
       json={'template':'multi_annexure'}).status_code==422
    current=get(pid)['commercial']['profile']['terms']
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'terms':{**current,'customer_attention':'Ms. Sample Buyer'}}).status_code==200
    quote=request('GET',f'/api/projects/{pid}/commercial/preview.pdf')
    assert quote.status_code==200
    text=PdfReader(BytesIO(quote.content)).pages[0].extract_text()
    assert 'BESPOKE REPAIR OFFER' in text
    # Template definition is part of quotation fingerprint; admin updates invalidate approvals.
    fp=get(pid)['commercial']['gates']['fingerprint']
    changed={**data['layout'],'closing':'Changed terms of the PDF template'}
    assert request('PUT',f'/api/quote-templates/{data["code"]}',username='demo',json={
       'name':'Custom default','layout':changed}).status_code==200
    assert get(pid)['commercial']['gates']['fingerprint']!=fp
    # Default is specific to service workflow.
    eq=next(x for x in request('GET','/api/quote-templates').json() if x['code']=='multi_annexure')
    assert eq['is_default'] is False
    assert next(x for x in request('GET','/api/quote-templates').json() if x['code']=='quote73_equipment')['is_default'] is True


def test_custom_template_preserves_issued_quote_snapshot():
    data=payload('issued')
    assert request('POST','/api/quote-templates',username='demo',json=data).status_code==200
    pid=sample_project('generic_service')
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'service_repair','template':data['code']}).status_code==200
    assert request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
       'description':'Repair labour','mode':'FIXED','price':'1000','qty':'1','unit':'each'}).status_code==200
    assert request('PUT',f'/api/projects/{pid}/commercial',username='commercial',json={
       'terms':{'customer_attention':'Mr. Fixture Contact','scope':'Service test','payment':'Payment after completion','delivery':'Two days after confirmation'},
       'tax_config':{'mode':'EXCLUSIVE','status':'APPROVED','components':[],
                     'basis_note':'Validated zero-tax synthetic test scenario'}}).status_code==200
    assert request('POST',f'/api/projects/{pid}/commercial/approve/pricing',username='procurement').status_code==200
    assert request('POST',f'/api/projects/{pid}/commercial/approve/commercial',username='commercial').status_code==200
    assert get(pid)['commercial']['gates']['firm_ready']
    assert request('POST',f'/api/projects/{pid}/commercial/issue',username='commercial').status_code==200
    item=get(pid)['issues'][0]
    frozen=request('GET',f'/api/projects/{pid}/issued/{item["id"]}.pdf').content
    assert b'%PDF' in frozen[:4]
    change={**data['layout'],'title':'CHANGE AFTER ISSUING'}
    assert request('PUT',f'/api/quote-templates/{data["code"]}',username='demo',json={
       'name':'Changed issued layout','layout':change}).status_code==200
    assert not get(pid)['commercial']['gates']['firm_ready']
    assert request('GET',f'/api/projects/{pid}/issued/{item["id"]}.pdf').content==frozen
