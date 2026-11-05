"""Regression tests for standalone company white labelling, UOM and reference alignment.

One deployment contains one company. The same application can be installed with
separate database/file storage for each manufacturer; cross-tenant operations
are deliberately NOT claimed or implemented here.
"""
from io import BytesIO
import re
import fitz
from docx import Document as WordDocument
from docx.enum.text import WD_TAB_ALIGNMENT
from tests.test_end_to_end import request, sample_project, get
from backend.word_quote_templates import safe_docx


def _company():
    r=request('GET','/api/company-profile')
    assert r.status_code==200,r.text
    return r.json()


def _set_company(values,username='demo'):
    return request('PUT','/api/company-profile',username=username,json=values)


def _quote(workflow='general_sale'):
    pid=sample_project('generic_service')
    result=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':workflow})
    assert result.status_code==200,result.text
    return pid


def _contact(pid,name='Ms. Test Customer'):
    old=get(pid)['commercial']['profile']['terms']
    r=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={
        'terms':{**old,'customer_attention':name,'customer_address':'Sample buyer site'}})
    assert r.status_code==200,r.text


def test_company_settings_are_admin_controlled_and_persisted_for_future_projects():
    saved=_company()
    changed={**saved,'quote_prefix':'ACME','branding':{**saved['branding'],
        'name':'ACME FABRICATION PRIVATE LIMITED','heading':'',
        'address':'Sample factory, Industrial Estate','works_address':'Workshop 4',
        'gstin':'TEST-TAX-ID-01','signature_title':'Authorised Signatory',
        'contact':'sales@acme.example'}}
    changed['units']=['Nos.','Set','kg','m','sq ft','Pair','job','litre']
    before=_quote()
    original=get(before)['commercial']['profile']['branding']
    try:
        assert _set_company(changed,username='estimator').status_code==403
        r=_set_company(changed)
        assert r.status_code==200,r.text
        assert _company()['branding']['name']==changed['branding']['name']
        assert _company()['quote_prefix']=='ACME'
        after=_quote()
        state=get(after)
        assert state['project']['ref'].startswith('ACME-')
        brand=state['commercial']['profile']['branding']
        assert brand['name']=='ACME FABRICATION PRIVATE LIMITED'
        assert brand['gstin']=='TEST-TAX-ID-01'
        assert brand['heading']==''
        # Existing projects stay under previously captured seller details until explicitly refreshed.
        assert get(before)['commercial']['profile']['branding']==original
        _contact(after)
        pdf=request('GET',f'/api/projects/{after}/commercial/preview.pdf').content
        word=request('GET',f'/api/projects/{after}/commercial/preview.docx').content
        assert b'%PDF'==pdf[:4] and word.startswith(b'PK')
        pdftext=fitz.open(stream=pdf,filetype='pdf')[0].get_text()
        assert 'ACME FABRICATION PRIVATE LIMITED' in pdftext
        assert 'YASH ENGINEERING' not in pdftext
        worddoc=WordDocument(BytesIO(word))
        blob='\n'.join(c.text for t in worddoc.tables for row in t.rows for c in row.cells)
        assert 'ACME FABRICATION PRIVATE LIMITED' in blob
        assert 'YASH ENGINEERING' not in blob
        refreshed=request('POST',f'/api/projects/{before}/commercial/apply-company-profile',username='estimator')
        assert refreshed.status_code==200,refreshed.text
        assert get(before)['commercial']['profile']['branding']['name']=='ACME FABRICATION PRIVATE LIMITED'
    finally:
        restore={k:saved[k] for k in ('branding','quote_prefix','units')}
        r=_set_company(restore)
        assert r.status_code==200,r.text


def test_rejects_invalid_company_profile_and_unit_catalog():
    old=_company()
    basic={k:old[k] for k in ('branding','quote_prefix','units')}
    assert _set_company({**basic,'quote_prefix':'../../'}).status_code==422
    assert _set_company({**basic,'units':['kg','bad\nunit']}).status_code==422
    assert _set_company({**basic,'branding':{**old['branding'],'name':''}}).status_code==422


def test_multiple_quantity_units_decimal_arithmetic_and_pdf_rendering():
    pid=_quote('general_sale')
    _contact(pid)
    for i,(u,qty,rate) in enumerate([('Set','3','100'),('m2','2.5','123.40'),('Pair','1.25','80.0'),('sq ft','10','2')],1):
        r=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
           'description':f'Item {i}: customer charge','mode':'UNIT_RATE','qty':qty,'unit':u,
           'price':rate,'ordinal':i*10,'tax_applicable':True})
        assert r.status_code==200,r.text
    state=get(pid)['commercial']['pricing']
    expected=300+308.5+100+20
    assert state['subtotal_known']==f'{expected:.2f}',state['subtotal_known']
    assert [x['unit'] for x in state['lines']]==['Set','m2','Pair','sq ft']
    pdf=request('GET',f'/api/projects/{pid}/commercial/preview.pdf')
    assert pdf.status_code==200,pdf.text if pdf.status_code!=200 else ''
    text=fitz.open(stream=pdf.content,filetype='pdf')[0].get_text()
    for unit in ('Set','m2','Pair','sq ft'):
        assert unit.upper() in text.upper(),(unit,text)
    bad=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
        'description':'Unsupported markup','mode':'UNIT_RATE','qty':'2','unit':'<script>','price':'5'})
    assert bad.status_code==422
    badfixed=request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
        'description':'Misleading fixed item','mode':'FIXED','qty':'2','unit':'Set','price':'100'})
    assert badfixed.status_code==422


def test_quote_reference_is_on_the_right_in_pdf_and_word():
    pid=_quote('general_sale')
    _contact(pid)
    profile=get(pid)['commercial']['profile']
    r=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={
        'external_reference':'TEST-73/EX','terms':profile['terms']})
    assert r.status_code==200,r.text
    pdf=request('GET',f'/api/projects/{pid}/commercial/preview.pdf')
    assert pdf.status_code==200,pdf.text
    doc=fitz.open(stream=pdf.content,filetype='pdf')
    boxes=[]
    for block in doc[0].get_text('dict')['blocks']:
        for line in block.get('lines',[]):
            text=''.join(s['text'] for s in line['spans'])
            if 'Quot No.' in text:boxes.append(line['bbox'])
    assert len(boxes)==1,boxes
    # Same exact right edge as the original Quote 73 supplied by the user.
    assert abs(boxes[0][2]-390.9)<1.5,boxes
    assert boxes[0][0]>280,boxes
    raw=request('GET',f'/api/projects/{pid}/commercial/preview.docx').content
    word=WordDocument(BytesIO(raw))
    ref_paragraphs=[p for table in word.tables for row in table.rows for cell in row.cells for p in cell.paragraphs if 'Quot No.' in p.text]
    assert ref_paragraphs
    assert any(any(stop.alignment==WD_TAB_ALIGNMENT.RIGHT for stop in p.paragraph_format.tab_stops) for p in ref_paragraphs)


def test_unit_catalog_not_a_conversion_engine():
    # An unknown BOM/price unit is permitted only if EXACTLY compatible; the
    # estimate must reject conversions which we have not implemented.
    pid=sample_project('general_fabrication')
    price=request('POST','/api/prices',username='procurement',json={
        'sku':'TEST-LITRE','description':'Consumable supplied per litre','rate':'80','unit':'litre',
        'status':'DEMO_ASSUMPTION','source':'Testing only','profile':{}})
    assert price.status_code in (200,409),price.text
    matched=request('POST',f'/api/projects/{pid}/bom',username='estimator',json={
        'sku':'TEST-LITRE','qty':'2.5','unit':'litre','status':'ASSUMED'})
    assert matched.status_code==200,matched.text
    second_pid=sample_project('general_fabrication')
    wrong=request('POST',f'/api/projects/{second_pid}/bom',username='estimator',json={
        'sku':'TEST-LITRE','qty':'2500','unit':'ml','status':'ASSUMED'})
    assert wrong.status_code==422,wrong.text


def test_health_reflects_current_application_version():
    from backend.app import app
    health = request('GET', '/api/health')
    assert health.status_code == 200
    assert health.json()['version'] == app.version == '0.8.4-dev'
