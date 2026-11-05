"""All new product families use the original cost-plus path, without changing
previously saved commercial projects or the seeded pallet estimate."""
from tests.test_end_to_end import request, get
from backend.app import SessionLocal, Project
from backend import commercial


def _create(family='fabricated_pallet', workflow=None):
    data={'title':'Unified cost-plus regression','customer':'Synthetic Buyer',
          'product_code':family}
    if workflow is not None:
        data['quote_workflow']=workflow
    r=request('POST','/api/projects',username='estimator',json=data)
    assert r.status_code==200,r.text
    return r.json()


def test_all_families_use_original_cost_plus_workflow():
    rows=request('GET','/api/projects').json()
    demo=next(row for row in rows if row['ref']=='PALLET-PROOF-001')
    before=get(demo['id'])
    assert before['commercial'] is None
    families=('fabricated_pallet','eot_crane','belt_conveyor','general_fabrication','generic_service')
    for family in families:
        new=_create(family)
        assert new['project']['product_code']==family
        assert new['commercial'] is None
        assert 'order_value' in new['estimate']
        assert 'material_cost' in new['estimate']
        assert 'margin_pct' in new['project']
        assert 'pricing_approved' in new['gates']
        assert new['bom']==[] and new['operations']==[]
        assert get(new['project']['id'])['commercial'] is None
        pid=new['project']['id']
        assert new['quotation']['profile']['template']
        assert new['quotation']['pricing']['subtotal_known']==new['estimate']['order_value']
        assert request('GET',f'/api/projects/{pid}/preview.pdf').status_code==409
        assert request('GET',f'/api/projects/{pid}/quotation/preview.docx').status_code==409
        terms={**new['quotation']['profile']['terms'],'customer_attention':'Ms. Synthetic Contact'}
        assert request('PUT',f'/api/projects/{pid}/quotation',username='estimator',json={'terms':terms}).status_code==200
        preview=request('GET',f'/api/projects/{pid}/preview.pdf')
        assert preview.status_code==200 and preview.content.startswith(b'%PDF')
        word=request('GET',f'/api/projects/{pid}/quotation/preview.docx')
        assert word.status_code==200 and word.content.startswith(b'PK')
        audit=request('GET',f"/api/projects/{new['project']['id']}/audit").json()
        created=next(x for x in audit if x['action']=='PROJECT_CREATED')
        assert created['detail']['workflow']=='legacy_cost_plus'
    assert get(demo['id'])['estimate']['material_cost']==before['estimate']['material_cost']


def test_old_clients_cannot_select_a_different_workflow_for_new_projects():
    for family,workflow in [('fabricated_pallet','equipment_supply'),
                            ('eot_crane','equipment_supply'),
                            ('generic_service','service_repair'),
                            ('general_fabrication','general_sale')]:
        new=_create(family,workflow)
        assert new['commercial'] is None
        audit=request('GET',f"/api/projects/{new['project']['id']}/audit").json()
        created=next(x for x in audit if x['action']=='PROJECT_CREATED')
        assert created['detail']['workflow']=='legacy_cost_plus'
        assert created['detail']['requested_workflow']==workflow


def test_existing_commercial_project_and_issued_history_are_not_mutated():
    # Model an existing project created under the discontinued new-project path.
    old=_create('eot_crane')
    pid=old['project']['id']
    with SessionLocal() as db:
        p=db.get(Project,pid)
        commercial.init_profile(db,p,'equipment_supply')
        db.commit()
    original=get(pid)
    assert original['commercial']['profile']['workflow']=='equipment_supply'
    _create('generic_service')
    assert get(pid)['commercial']==original['commercial']
    assert get(pid)['issues']==original['issues']
