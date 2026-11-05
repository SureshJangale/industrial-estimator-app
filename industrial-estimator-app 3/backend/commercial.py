"""Generic customer-facing quotations: equipment, repairs, fabricated products, services.

Separates *internal cost estimates* from *customer selling prices*.  All tax
rates and commercial claims require explicit human confirmation. No paid APIs.
"""
from __future__ import annotations
import hashlib
import io
import json
import secrets
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from fastapi import Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from .app import (Base, app, engine, SessionLocal, db_session, current_user, User, Project,
    Requirement, Approval, IssuedQuote, PRIVATE_DIR, get_project, get_config,
    project_json, config_dict, requirement_json, pack_records, record, utcnow, dec, money, Q_APPROVED)
from .extraction import conflicts_from_docs, extract_candidates
from .company_settings import branding_for


class CommercialProfile(Base):
    __tablename__='commercial_profiles'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    project_id: Mapped[int]=mapped_column(ForeignKey('projects.id'),unique=True,index=True)
    workflow: Mapped[str]=mapped_column(String(40),default='equipment_supply')
    template: Mapped[str]=mapped_column(String(60),default='multi_annexure')
    tax_config: Mapped[str]=mapped_column(Text,default='{}')
    terms: Mapped[str]=mapped_column(Text,default='{}')
    technical: Mapped[str]=mapped_column(Text,default='[]')
    branding: Mapped[str]=mapped_column(Text,default='{}')
    external_reference: Mapped[str]=mapped_column(String(60),default='')
    updated_at: Mapped[object]=mapped_column(DateTime,default=utcnow)


class CustomerLine(Base):
    __tablename__='customer_lines'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    project_id: Mapped[int]=mapped_column(ForeignKey('projects.id'),index=True)
    ordinal: Mapped[int]=mapped_column(Integer,default=10)
    description: Mapped[str]=mapped_column(Text)
    mode: Mapped[str]=mapped_column(String(25))
    qty: Mapped[str]=mapped_column(String(30),default='')
    unit: Mapped[str]=mapped_column(String(30),default='each')
    price: Mapped[str]=mapped_column(String(35),default='')
    tax_applicable: Mapped[bool]=mapped_column(Boolean,default=True)
    tax_code: Mapped[str]=mapped_column(String(40),default='')
    parent_id: Mapped[int | None]=mapped_column(Integer,nullable=True)
    notes: Mapped[str]=mapped_column(Text,default='')


class FieldResolution(Base):
    __tablename__='field_resolutions'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    project_id: Mapped[int]=mapped_column(ForeignKey('projects.id'),index=True)
    field_key: Mapped[str]=mapped_column(String(100))
    accepted_value: Mapped[str]=mapped_column(String(220))
    document_fingerprint: Mapped[str]=mapped_column(String(64))
    explanation: Mapped[str]=mapped_column(Text)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    at: Mapped[object]=mapped_column(DateTime,default=utcnow)


# Additive tables only: compatible with existing v0.1 SQLite schema.
Base.metadata.create_all(engine)

WORKFLOWS={'equipment_supply','service_repair','general_sale'}
MODES={'FIXED','UNIT_RATE','INCLUDED','EXCLUDED','AT_ACTUAL','NOTE'}
CENT=Decimal('.01')


def js(data, fallback):
    try:return json.loads(data or '')
    except (ValueError,TypeError):return fallback


def profile_for(db,pid):
    return db.scalar(select(CommercialProfile).where(CommercialProfile.project_id==pid))


def init_profile(db,p,workflow):
    if workflow not in WORKFLOWS:raise HTTPException(422,'Unknown quotation workflow')
    if profile_for(db,p.id):raise HTTPException(409,'Commercial profile already exists')
    from .templates import get_default
    template=get_default(db,workflow).code
    cfg=config_dict(get_config(db,p.product_code))
    technical=[]
    existing_req={r.field_key:r for r in db.scalars(select(Requirement).where(Requirement.project_id==p.id)).all()}
    if workflow!='service_repair':
        sections=cfg.get('specification_sections') or ([{'id':'general','title':'Technical specification',
          'fields':cfg.get('required_fields',[])}] if cfg.get('required_fields') else [])
        for section in sections:
            technical.append({'id':section['id'],'title':section.get('title',section['id']),
                'fields':[{'key':f.get('key',''),'label':f.get('label',''),
                  'value':existing_req.get(f.get('key')).value if f.get('key') in existing_req else '',
                  'unit':f.get('unit',''),
                  'review_status':existing_req[f.get('key')].status if f.get('key') in existing_req else 'PENDING',
                  'evidence':existing_req.get(f.get('key')).evidence if f.get('key') in existing_req else ''} for f in section.get('fields',[])]})
    profile=CommercialProfile(project_id=p.id,workflow=workflow,template=template,
        tax_config=json.dumps({'mode':'EXCLUSIVE','status':'PENDING','components':[],'basis_note':'Requires accountant/commercial verification'}),
        terms=json.dumps({'scope':'','delivery':p.delivery,'payment':p.payment_terms,'warranty':'',
            'inspection':'','transport':'','exclusions':p.exclusions,'certifications':[],
            'validity_days':p.validity_days}),technical=json.dumps(technical),
        branding=json.dumps(branding_for(db),ensure_ascii=False))
    db.add(profile);db.flush()
    return profile


def quote_line(x):
    return {'id':x.id,'ordinal':x.ordinal,'description':x.description,'mode':x.mode,
      'qty':x.qty,'unit':x.unit,'price':x.price,'tax_applicable':x.tax_applicable,
      'tax_code':x.tax_code,'parent_id':x.parent_id,'notes':x.notes}


INVALID_CONTACTS = {
    '', 'purchasing team', 'purchase team', 'procurement team',
    'purchase department', 'procurement department', 'sales team', 'dear sir',
    'contact person', 'unknown', 'tbd', 'tbc', 'na', 'n/a', 'pending',
    'pending review', 'not specified', 'not available', '-',
}


def customer_contact(profile:dict) -> str:
    return str((profile.get('terms') or {}).get('customer_attention') or '').strip()


def contact_is_named(profile:dict) -> bool:
    name=customer_contact(profile)
    return bool(name and len(name)<=160 and sum(c.isalpha() for c in name)>=2
                and name.casefold().strip(' .') not in INVALID_CONTACTS)


def require_contact(profile:dict) -> str:
    name=customer_contact(profile)
    if not contact_is_named(profile):
        raise HTTPException(409,
            'Enter the customer contact PERSON (Kind Attendance) before generating a quotation. '
            'A department such as Purchase Team is not a person. Save it in Customer quotation > Edit contact / terms.')
    return name


def upgrade_placeholder_seller_branding():
    """Only migrate untouched v0.x placeholder branding; never change custom seller profiles."""
    with SessionLocal() as db:
        profiles=db.scalars(select(CommercialProfile)).all()
        changed=0
        for q in profiles:
            brand=js(q.branding,{})
            if str(brand.get('name') or '').strip().lower() in ('your company',''):
                q.branding=json.dumps(branding_for(db),ensure_ascii=False)
                changed+=1
            elif str(brand.get('name') or '').strip().upper()=='YASH ENGINEERING' and 'heading' not in brand:
                # Safe additive migration for the older Yash-issued pattern only.
                # No generic customer heading is invented for another company.
                brand['heading']='II Shri II'
                q.branding=json.dumps(brand,ensure_ascii=False)
                changed+=1
        if changed:db.commit()
    return changed


@app.post('/api/projects/{pid}/commercial/apply-company-profile')
def apply_current_company_profile(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    """Explicitly resync an existing draft; historic issued snapshots are untouched."""
    from .app import require_role
    require_role(user,'estimator','commercial')
    p=get_project(db,pid)
    q=profile_for(db,pid)
    if not q:raise HTTPException(409,'Customer-facing quotation workflow is not enabled')
    q.branding=json.dumps(branding_for(db),ensure_ascii=False)
    q.updated_at=utcnow();p.updated_at=utcnow();p.status='DRAFT'
    record(db,user,'PROJECT_BRANDING_REFRESHED',pid,{'company':branding_for(db).get('name')})
    db.commit()
    return commercial_overview(db,p)


def profile_json(profile):
    return {'id':profile.id,'workflow':profile.workflow,'template':profile.template,
      'tax_config':js(profile.tax_config,{}),'terms':js(profile.terms,{}),
      'technical':js(profile.technical,[]),'branding':js(profile.branding,{}),
      'external_reference':profile.external_reference}


def doc_list(db,p):
    docs=pack_records(db,p)[3]
    return [{'id':d.id,'original_name':d.original_name,'checksum':d.checksum,
             'candidates':js(d.candidates,[])} for d in docs]


def extract_fp(db,p,key):
    refs=[]
    for d in doc_list(db,p):
        for c in d['candidates']:
            if c.get('kind')=='field' and c.get('key')==key:
                refs.append({'checksum':d['checksum'],'value':c.get('value'),'page':c.get('page'),'evidence':c.get('evidence')})
    return hashlib.sha256(json.dumps(sorted(refs,key=lambda x:(x['checksum'],str(x['page']),str(x['value']))),sort_keys=True).encode()).hexdigest()


def commercial_conflicts(db,p):
    detected=conflicts_from_docs(doc_list(db,p))
    res=db.scalars(select(FieldResolution).where(FieldResolution.project_id==p.id).order_by(FieldResolution.id.desc())).all()
    latest={}
    for r in res:
        latest.setdefault(r.field_key,r)
    reqs={r.field_key:r for r in pack_records(db,p)[0]}
    for c in detected:
        v=latest.get(c['key']); req=reqs.get(c['key'])
        valid=bool(v and v.document_fingerprint==extract_fp(db,p,c['key']) and req
            and req.status=='APPROVED' and req.value.strip()==v.accepted_value)
        c['status']='RESOLVED' if valid else 'UNRESOLVED'
        if valid:c['resolution']={'accepted_value':v.accepted_value,'reason':v.explanation,'reviewed_by':v.user_id}
    return detected


def price_vs_spec_findings(db,p):
    """Compare technical requirement values with explicit quantities in price-line prose.

    Reuses the field aliases in the product configuration. No crane-specific
    condition is introduced into the generic commercial quotation engine.
    """
    cfg=config_dict(get_config(db,p.product_code))
    reqs={r.field_key:r for r in pack_records(db,p)[0]}
    lines=db.scalars(select(CustomerLine).where(CustomerLine.project_id==p.id)).all()
    result=[]
    for line in lines:
        for candidate in extract_candidates([line.description],cfg,[],source_kind='QUOTE_LINE'):
            if candidate.get('kind')!='field':continue
            key=candidate['key'];req=reqs.get(key)
            if req and req.status=='APPROVED' and req.value.strip():
                try:match=Decimal(req.value.strip())==Decimal(candidate['value'])
                except Exception:match=req.value.strip().lower()==candidate['value'].lower()
                if not match:
                    result.append({'severity':'BLOCKING','key':key,'source':'CUSTOMER_PRICE_LINE',
                        'line_id':line.id,'expected':req.value,'observed':candidate['value'],
                        'message':'Customer-facing price line conflicts with engineer-approved technical requirement',
                        'evidence':candidate.get('evidence')})
    return result


def calculate_commercial(db,p):
    q=profile_for(db,p.id)
    if not q:return None
    items=db.scalars(select(CustomerLine).where(CustomerLine.project_id==p.id).order_by(CustomerLine.ordinal,CustomerLine.id)).all()
    tax=js(q.tax_config,{})
    subtotal=Decimal('0'); taxable=Decimal('0'); rows=[]; incompletes=[];variable=[]
    for x in items:
        value=None
        if x.mode in ('FIXED','UNIT_RATE'):
            if x.price.strip() and (x.mode=='FIXED' or x.qty.strip()):
                rate=dec(x.price,'offered unit price',0)
                qty=dec(x.qty,'selling quantity',Decimal('0.0000001')) if x.mode=='UNIT_RATE' else Decimal('1')  # FIXED is total lump sum
                value=(rate*qty).quantize(CENT,rounding=ROUND_HALF_UP)
                subtotal+=value
                if x.tax_applicable:taxable+=value
            else: incompletes.append({'line_id':x.id,'description':x.description,'issue':'Quantity or unit price missing'})
        elif x.mode=='AT_ACTUAL':variable.append(x.description)
        rows.append({**quote_line(x),'line_total':str(value) if value is not None else None})
    taxes=[];tax_amount=Decimal(0)
    for component in tax.get('components',[]):
        pct=dec(component.get('rate','0'),'tax %',0,100)
        amount=(taxable*pct/100).quantize(CENT,rounding=ROUND_HALF_UP)
        taxes.append({'name':component['name'],'rate':str(pct),'amount':str(amount)})
        tax_amount+=amount
    return {'lines':rows,'subtotal_known':str(subtotal.quantize(CENT)),
        'taxable_subtotal':str(taxable.quantize(CENT)),
        'tax_components':taxes,'tax_amount':str(tax_amount.quantize(CENT)),
        'known_total_including_tax':str((subtotal+tax_amount).quantize(CENT)),
        'grand_total_definitive':not incompletes and not variable and tax.get('status')=='APPROVED',
        'unpriced_lines':incompletes,'additional_at_actual':variable,
        'tax_status':tax.get('status','PENDING'),
        'tax_mode':tax.get('mode','EXCLUSIVE'),
        'tax_warning':'Tax profile requires approval' if tax.get('status')!='APPROVED' else ''}


def commercial_fingerprint(db,p):
    q=profile_for(db,p.id)
    items=db.scalars(select(CustomerLine).where(CustomerLine.project_id==p.id).order_by(CustomerLine.ordinal,CustomerLine.id)).all()
    reqs, bom, ops, docs=pack_records(db,p)
    obj={'project':project_json(p),'profile':profile_json(q),'lines':[quote_line(x) for x in items],
        'requirements':[requirement_json(x) for x in reqs],
        'documents':[{'checksum':d.checksum,'id':d.id,'candidates':js(d.candidates,[])} for d in docs],
        'resolutions':[{'key':x.field_key,'value':x.accepted_value,'evidence_fingerprint':x.document_fingerprint,'reason':x.explanation}
            for x in db.scalars(select(FieldResolution).where(FieldResolution.project_id==p.id).order_by(FieldResolution.id)).all()]}
    from .templates import get_template
    template=get_template(db,q.template)
    obj['template_version']=template.version if template else None
    obj['template_layout']=template.layout_json if template else None
    from .word_quote_templates import asset_for
    word_asset=asset_for(db,template)
    obj['template_docx_checksum']=word_asset.checksum if word_asset else None
    obj['project'].pop('updated_at',None);obj['project'].pop('status',None)
    return hashlib.sha256(json.dumps(obj,sort_keys=True,default=str).encode()).hexdigest()


def commercial_checks(db,p,calc=None):
    q=profile_for(db,p.id)
    if not q:return None
    calc=calc or calculate_commercial(db,p)
    from .templates import get_template
    selected=get_template(db,q.template)
    template_ok=bool(selected and selected.workflow==q.workflow)
    profile=profile_json(q)
    reqs,bom,ops,docs=pack_records(db,p)
    conflicts=commercial_conflicts(db,p)
    price_findings=price_vs_spec_findings(db,p)
    conflict_blockers=[c['key'] for c in conflicts if c['status']=='UNRESOLVED']
    cfg=config_dict(get_config(db,p.product_code))
    missing=[]
    if q.workflow=='service_repair':
        technical_ok=bool(profile['terms'].get('scope','').strip())
        if not technical_ok:missing.append('Service scope / work description')
    elif q.workflow=='general_sale':
        technical_ok=bool(profile['terms'].get('scope','').strip())
        if not technical_ok:missing.append('Supply scope')
    else:
        required=[f['key'] for f in cfg.get('required_fields',[]) if f.get('firm_required')]
        found={r.field_key:r for r in reqs}
        for key in required:
            r=found.get(key)
            if not r or r.status!='APPROVED' or not r.value.strip():missing.append(key)
        technical_ok=bool(docs) and not missing and bool(cfg.get('firm_release_enabled',True))
        if not docs:missing.append('Supporting technical document')
        if not cfg.get('firm_release_enabled',True):missing.append('Engineer-validated product family release')
    specs=profile['technical']
    spec_pending=[f.get('label',f.get('key','')) for s in specs for f in s.get('fields',[])
        if str(f.get('value','')).strip() and f.get('review_status')!='APPROVED']
    if q.workflow=='equipment_supply' and spec_pending:technical_ok=False;missing.extend(spec_pending)
    line_ok=bool(calc['lines']) and not calc['unpriced_lines']
    if not calc['lines']:missing.append('At least one customer selling-price line')
    if calc['unpriced_lines']:missing.append('Price-line quantities / rates')
    tax_ok=profile['tax_config'].get('status')=='APPROVED'
    if not tax_ok:missing.append('Tax profile needs commercial/accounting approval')
    # Explicitly presented AT_ACTUAL charges are permitted, but numeric total stays qualified.
    payment=str(profile['terms'].get('payment','')).strip().lower()
    delivery=str(profile['terms'].get('delivery','')).strip().lower()
    terms_ok=bool(payment and delivery and payment not in ('to be agreed','tbd','to be confirmed') and delivery not in ('to be confirmed','tbd','to be agreed'))
    if not terms_ok:missing.append('Payment and delivery terms')
    contact_ok=contact_is_named(profile)
    if not contact_ok:missing.append('Named customer contact person (Kind Attendance)')
    fp=commercial_fingerprint(db,p)
    all_ap=db.scalars(select(Approval).where(Approval.project_id==p.id).order_by(Approval.id.desc())).all()
    current={}
    for a in all_ap:
        if a.kind in ('quote_engineering','quote_pricing','quote_commercial') and a.fingerprint==fp:
            current.setdefault(a.kind,a)
    need_engineering=q.workflow=='equipment_supply'
    eng=bool(current.get('quote_engineering')) if need_engineering else True
    pric=bool(current.get('quote_pricing'))
    comm=bool(current.get('quote_commercial'))
    if not template_ok:missing.append('Compatible quotation template')
    firm_ready=all((template_ok,technical_ok,line_ok,tax_ok,terms_ok,contact_ok,not conflict_blockers,not price_findings,eng,pric,comm))
    return {'firm_ready':firm_ready,'workflow':q.workflow,
      'template_valid':template_ok,'technical_verified':technical_ok,'price_lines_complete':line_ok,'tax_approved':tax_ok,
      'terms_complete':terms_ok,'customer_contact_confirmed':contact_ok,'unresolved_conflicts':conflict_blockers,'price_spec_conflicts':[x['key'] for x in price_findings],'pending_spec_review':spec_pending,
      'engineering_approved':eng,'pricing_approved':pric,'commercial_approved':comm,
      'missing':sorted(set(missing)),'fingerprint':fp}


def commercial_overview(db,p):
    q=profile_for(db,p.id)
    if not q:return None
    return {'profile':profile_json(q),'pricing':calculate_commercial(db,p),
       'gates':commercial_checks(db,p),'conflicts':commercial_conflicts(db,p),
       'quality_findings':price_vs_spec_findings(db,p)}


class ProfileUpdate(BaseModel):
    workflow: str | None = None
    template: str | None = None
    tax_config: dict | None = None
    terms: dict | None = None
    technical: list[dict] | None = None
    branding: dict | None = None
    external_reference: str | None = Field(default=None,max_length=60)


class CustomerLineInput(BaseModel):
    description: str=Field(min_length=2,max_length=500)
    mode: str='FIXED'
    qty: str=''
    unit: str=Field(default='Nos.',max_length=24)
    price: str=''
    ordinal: int=10
    tax_applicable: bool=True
    tax_code: str=Field(default='',max_length=40)
    parent_id: int | None=None
    notes: str=Field(default='',max_length=1000)

    @field_validator('unit')
    @classmethod
    def valid_unit(cls, raw:str):
        unit=raw.strip()
        if not unit or not re.fullmatch(r'[\w][\w ./%+-]{0,23}',unit,flags=re.UNICODE):
            raise ValueError('Choose a unit such as Nos., kg, m, m2, Set, Pair, hour, or a custom short label')
        return unit


class ResolveBody(BaseModel):
    accepted_value:str=Field(min_length=1,max_length=220)
    explanation:str=Field(min_length=12,max_length=1500)


@app.get('/api/projects/{pid}/commercial')
def get_commercial(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    return commercial_overview(db,get_project(db,pid))


@app.put('/api/projects/{pid}/commercial')
def save_commercial(pid:int,data:ProfileUpdate,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    require_role(user,'estimator','commercial')
    p=get_project(db,pid)
    q=profile_for(db,pid)
    if not q:
        if not data.workflow:raise HTTPException(422,'Select quotation workflow first')
        q=init_profile(db,p,data.workflow)
    if data.workflow is not None and data.workflow!=q.workflow:
        raise HTTPException(422,'Cannot change established quote workflow; create a new project')
    if data.template is not None:
        from .templates import get_template
        selected=get_template(db,data.template)
        if not selected or selected.workflow!=q.workflow:
            raise HTTPException(422,'Unknown or incompatible quotation template')
        q.template=data.template
    if data.tax_config is not None:
        tax=data.tax_config
        if tax.get('mode','EXCLUSIVE')!='EXCLUSIVE':raise HTTPException(422,'Only explicitly tax-exclusive quotes supported')
        components=tax.get('components',[])
        if len(components)>6:raise HTTPException(422,'Maximum six tax components')
        for c in components:
            if not isinstance(c,dict) or not str(c.get('name','')).strip():raise HTTPException(422,'Each tax component needs a name')
            dec(c.get('rate'),'tax percent',0,100)
        if tax.get('status')=='APPROVED':
            require_role(user,'commercial','procurement')
            if not str(tax.get('basis_note','')).strip():raise HTTPException(422,'Document the accountant-approved tax basis')
        else:tax['status']='PENDING'
        q.tax_config=json.dumps(tax,sort_keys=True)
    if data.terms is not None:
        name=str(data.terms.get('customer_attention') or '').strip()
        if len(name)>160:raise HTTPException(422,'Contact person name is too long')
        if name and not contact_is_named({'terms':data.terms}):
            raise HTTPException(422,'Enter an actual named contact person, not a department such as Purchase Team')
        if len(json.dumps(data.terms))>15000:raise HTTPException(422,'Terms too long')
        q.terms=json.dumps(data.terms,ensure_ascii=False)
    if data.technical is not None:
        if len(data.technical)>40:raise HTTPException(422,'Too many technical sections')
        from .app import CandidateReview
        known={r.field_key:r for r in db.scalars(select(Requirement).where(Requirement.project_id==pid)).all()}
        # Product-required keys have one source of truth. Editing a customer-facing
        # technical spec updates the project requirement and resets verification.
        # The UI cannot forge APPROVED by changing JSON directly.
        for section in data.technical:
            for f in section.get('fields',[]):
                r=known.get(f.get('key'))
                if r:
                    newval=str(f.get('value','')).strip()
                    evidence=str(f.get('evidence','')).strip()
                    if newval!=r.value or evidence!=r.evidence:
                        for entry in db.scalars(select(CandidateReview).where(CandidateReview.project_id==pid,CandidateReview.target_kind=='REQUIREMENT',CandidateReview.target_id==r.id)).all():db.delete(entry)
                        if newval!=r.value:r.document_id=None
                        r.value=newval;r.evidence=evidence;r.status='PENDING';r.updated_at=utcnow()
                    f['value']=r.value;f['evidence']=r.evidence;f['review_status']=r.status
                else:
                    f['review_status']='PENDING'
        q.technical=json.dumps(data.technical,ensure_ascii=False)
    if data.branding is not None:
        if len(json.dumps(data.branding))>5000:raise HTTPException(422,'Branding data too long')
        q.branding=json.dumps(data.branding,ensure_ascii=False)
    if data.external_reference is not None:
        proposed=data.external_reference.strip()
        existing=db.scalar(select(CommercialProfile).where(CommercialProfile.external_reference==proposed,CommercialProfile.project_id!=pid)) if proposed else None
        if existing:raise HTTPException(409,'Quotation reference already used on another project')
        q.external_reference=proposed
    q.updated_at=utcnow();p.status='DRAFT';p.updated_at=utcnow()
    record(db,user,'COMMERCIAL_PROFILE_UPDATED',pid)
    db.commit()
    return commercial_overview(db,p)


@app.post('/api/projects/{pid}/commercial/verify-specs')
def verify_specs(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    require_role(user,'engineer')
    p=get_project(db,pid);q=profile_for(db,pid)
    if not q:raise HTTPException(404,'Commercial profile missing')
    technical=js(q.technical,[])
    for section in technical:
        for f in section.get('fields',[]):
            if f.get('value') and (not f.get('evidence') or str(f.get('evidence')).strip().lower().startswith(('unverified ', 'extracted (unverified)'))):
                raise HTTPException(409,'Technical specification contains machine-extracted evidence only. Review the requirement against its source and record engineer verification first')
            if f.get('value'):f['review_status']='APPROVED'
    q.technical=json.dumps(technical);q.updated_at=utcnow()
    record(db,user,'TECHNICAL_SPEC_VERIFIED',pid)
    db.commit();return commercial_overview(db,p)


@app.post('/api/projects/{pid}/commercial/lines')
def add_line(pid:int,data:CustomerLineInput,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    require_role(user,'estimator','commercial')
    p=get_project(db,pid)
    if not profile_for(db,pid):raise HTTPException(409,'Select commercial workflow')
    if data.mode not in MODES:raise HTTPException(422,'Unknown price mode')
    if data.mode in ('FIXED','UNIT_RATE'):
        if data.price.strip():dec(data.price,'price',0)
        if data.qty.strip():dec(data.qty,'quantity',0)
    if data.mode=='FIXED' and data.qty.strip() and dec(data.qty,'quantity') != 1:
        raise HTTPException(422,'Fixed amount is a total lump sum; use UNIT_RATE for quantity x rate')
    obj=CustomerLine(project_id=pid,**data.model_dump())
    db.add(obj);db.flush();p.status='DRAFT';p.updated_at=utcnow()
    record(db,user,'SELLING_LINE_ADDED',pid,{'id':obj.id,'mode':obj.mode});db.commit()
    return commercial_overview(db,p)


@app.put('/api/projects/{pid}/commercial/lines/{line_id}')
def update_line(pid:int,line_id:int,data:CustomerLineInput,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    require_role(user,'estimator','commercial')
    p=get_project(db,pid)
    line=db.scalar(select(CustomerLine).where(CustomerLine.project_id==pid,CustomerLine.id==line_id))
    if not line:raise HTTPException(404,'Line not found')
    if data.mode not in MODES:raise HTTPException(422,'Invalid line mode')
    if data.price.strip():dec(data.price,'price',0)
    if data.qty.strip():dec(data.qty,'quantity',0)
    if data.mode=='FIXED' and data.qty.strip() and dec(data.qty,'quantity') != 1:
        raise HTTPException(422,'Fixed amount is a total lump sum; use UNIT_RATE for quantity x rate')
    for field,val in data.model_dump().items():setattr(line,field,val)
    p.status='DRAFT';p.updated_at=utcnow()
    record(db,user,'SELLING_LINE_UPDATED',pid,{'id':line.id});db.commit()
    return commercial_overview(db,p)


@app.delete('/api/projects/{pid}/commercial/lines/{line_id}')
def delete_line(pid:int,line_id:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    require_role(user,'estimator','commercial')
    p=get_project(db,pid)
    obj=db.scalar(select(CustomerLine).where(CustomerLine.project_id==pid,CustomerLine.id==line_id))
    if not obj:raise HTTPException(404,'Line not found')
    db.delete(obj);p.status='DRAFT';p.updated_at=utcnow()
    record(db,user,'SELLING_LINE_REMOVED',pid,{'id':line_id});db.commit()
    return commercial_overview(db,p)


@app.post('/api/projects/{pid}/commercial/conflicts/{key}/resolve')
def resolve_conflict(pid:int,key:str,data:ResolveBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    require_role(user,'engineer')
    p=get_project(db,pid)
    candidates=[c for c in commercial_conflicts(db,p) if c['key']==key]
    if not candidates:raise HTTPException(404,'No conflicting source values for field')
    allowed={str(v['value']) for v in candidates[0]['values']}
    if data.accepted_value not in allowed:raise HTTPException(422,'Chosen value must be one of the source-supported candidates')
    r=db.scalar(select(Requirement).where(Requirement.project_id==pid,Requirement.field_key==key))
    if not r or r.status!='APPROVED' or r.value.strip()!=data.accepted_value:
        raise HTTPException(409,'First set and engineer-approve the selected requirement value')
    db.add(FieldResolution(project_id=pid,field_key=key,accepted_value=data.accepted_value,
        document_fingerprint=extract_fp(db,p,key),explanation=data.explanation,user_id=user.id))
    record(db,user,'SOURCE_CONFLICT_RESOLVED',pid,{'key':key,'accepted_value':data.accepted_value,'reason':data.explanation})
    db.commit();return commercial_overview(db,p)


@app.post('/api/projects/{pid}/commercial/approve/{kind}')
def approve_commercial(pid:int,kind:str,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    role={'engineering':'engineer','pricing':'procurement','commercial':'commercial'}.get(kind)
    if not role:raise HTTPException(404,'Unknown approval')
    require_role(user,role)
    p=get_project(db,pid);q=profile_for(db,pid)
    if not q:raise HTTPException(409,'Commercial workflow not enabled')
    checks=commercial_checks(db,p)
    if checks['unresolved_conflicts'] or checks['price_spec_conflicts']:
        raise HTTPException(409,'Resolve source conflicts and technical/price-schedule mismatches first')
    if kind=='engineering' and not checks['technical_verified']:raise HTTPException(409,'Technical fields are unverified')
    if kind=='pricing' and not (checks['price_lines_complete'] and checks['tax_approved']):
        raise HTTPException(409,'Customer price lines and tax policy require review')
    if kind=='commercial':
        if not checks['pricing_approved'] or not checks['terms_complete']:
            raise HTTPException(409,'Pricing approval and commercial terms required')
        if q.workflow=='equipment_supply' and not checks['engineering_approved']:
            raise HTTPException(409,'Engineering approval required')
        eng=db.scalar(select(Approval).where(Approval.project_id==pid,Approval.kind=='quote_engineering',Approval.fingerprint==checks['fingerprint']).order_by(Approval.id.desc()))
        if eng and eng.user_id==user.id:raise HTTPException(409,'Separate engineering and commercial approvers required')
    db.add(Approval(project_id=pid,kind='quote_'+kind,user_id=user.id,fingerprint=checks['fingerprint'],note='Commercial profile review'))
    record(db,user,'QUOTE_'+kind.upper()+'_APPROVED',pid)
    db.commit();return commercial_overview(db,p)


def render_pdf(p:Project,profile,summary,firm=False,number=None,layout=None):
    """Render only whitelisted, admin-authored data; never execute template markup."""
    from .templates import DEFAULTS, valid_layout
    if layout is None:
        builtins={code:cfg for code,_name,_wf,cfg in DEFAULTS}
        layout=builtins.get(profile['template']) or builtins['simple_sales']
    layout=valid_layout(layout)
    if layout.get('format_style') in ('classic_equipment','classic_service'):
        from .classic_formats import classic_quote
        return classic_quote(p,profile,summary,firm=firm,number=number,layout=layout)
    pdf=io.BytesIO()
    d=SimpleDocTemplate(pdf,pagesize=A4,rightMargin=17*mm,leftMargin=17*mm,
                        topMargin=16*mm,bottomMargin=16*mm)
    styles=getSampleStyleSheet()
    primary=colors.HexColor(layout['primary_color'])
    accent=colors.HexColor(layout['accent_color'])
    styles.add(ParagraphStyle(name='IQTitle',parent=styles['Title'],fontSize=17,leading=22,
                              spaceAfter=8,textColor=primary))
    styles.add(ParagraphStyle(name='IQSection',parent=styles['Heading2'],fontSize=11,
                              spaceBefore=10,spaceAfter=5,textColor=primary))
    styles.add(ParagraphStyle(name='IQText',parent=styles['Normal'],fontSize=9,leading=12,
                              spaceAfter=4))
    styles.add(ParagraphStyle(name='IQSmall',parent=styles['Normal'],fontSize=8,leading=11,
                              textColor=colors.HexColor('#4b5c6a')))
    def P(x,style='IQText'):
        return Paragraph(escape(str(x or '')).replace('\n','<br/>'),styles[style])
    def tbl(rows,widths=None):
        table=Table([[P(x) for x in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('LINEBELOW',(0,0),(-1,0),.65,accent),
          ('GRID',(0,0),(-1,-1),.25,colors.HexColor('#d5dfe7')),
          ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef4f6')),
          ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),
          ('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),4),
          ('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return table
    brand=profile['branding'];terms=profile['terms'];tax=summary['pricing']
    reference=number or profile.get('external_reference') or p.ref+' / DRAFT'
    def substitute(source):
        for k,v in {'{customer}':p.customer,'{project}':p.title,'{quote_number}':reference,
                    '{company_name}':brand.get('name',''),' {date}':date.today().isoformat(),
                    '{date}':date.today().isoformat()}.items():
            source=source.replace(k,str(v))
        return source
    st=[P(brand.get('name','Your company'),'IQTitle'),P(brand.get('address',''),'IQSmall'),
        P(brand.get('contact',''),'IQSmall'),Spacer(1,5*mm),
        P(layout['title'],'IQSection')]
    if layout.get('tagline'):st.append(P(substitute(layout['tagline']),'IQSmall'))
    st.extend([P('QUOTE: '+reference),P('CUSTOMER: '+p.customer),
               P('KIND ATTENDANCE: '+require_contact(profile)),
               P('PROJECT: '+p.title),P('DATE: '+date.today().isoformat())])
    if layout.get('intro'):st.extend([Spacer(1,3*mm),P(substitute(layout['intro']))])
    for sec in layout['sections']:
        if not sec['enabled']:continue
        kind=sec['key'];st.append(P(sec['title'],'IQSection'))
        if kind=='technical':
            rows=[['Parameter','Specification']]
            for section in profile.get('technical',[]):
                rows.append([section.get('title','Section'),''])
                for f in section.get('fields',[]):
                    if f.get('value'):rows.append([f.get('label',f.get('key','')),
                                                     str(f['value'])+' '+f.get('unit','')])
            if len(rows)==1:rows.append(['Scope','Technical schedule pending review'])
            st.append(tbl(rows,[65*mm,107*mm]))
        elif kind=='pricing':
            rows=[['Description','Qty','Rate','Amount (INR)']]
            for line in tax['lines']:
                if line['mode']=='UNIT_RATE' and not line['qty']:amount='Quantity pending'
                elif line['mode']=='AT_ACTUAL':amount='At actual (extra)'
                elif line['mode']=='EXCLUDED':amount='Excluded'
                elif line['mode']=='INCLUDED':amount='Included'
                elif line['mode']=='NOTE':amount='Breakdown only'
                else:amount=line['line_total'] or 'Pending'
                label=line['description']
                if line.get('tax_code'):label+=' (HSN/SAC '+line['tax_code']+')'
                rows.append([label,((line['qty'] or '')+' '+(line['unit'] or '')).strip()
                     if line['mode'] in ('FIXED','UNIT_RATE') else '',
                     line['price'] if line['mode'] in ('FIXED','UNIT_RATE') else '',amount])
            st.append(tbl(rows,[83*mm,24*mm,29*mm,36*mm]));st.append(Spacer(1,4*mm))
            st.append(P('Known priced subtotal (INR): '+tax['subtotal_known']))
            for item in tax['tax_components']:
                st.append(P(item['name']+' '+item['rate']+'%: INR '+item['amount']))
            st.append(P(('Known priced items incl. tax: ' if not tax['grand_total_definitive']
                else 'Total including tax: ')+'INR '+tax['known_total_including_tax']))
            if tax['additional_at_actual']:
                st.append(P('ADDITIONAL, NOT INCLUDED: '+', '.join(tax['additional_at_actual']),'IQSmall'))
            if tax['unpriced_lines']:
                st.append(P('INCOMPLETE PRICE LINES: this is not a complete all-inclusive total.','IQSmall'))
        elif kind=='terms':
            for key in ('scope','payment','delivery','warranty','inspection','transport','exclusions'):
                if terms.get(key):st.append(P(key.replace('_',' ').title()+': '+str(terms[key])))
        elif kind=='certifications':
            for item in terms.get('certifications',[]):
                if isinstance(item,dict):
                    st.append(P(str(item.get('name',''))+': '+str(item.get('condition',''))))
                else:st.append(P(str(item)))
            if not terms.get('certifications'):st.append(P('No additional documents specified.','IQSmall'))
    if layout.get('closing'):st.extend([Spacer(1,3*mm),P(substitute(layout['closing']))])
    if brand.get('signature_title'):st.append(P(brand['signature_title'],'IQSmall'))
    if not firm:st.append(P('INTERNAL PREVIEW ONLY - NOT AUTHORIZED FOR CUSTOMER ISSUE','IQSmall'))
    else:st.append(P('Approved for commercial issue. Technical certification requires independent verification.','IQSmall'))
    def footer(c,document):
        c.saveState();c.setFont('Helvetica',8);c.setFillColor(colors.grey)
        c.drawString(17*mm,11*mm,substitute(layout.get('footer',''))[:100])
        c.drawRightString(196*mm,11*mm,'Page '+str(document.page))
        if not firm:
            c.translate(A4[0]/2,A4[1]/2);c.rotate(45)
            c.setFont('Helvetica-Bold',28)
            c.setFillColor(colors.Color(.75,.15,.15,alpha=.14))
            c.drawCentredString(0,0,'DRAFT - NOT FOR ISSUE')
        c.restoreState()
    d.build(st,onFirstPage=footer,onLaterPages=footer)
    return pdf.getvalue()


@app.get('/api/projects/{pid}/commercial/preview.pdf')
def preview_commercial(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    p=get_project(db,pid);state=commercial_overview(db,p)
    if not state:raise HTTPException(404,'Commercial workflow not enabled')
    require_contact(state['profile'])
    from .templates import get_template
    chosen=get_template(db,state['profile']['template'])
    if not chosen:raise HTTPException(409,'Selected template does not exist')
    from .word_quote_templates import asset_for,context_for,render_asset_pdf
    word_asset=asset_for(db,chosen)
    body=(render_asset_pdf(word_asset,context_for(p,state['profile'],state,db=db))
          if word_asset else render_pdf(p,state['profile'],state,False,layout=json.loads(chosen.layout_json)))
    return Response(body,media_type='application/pdf',headers={'Cache-Control':'no-store'})


DOCX_MEDIA='application/vnd.openxmlformats-officedocument.wordprocessingml.document'


@app.get('/api/projects/{pid}/commercial/preview.docx')
def preview_commercial_word(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    """Editable download with the current approved/provisional customer fields (never internal costs)."""
    p=get_project(db,pid);state=commercial_overview(db,p)
    if not state:raise HTTPException(404,'Customer quotation workflow not enabled')
    require_contact(state['profile'])
    from .templates import get_template
    from .docx_exports import export_word
    chosen=get_template(db,state['profile']['template'])
    if not chosen:raise HTTPException(409,'Selected quotation format no longer exists')
    body=export_word(p,state['profile'],state,chosen,db)
    return Response(body,media_type=DOCX_MEDIA,headers={
        'Cache-Control':'no-store',
        'Content-Disposition':'attachment; filename="'+p.ref.replace('"','')+'-draft.docx"',
        'X-Content-Type-Options':'nosniff'})


@app.post('/api/projects/{pid}/commercial/issue')
def issue_commercial(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .app import require_role
    require_role(user,'commercial')
    p=get_project(db,pid);state=commercial_overview(db,p)
    if not state:raise HTTPException(409,'Enable customer quotation workflow')
    require_contact(state['profile'])
    if not state['gates']['firm_ready']:
        raise HTTPException(409,'Cannot issue: resolve critical requirements, pricing, taxes and approvals first')
    past=db.scalars(select(IssuedQuote).where(IssuedQuote.project_id==pid).order_by(IssuedQuote.id.desc())).all()
    ref=state['profile']['external_reference'] or p.ref
    number=ref+'-R'+f'{len(past)+1:02d}'
    from .templates import get_template
    chosen=get_template(db,state['profile']['template'])
    if not chosen:raise HTTPException(409,'Selected template does not exist')
    from .word_quote_templates import asset_for,context_for,render_asset_pdf
    from .docx_exports import export_word
    word_asset=asset_for(db,chosen)
    body=(render_asset_pdf(word_asset,context_for(p,state['profile'],state,firm=True,number=number,db=db))
          if word_asset else render_pdf(p,state['profile'],state,True,number,layout=json.loads(chosen.layout_json)))
    word_body=export_word(p,state['profile'],state,chosen,db,firm=True,number=number)
    filename=secrets.token_hex(24)+'.pdf';word_filename=secrets.token_hex(24)+'.docx'
    (PRIVATE_DIR/filename).write_bytes(body)
    try:
        (PRIVATE_DIR/word_filename).write_bytes(word_body)
    except Exception:
        (PRIVATE_DIR/filename).unlink(missing_ok=True)
        raise
    db.add(IssuedQuote(project_id=pid,number=number,snapshot=json.dumps({'project':project_json(p),
        'commercial':state,'template_code':chosen.code,'template_version':chosen.version,
        'template_layout':json.loads(chosen.layout_json),'word_layout_checksum':word_asset.checksum if word_asset else None,
        'docx_stored_name':word_filename,'docx_sha256':hashlib.sha256(word_body).hexdigest()},default=str),
        stored_name=filename,checksum=hashlib.sha256(body).hexdigest(),issued_by=user.id))
    p.status='ISSUED';record(db,user,'COMMERCIAL_QUOTE_ISSUED',pid,{'number':number});db.commit()
    return commercial_overview(db,p)


@app.get('/api/projects/{pid}/commercial/issued/{iid}.docx')
def issued_commercial_word(pid:int,iid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    """Download the frozen, editable Word snapshot associated with an issued PDF."""
    from fastapi.responses import FileResponse
    get_project(db,pid)
    quote=db.scalar(select(IssuedQuote).where(IssuedQuote.project_id==pid,IssuedQuote.id==iid))
    if not quote:raise HTTPException(404,'Issued quotation not found')
    snapshot=js(quote.snapshot,{})
    word_name=snapshot.get('docx_stored_name')
    if not word_name:raise HTTPException(404,'This historical issue predates editable Word snapshots. Use the draft Word export for the current data.')
    path=PRIVATE_DIR / word_name
    if not path.is_file():raise HTTPException(404,'Archived Word document missing')
    return FileResponse(path,media_type=DOCX_MEDIA,
        filename=quote.number.replace('/','-')+'.docx',
        content_disposition_type='attachment',
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
