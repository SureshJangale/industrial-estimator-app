"""Regression tests for Yash Engineering identity, required named contacts, paired PDF/DOCX."""
from io import BytesIO
from docx import Document as WordDocument
from pypdf import PdfReader
from tests.test_end_to_end import request,sample_project,get
from backend.company_defaults import YASH_BRANDING
from backend.commercial import upgrade_placeholder_seller_branding
from backend.app import SessionLocal
from backend.commercial import CommercialProfile
from sqlalchemy import select
import json


def create_quote(workflow='general_sale'):
    pid=sample_project('generic_service')
    assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':workflow}).status_code==200
    return pid


def apply_contact(pid,name='Mr. Amol Customer',address='Customer works, MIDC'):
    profile=get(pid)['commercial']['profile']
    terms={**profile['terms'],'customer_attention':name,'customer_address':address}
    return request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'terms':terms})


def word_text(blob):
    doc=WordDocument(BytesIO(blob))
    text='\n'.join(x.text for x in doc.paragraphs)
    for table in doc.tables:
        text+='\n'+'\n'.join(' | '.join(cell.text for cell in row.cells) for row in table.rows)
    return text


def pdf_text(blob):
    r=PdfReader(BytesIO(blob))
    return '\n'.join(p.extract_text() for p in r.pages)


def test_yash_is_default_on_new_quotations():
    pid=create_quote()
    brand=get(pid)['commercial']['profile']['branding']
    for key in ('name','address','works_address','gstin','contact','signature_title'):
        assert brand[key]==YASH_BRANDING[key]
    assert brand['name']=='YASH ENGINEERING' and brand['gstin']=='27JILPS1079H1ZL'
    assert get(pid)['commercial']['profile']['terms'].get('customer_attention') is None


def test_require_named_contact_and_never_copy_historical_contact():
    pid=create_quote()
    expected='Enter the customer contact PERSON'
    for ext in ('pdf','docx'):
        result=request('GET',f'/api/projects/{pid}/commercial/preview.{ext}')
        assert result.status_code==409
        assert expected in result.json()['detail']
    missing=request('POST',f'/api/projects/{pid}/commercial/issue',username='commercial')
    assert missing.status_code==409
    assert 'contact PERSON' in missing.json()['detail']
    for bad in ('Purchase Team','Purchasing team','Procurement Department','N/A'):
        reject=apply_contact(pid,bad)
        assert reject.status_code==422,(bad,reject.text)
    assert apply_contact(pid,'Mr. Customer Person').status_code==200
    assert get(pid)['commercial']['gates']['customer_contact_confirmed'] is True


def test_quote73_pdf_and_editable_docx_show_yash_and_named_contact():
    pid=create_quote()
    assert apply_contact(pid,'Ms. Renuka Buyer','Plot 7, Customer Industrial Park').status_code==200
    rawpdf=request('GET',f'/api/projects/{pid}/commercial/preview.pdf')
    assert rawpdf.status_code==200,rawpdf.text if rawpdf.status_code!=200 else ''
    rawword=request('GET',f'/api/projects/{pid}/commercial/preview.docx')
    assert rawword.status_code==200,rawword.text if rawword.status_code!=200 else ''
    assert rawpdf.content.startswith(b'%PDF') and rawword.content.startswith(b'PK')
    for text in (pdf_text(rawpdf.content),word_text(rawword.content)):
        assert 'YASH ENGINEERING' in text
        assert 'Ms. Renuka Buyer' in text
        assert 'Plot 7, Customer Industrial Park' in text
        assert 'Purchase Team' not in text
        assert 'Reliable Aototech' not in text
    pdf=PdfReader(BytesIO(rawpdf.content))
    assert len(pdf.pages)==1
    assert abs(float(pdf.pages[0].mediabox.width)-595.2)<1
    # New contact must change both generated docs and make prior approval fingerprint stale.
    old_fp=get(pid)['commercial']['gates']['fingerprint']
    assert apply_contact(pid,'Mr. Changed Recipient').status_code==200
    assert get(pid)['commercial']['gates']['fingerprint']!=old_fp
    pdf2=pdf_text(request('GET',f'/api/projects/{pid}/commercial/preview.pdf').content)
    word2=word_text(request('GET',f'/api/projects/{pid}/commercial/preview.docx').content)
    assert 'Mr. Changed Recipient' in pdf2 and 'Mr. Changed Recipient' in word2
    assert 'Ms. Renuka Buyer' not in pdf2 and 'Ms. Renuka Buyer' not in word2


def test_issued_pdf_and_word_are_frozen_together():
    pid=create_quote('service_repair')
    assert request('POST',f'/api/projects/{pid}/commercial/lines',username='estimator',json={
        'description':'Repair motor and restore function','mode':'FIXED','price':'1000','qty':'1',
        'unit':'job','tax_applicable':True}).status_code==200
    terms={**get(pid)['commercial']['profile']['terms'],'scope':'Service fixture',
        'payment':'Immediately after completion','delivery':'After inspection and authorization',
        'customer_attention':'Ms. Original Buyer','customer_address':'Customer plant (synthetic)'}
    assert request('PUT',f'/api/projects/{pid}/commercial',username='commercial',json={
        'terms':terms,'tax_config':{'mode':'EXCLUSIVE','status':'APPROVED','components':[],
            'basis_note':'Approved synthetic zero-tax fixture, not a live tax policy'}}).status_code==200
    for kind,actor in [('pricing','procurement'),('commercial','commercial')]:
        r=request('POST',f'/api/projects/{pid}/commercial/approve/{kind}',username=actor)
        assert r.status_code==200,r.text
    assert get(pid)['commercial']['gates']['firm_ready']
    issue=request('POST',f'/api/projects/{pid}/commercial/issue',username='commercial')
    assert issue.status_code==200,issue.text
    row=get(pid)['issues'][0]
    assert row['has_docx']
    pdf0=request('GET',f'/api/projects/{pid}/issued/{row["id"]}.pdf').content
    docx0=request('GET',f'/api/projects/{pid}/commercial/issued/{row["id"]}.docx').content
    assert 'Ms. Original Buyer' in pdf_text(pdf0)
    assert 'Ms. Original Buyer' in word_text(docx0)
    assert request('GET',f'/api/projects/{pid}/commercial/issued/{row["id"]}.docx',username='estimator').status_code==200
    assert request('GET',f'/api/projects/{pid}/commercial/issued/{row["id"]}.docx',username='estimator').headers['content-type'].startswith('application/vnd.openxmlformats')
    assert apply_contact(pid,'Mr. New Buyer').status_code==200
    assert request('GET',f'/api/projects/{pid}/issued/{row["id"]}.pdf').content==pdf0
    assert request('GET',f'/api/projects/{pid}/commercial/issued/{row["id"]}.docx').content==docx0


def test_non_default_classic_and_generic_templates_show_contact_and_word():
    for workflow, code in [('service_repair','short_service'),('general_sale','simple_sales')]:
        pid=create_quote(workflow)
        assert apply_contact(pid,'Mr. Named Contact').status_code==200
        assert request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'template':code}).status_code==200
        pdf=request('GET',f'/api/projects/{pid}/commercial/preview.pdf')
        word=request('GET',f'/api/projects/{pid}/commercial/preview.docx')
        assert pdf.status_code==200,pdf.text if pdf.status_code!=200 else ''
        assert word.status_code==200,word.text if word.status_code!=200 else ''
        assert 'Mr. Named Contact' in pdf_text(pdf.content)
        assert 'Mr. Named Contact' in word_text(word.content)


def test_safe_placeholder_migration_preserves_custom_seller():
    pid=create_quote()
    other=create_quote()
    with SessionLocal() as db:
        old=db.scalar(select(CommercialProfile).where(CommercialProfile.project_id==pid))
        brand=json.loads(old.branding);brand['name']='Your Company';old.branding=json.dumps(brand)
        intentional=db.scalar(select(CommercialProfile).where(CommercialProfile.project_id==other))
        custom=json.loads(intentional.branding);custom['name']='CUSTOM FABRICATION BRAND';intentional.branding=json.dumps(custom)
        db.commit()
    changed=upgrade_placeholder_seller_branding()
    assert changed>=1
    assert get(pid)['commercial']['profile']['branding']['name']=='YASH ENGINEERING'
    assert get(other)['commercial']['profile']['branding']['name']=='CUSTOM FABRICATION BRAND'
