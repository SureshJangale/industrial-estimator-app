"""v0.8 regression checks: review a real extracted candidate, reopen, edit,
verify, and retain source traceability without pretending extraction is certain.
No confidential customer files are used here.
"""
from tests.test_end_to_end import request, sample_project, get, make_pdf
from backend.app import SessionLocal, Requirement, Document, CandidateReview
from sqlalchemy import select


def new_document(pid):
    body=make_pdf()
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',files={'file':('SYNTHETIC-REV-A.pdf',body,'application/pdf')})
    assert r.status_code==200,r.text
    doc=next(x for x in r.json()['documents'] if x['original_name']=='SYNTHETIC-REV-A.pdf')
    return doc


def candidate(doc,kind,key):
    return next(x for x in doc['candidates'] if x.get('kind')==kind and (x.get('key')==key or x.get('sku')==key))


def get_doc(pid,did):
    return next(d for d in get(pid)['documents'] if d['id']==did)


def test_requirement_verify_requires_real_source_review_and_remembers_evidence():
    pid=sample_project('fabricated_pallet')
    doc=new_document(pid)
    c=candidate(doc,'field','length_mm')
    row=next(x for x in get(pid)['requirements'] if x['key']=='length_mm')
    assert row['value']=='1100' and row['status']=='PENDING'
    assert row['evidence'].startswith('Extracted (unverified)')
    assert c['review']['state']=='AUTO_PREFILLED'
    assert request('POST',f'/api/projects/{pid}/requirements/length_mm/approve',username='engineer').status_code==422
    url=f'/api/projects/{pid}/requirements/length_mm/verify'
    incomplete={'value':'1100','source_reference':'Drawing revision A, page 1','document_id':doc['id'],'candidate_index':c['candidate_index']}
    assert request('POST',url,username='engineer',json=incomplete).status_code==422
    assert request('POST',url,username='estimator',json={**incomplete,'verification_note':'Confirmed against labelled view'}).status_code==403
    r=request('POST',url,username='engineer',json={**incomplete,
        'verification_note':'Confirmed 1100 mm on the drawing labelled Length view'})
    assert r.status_code==200,r.text
    state=get(pid)
    row=next(x for x in state['requirements'] if x['key']=='length_mm')
    assert row['status']=='APPROVED' and 'Engineer verification' in row['evidence']
    c=candidate(get_doc(pid,doc['id']),'field','length_mm')
    assert c['review']['state']=='VERIFIED' and c['review']['value'].startswith('1100')
    assert c['review']['target_kind']=='REQUIREMENT'
    a=request('GET',f'/api/projects/{pid}/audit').json()
    assert any(x['action']=='REQUIREMENT_EVIDENCE_VERIFIED' for x in a)
    # A manual edit must reset approval AND clear the obsolete source linkage.
    r=request('PUT',f'/api/projects/{pid}/requirements/length_mm',username='estimator',json={
        'value':'1120','evidence':'New drawing revision required', 'document_id':None})
    assert r.status_code==200,r.text
    assert candidate(get_doc(pid,doc['id']),'field','length_mm')['review']['state']=='UNREVIEWED'
    assert next(x for x in get(pid)['requirements'] if x['key']=='length_mm')['status']=='PENDING'


def test_material_review_persists_saved_quantity_in_documents_after_edits_and_approvals():
    pid=sample_project('fabricated_pallet')
    doc=new_document(pid)
    c=candidate(doc,'material','SHS-40-40-3')
    assert c['review']['state']=='UNREVIEWED'
    url=f'/api/projects/{pid}/bom'
    payload={'sku':'SHS-40-40-3','qty':'12.5','unit':'m','waste_pct':'6',
      'note':'Engineered member takeoff from approved list; pending engineer verification',
      'status':'ASSUMED','source_document_id':doc['id'],'source_candidate_index':c['candidate_index']}
    r=request('POST',url,username='estimator',json=payload)
    assert r.status_code==200,r.text
    bid=next(x['id'] for x in r.json()['bom'] if x['sku']=='SHS-40-40-3' and x['qty']=='12.5')
    state=get(pid)
    row=next(x for x in state['bom'] if x['id']==bid)
    assert row['source_link']['document_id']==doc['id']
    c=candidate(get_doc(pid,doc['id']),'material','SHS-40-40-3')
    assert c['review']['state']=='SAVED_PENDING' and c['review']['target_id']==bid
    assert '12.5 m' in c['review']['value']
    # Opening the source again presents the saved value; editing from the BOM tab updates it.
    payload.update(qty='15.25',source_document_id=None,source_candidate_index=None)
    r=request('PUT',f'{url}/{bid}',username='estimator',json=payload)
    assert r.status_code==200,r.text
    c=candidate(get_doc(pid,doc['id']),'material','SHS-40-40-3')
    assert '15.25 m' in c['review']['value'] and c['review']['state']=='SAVED_PENDING'
    r=request('POST',f'{url}/{bid}/approve',username='engineer',json={'source_reference':'Synthetic cutting list Rev A, page 1', 'verification_note':'Independently checked all material member lengths and counts'})
    assert r.status_code==200,r.text
    assert candidate(get_doc(pid,doc['id']),'material','SHS-40-40-3')['review']['state']=='VERIFIED'
    assert request('DELETE',f'{url}/{bid}',username='estimator').status_code==200
    assert candidate(get_doc(pid,doc['id']),'material','SHS-40-40-3')['review']['state']=='UNREVIEWED'


def test_candidate_disposition_is_persistent_and_cannot_hide_verified_requirements():
    pid=sample_project('fabricated_pallet')
    doc=new_document(pid)
    c=candidate(doc,'field','width_mm')
    url=f'/api/projects/{pid}/documents/{doc["id"]}/candidates/{c["candidate_index"]}/dismiss'
    r=request('POST',url,username='estimator',json={'explanation':'Outside customer scope; check later'})
    assert r.status_code==200,r.text
    assert candidate(get_doc(pid,doc['id']),'field','width_mm')['review']['state']=='DISMISSED'
    # Dismissing an automatically prefilled value must also clear it in Requirements.
    field=next(x for x in get(pid)['requirements'] if x['key']=='width_mm')
    assert field['value']=='' and field['status']=='PENDING'
    assert request('DELETE',url,username='estimator').status_code==200
    assert candidate(get_doc(pid,doc['id']),'field','width_mm')['review']['state']=='UNREVIEWED'


def test_operation_source_status_survives_reopen():
    from io import BytesIO
    from reportlab.pdfgen import canvas
    b=BytesIO(); c=canvas.Canvas(b);c.drawString(60,760,'FULL WELDED at all joints');c.save()
    pid=sample_project('fabricated_pallet')
    r=request('POST',f'/api/projects/{pid}/documents',username='estimator',files={'file':('WELD-REQ.pdf',b.getvalue(),'application/pdf')})
    assert r.status_code==200,r.text
    doc=r.json()['documents'][0]
    operation=candidate(doc,'operation','weld')
    payload={'code':'weld','description':'Full welding at joints','hours':'4','rate':'350','status':'ASSUMED',
      'source_document_id':doc['id'],'source_candidate_index':operation['candidate_index']}
    r=request('POST',f'/api/projects/{pid}/operations',username='estimator',json=payload)
    assert r.status_code==200,r.text
    row=next(x for x in r.json()['operations'] if x['code']=='weld')
    c=candidate(get_doc(pid,doc['id']),'operation','weld')
    assert c['review']['state']=='SAVED_PENDING' and c['review']['target_id']==row['id']
    assert '4 hours' in c['review']['value']
    r=request('POST',f'/api/projects/{pid}/operations/{row["id"]}/approve',username='procurement')
    assert r.status_code==200,r.text
    assert candidate(get_doc(pid,doc['id']),'operation','weld')['review']['state']=='VERIFIED'


def test_verified_requirement_synced_with_customer_facing_specification():
    pid=sample_project('fabricated_pallet')
    r=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'equipment_supply'})
    assert r.status_code==200,r.text
    doc=new_document(pid)
    c=candidate(doc,'field','length_mm')
    data={'value':'1100','source_reference':'REV A drawing page 1 (length)',
      'verification_note':'Checked labelled overall length dimension on drawing',
      'document_id':doc['id'],'candidate_index':c['candidate_index']}
    r=request('POST',f'/api/projects/{pid}/requirements/length_mm/verify',username='engineer',json=data)
    assert r.status_code==200,r.text
    fields=[f for x in get(pid)['commercial']['profile']['technical'] for f in x['fields']]
    matching=[f for f in fields if f['key']=='length_mm']
    if matching:
        assert matching[0]['value']=='1100' and matching[0]['review_status']=='APPROVED'


def test_technical_profile_inherits_requirements_extracted_before_commercial_setup():
    pid=sample_project('fabricated_pallet')
    doc=new_document(pid)
    assert next(r for r in get(pid)['requirements'] if r['key']=='length_mm')['value']=='1100'
    r=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'equipment_supply'})
    assert r.status_code==200,r.text
    technical=[f for section in get(pid)['commercial']['profile']['technical'] for f in section['fields']]
    corresponding=[f for f in technical if f.get('key')=='length_mm']
    if corresponding:
        assert corresponding[0]['value']=='1100'
        assert corresponding[0]['review_status']=='PENDING'
        assert corresponding[0]['evidence']


def test_technical_edit_from_customer_quote_resets_requirement_approval():
    pid=sample_project('fabricated_pallet')
    doc=new_document(pid)
    r=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'workflow':'equipment_supply'})
    assert r.status_code==200,r.text
    data=get(pid)['commercial']['profile']['technical']
    lookup=[(i,j,f) for i,sec in enumerate(data) for j,f in enumerate(sec['fields']) if f.get('key')=='length_mm']
    if not lookup:return
    i,j,f=lookup[0]
    data[i]['fields'][j]['value']='1200'
    data[i]['fields'][j]['evidence']='Updated design drawing revision B page 2'
    data[i]['fields'][j]['review_status']='APPROVED'  # malicious/accidental client assertion
    response=request('PUT',f'/api/projects/{pid}/commercial',username='estimator',json={'technical':data})
    assert response.status_code==200,response.text
    row=next(r for r in get(pid)['requirements'] if r['key']=='length_mm')
    assert row['value']=='1200' and row['status']=='PENDING'
    field=next(f for x in get(pid)['commercial']['profile']['technical'] for f in x['fields'] if f.get('key')=='length_mm')
    assert field['review_status']=='PENDING'
