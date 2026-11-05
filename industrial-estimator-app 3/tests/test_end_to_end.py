"""End-to-end API checks. Run with `python -m pytest -q` from project root.
Uses an isolated temporary database; no production records are altered.
"""
import os
import tempfile
from pathlib import Path

_TEMP=tempfile.TemporaryDirectory(prefix='industrial_quote_tests_')
os.environ['DATABASE_URL']='sqlite:///'+str(Path(_TEMP.name)/'test.db')
os.environ['PRIVATE_DIR']=str(Path(_TEMP.name)/'private')
os.environ['APP_SECRET']='TEST_KEY_DO_NOT_USE_IN_PRODUCTION_0123456789'

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import select
from backend.app import app,SessionLocal,User,Project,Price,Requirement,Document,Approval,IssuedQuote
from backend.seed import load_defaults

load_defaults(demo=True)
client=TestClient(app)


def token(username='demo'):
    r=client.post('/api/auth/login',json={'username':username,'password':'demo-pass-123'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}


def request(method,url,username='demo',**kwargs):
    return client.request(method,url,headers=token(username),**kwargs)


def make_pdf():
    from io import BytesIO
    b=BytesIO();c=canvas.Canvas(b);c.drawString(70,760,'TESTED PALLET');c.drawString(70,725,'Length: 1100 mm');c.drawString(70,700,'Width: 550 mm');c.drawString(70,675,'Height: 750 mm');c.drawString(70,650,'SQ TUBE 40X40X3MM');c.save();return b.getvalue()


def sample_project(code='general_fabrication'):
    r=request('POST','/api/projects',json={'customer':'Example Manufacturing','title':'Test fixture','product_code':code},username='estimator')
    assert r.status_code==200,r.text
    return r.json()['project']['id']


def get(pid):
    r=request('GET',f'/api/projects/{pid}')
    assert r.status_code==200,r.text
    return r.json()


def update_req(pid,key,value):
    r=request('PUT',f'/api/projects/{pid}/requirements/{key}',username='estimator',json={'value':value,'evidence':'Checked against an engineer-approved reference'})
    assert r.status_code==200,r.text
    r=request('POST',f'/api/projects/{pid}/requirements/{key}/approve',username='engineer')
    assert r.status_code==200,r.text


def create_ready_project():
    pid=sample_project()
    update_req(pid,'job_specification','Approved fabrication instruction')
    update_req(pid,'drawing_revision','REV-A')
    r=request('POST',f'/api/projects/{pid}/bom',username='estimator',json={'sku':'FLAT-40-8','qty':'10','unit':'m','waste_pct':'5','note':'Verified cut list','status':'ASSUMED'})
    assert r.status_code==200,r.text
    bid=r.json()['bom'][0]['id']
    r=request('POST',f'/api/projects/{pid}/bom/{bid}/approve',username='engineer',json={'source_reference':'Approved synthetic cutting list Rev A', 'verification_note':'Checked all bar lengths and the count against fabrication takeoff'});assert r.status_code==200,r.text
    r=request('POST',f'/api/projects/{pid}/operations',username='estimator',json={'code':'cut','description':'Cut steel','hours':'3','rate':'500','status':'ASSUMED'});assert r.status_code==200,r.text
    oid=r.json()['operations'][0]['id']
    r=request('POST',f'/api/projects/{pid}/operations/{oid}/approve',username='procurement');assert r.status_code==200,r.text
    # Establish an explicitly approved rate for this test fixture only.
    price=next(x for x in request('GET','/api/prices').json() if x['sku']=='FLAT-40-8')
    r=request('PUT','/api/prices/FLAT-40-8',username='procurement',json={**{k:price[k] for k in ('sku','description','rate','unit','source','vendor','url','valid_until','profile')},'status':'SUPPLIER_APPROVED','vendor':'Fixture Materials Vendor','source':'Confirmed test quotation','valid_until':'2099-12-31'})
    assert r.status_code==200,r.text
    return pid,bid,oid


def configure_costplus_quotation(pid, *, contact='Ms. Synthetic Buyer'):
    detail=get(pid)
    profile=detail['quotation']['profile']
    terms={**profile['terms'], 'customer_attention':contact,
           'customer_address':'Example customer facility',
           'delivery':'After approved purchase order',
           'payment':'Within 30 days of invoice'}
    result=request('PUT',f'/api/projects/{pid}/quotation',username='commercial',json={
      'terms':terms,'tax_config':{'mode':'EXCLUSIVE','status':'APPROVED',
       'components':[], 'basis_note':'Synthetic accounting review, no tax assumption'}})
    assert result.status_code==200,result.text


def approve_all(pid):
    for kind,user in [('engineering','engineer'),('pricing','procurement'),('commercial','commercial')]:
        r=request('POST',f'/api/projects/{pid}/approve/{kind}',username=user,json={'note':'Validated test fixture'})
        assert r.status_code==200,(kind,r.text)


def test_health_and_auth():
    assert client.get('/api/health').json()['status']=='ok'
    assert client.get('/api/prices').status_code==401
    assert client.post('/api/auth/login',json={'username':'demo','password':'incorrect'}).status_code==401
    assert request('GET','/api/configs').status_code==200


def test_product_config_and_sample_projects():
    configs=request('GET','/api/configs').json()
    assert {'fabricated_pallet','belt_conveyor','eot_crane','general_fabrication'} <= {c['product_type'] for c in configs}
    rows=request('GET','/api/projects').json()
    assert any(x['ref']=='PALLET-PROOF-001' for x in rows)
    pallet=next(x for x in rows if x['ref']=='PALLET-PROOF-001')
    detail=get(pallet['id'])
    assert detail['estimate']['material_cost']!='0.00'
    assert not detail['gates']['firm_ready']
    assert detail['gates']['missing_fields']


def test_configurable_new_family():
    data={'code':'rack_fixture','label':'Storage Rack','required_fields':[{'key':'rack_height_mm','label':'Height','unit':'mm','firm_required':True}],'allowed_components':[],'required_operations':['cut','weld'],'requires_document':False}
    r=request('POST','/api/configs',json=data)
    assert r.status_code==200,r.text
    pid=sample_project('rack_fixture')
    assert get(pid)['requirements'][0]['key']=='rack_height_mm'
    assert request('POST','/api/configs',json=data).status_code==409


def test_pdf_extract_and_private_access():
    pid=sample_project('fabricated_pallet')
    b=make_pdf()
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',files={'file':('example.pdf',b,'application/pdf')})
    assert r.status_code==200,r.text
    doc=r.json()['documents'][0]
    assert any(x.get('sku')=='SHS-40-40-3' for x in doc['candidates'])
    assert any(x.get('key')=='length_mm' and x['value']=='1100' for x in doc['candidates'])
    assert client.get(f'/api/projects/{pid}/documents/{doc["id"]}/file').status_code==401
    assert request('GET',f'/api/projects/{pid}/documents/{doc["id"]}/file').content==b


def test_invalid_units_and_rate_provenance():
    pid=sample_project('general_fabrication')
    r=request('POST',f'/api/projects/{pid}/bom',username='estimator',json={'sku':'FLAT-40-8','qty':'1','unit':'each','status':'ASSUMED'})
    assert r.status_code==422  # Unsupported unit conversion must fail closed even in previews
    # Create must not allow estimator to forge APPROVED status.
    r=request('POST',f'/api/projects/{pid}/bom',username='estimator',json={'sku':'FLAT-40-8','qty':'1','unit':'m','status':'APPROVED'})
    assert r.status_code==403
    price=next(x for x in request('GET','/api/prices').json() if x['sku']=='FLAT-40-8')
    data={k:price[k] for k in ('sku','description','rate','unit','status','source','vendor','url','valid_until','profile')}
    assert request('PUT','/api/prices/FLAT-40-8',username='estimator',json=data).status_code==403


def test_release_and_immutable_pdf():
    pid,_,_=create_ready_project()
    configure_costplus_quotation(pid)
    d=get(pid)
    assert not d['gates']['firm_ready']
    assert request('POST',f'/api/projects/{pid}/issue',username='commercial').status_code==409
    preview=request('GET',f'/api/projects/{pid}/preview.pdf').content
    assert preview.startswith(b'%PDF')
    word=request('GET',f'/api/projects/{pid}/quotation/preview.docx').content
    assert word.startswith(b'PK')
    approve_all(pid)
    assert get(pid)['gates']['firm_ready']
    r=request('POST',f'/api/projects/{pid}/issue',username='commercial')
    assert r.status_code==200,r.text
    i=r.json()['issues'][0]
    b=request('GET',f'/api/projects/{pid}/issued/{i["id"]}.pdf').content
    assert i['has_docx']
    frozen_word=request('GET',f'/api/projects/{pid}/issued/{i["id"]}.docx').content
    assert frozen_word.startswith(b'PK')
    assert b.startswith(b'%PDF') and len(b)>1500
    # Changing rates MUST invalidate approvals but not the issued historical PDF.
    price=next(x for x in request('GET','/api/prices').json() if x['sku']=='FLAT-40-8')
    r=request('PUT','/api/prices/FLAT-40-8',username='procurement',json={**{k:price[k] for k in ('sku','description','unit','source','vendor','url','valid_until','profile','status')},'rate':'99'})
    assert r.status_code==200,r.text
    updated=get(pid)
    assert not updated['gates']['firm_ready']
    assert updated['estimate']['order_value']!=d['estimate']['order_value']
    assert request('POST',f'/api/projects/{pid}/issue',username='commercial').status_code==409
    assert request('GET',f'/api/projects/{pid}/issued/{i["id"]}.pdf').content==b
    assert request('GET',f'/api/projects/{pid}/issued/{i["id"]}.docx').content==frozen_word


def test_approval_role_separation():
    pid,_,_=create_ready_project()
    assert request('POST',f'/api/projects/{pid}/approve/engineering',username='estimator',json={'note':'attempt'}).status_code==403
    r=request('POST',f'/api/projects/{pid}/approve/engineering',username='engineer',json={'note':'verified'})
    assert r.status_code==200
    r=request('POST',f'/api/projects/{pid}/approve/commercial',username='commercial',json={'note':'attempt before pricing'})
    assert r.status_code==409


def test_malformed_pdf_and_file_size():
    pid=sample_project()
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',files={'file':('bad.pdf',b'not-a-pdf','application/pdf')})
    assert r.status_code==422
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',files={'file':('bad.exe',b'x','application/octet-stream')})
    assert r.status_code==415


def test_csv_bom_import_unapproved():
    pid=sample_project('general_fabrication')
    csv_data=b'sku,qty,unit,waste_pct,note\nFLAT-40-8,10,m,5,Pending engineer check\n'
    r=request('POST',f'/api/projects/{pid}/bom/import',username='estimator',files={'file':('bom.csv',csv_data,'text/csv')})
    assert r.status_code==200,r.text
    d=r.json();assert len(d['bom'])==1 and d['bom'][0]['status']=='ASSUMED'
    assert not d['gates']['quantities_approved']
    # Second invalid import must not persist any row.
    wrong=b'sku,qty,unit\nFLAT-40-8,1,each\n'
    r=request('POST',f'/api/projects/{pid}/bom/import',username='estimator',files={'file':('wrong.csv',wrong,'text/csv')})
    assert r.status_code==422
    assert len(get(pid)['bom'])==1
