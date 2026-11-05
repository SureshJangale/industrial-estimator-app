"""Safe, versioned, JSON-configured customer quotation templates.

Admin-defined templates are declarative data. Uploaded JSON is validated and never
executed as HTML, JavaScript, Python, or ReportLab markup. Built-in templates are
immutable; admins customize by duplicating them.
"""
from __future__ import annotations
import json
import re
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from typing import Literal

from fastapi import Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from .app import Base, app, engine, db_session, current_user, require_role, User, record, utcnow

WORKFLOWS = {'equipment_supply','service_repair','general_sale'}
SECTIONS = ('technical', 'pricing', 'terms', 'certifications')
DEFAULTS = [
    ('multi_annexure','Classic equipment | multi-annexure','equipment_supply',
     {'title':'TECHNO-COMMERCIAL OFFER','tagline':'Engineering | Manufacturing | Services',
      'primary_color':'#17344C','accent_color':'#087E75',
      'intro':'We are pleased to submit our technical and commercial offer for {project}.',
      'closing':'Thank you for considering our proposal.',
      'footer':'Quotation is valid only when approved and issued by the authorized commercial signatory.',
      'format_style':'classic_equipment','sections':[{'key':'technical','title':'ANNEXURE A - TECHNICAL SPECIFICATION','enabled':True},
                  {'key':'pricing','title':'ANNEXURE B - PRICE SCHEDULE','enabled':True},
                  {'key':'certifications','title':'CERTIFICATIONS AND DOCUMENTS','enabled':True},
                  {'key':'terms','title':'ANNEXURE C - COMMERCIAL TERMS','enabled':True}]}),
    ('short_service','Classic service | itemized one-page','service_repair',
     {'title':'REPAIR AND SERVICE QUOTATION','tagline':'Service | Maintenance | Repair',
      'primary_color':'#17344C','accent_color':'#087E75',
      'intro':'We are pleased to offer the following work and service charges.',
      'closing':'We look forward to your confirmation.',
      'footer':'Please refer to the approved commercial terms and service scope.',
      'format_style':'classic_service','sections':[{'key':'pricing','title':'WORK AND CHARGES','enabled':True},
                  {'key':'terms','title':'COMMERCIAL TERMS','enabled':True},
                  {'key':'certifications','title':'SUPPORTING DOCUMENTS','enabled':True}]}),
    ('simple_sales','General - Simple quotation','general_sale',
     {'title':'QUOTATION','tagline':'Supply | Services',
      'primary_color':'#17344C','accent_color':'#087E75',
      'intro':'Please find our quotation below.','closing':'Thank you for your enquiry.',
      'footer':'This quotation is subject to the terms listed above.',
      'format_style':'modern','sections':[{'key':'pricing','title':'PRICE SCHEDULE','enabled':True},
                  {'key':'terms','title':'TERMS AND CONDITIONS','enabled':True},
                  {'key':'certifications','title':'DOCUMENTS','enabled':False}]})
]


class QuoteTemplate(Base):
    __tablename__='quote_templates'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    code: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    name: Mapped[str]=mapped_column(String(150))
    workflow: Mapped[str]=mapped_column(String(40))
    layout_json: Mapped[str]=mapped_column(Text)
    version: Mapped[int]=mapped_column(Integer,default=1)
    is_builtin: Mapped[bool]=mapped_column(Boolean,default=False)
    is_default: Mapped[bool]=mapped_column(Boolean,default=False)
    created_by: Mapped[int | None]=mapped_column(ForeignKey('users.id'),nullable=True)
    created_at: Mapped[object]=mapped_column(DateTime,default=utcnow)
    updated_at: Mapped[object]=mapped_column(DateTime,default=utcnow)


class TemplateRevision(Base):
    __tablename__='quote_template_revisions'
    id: Mapped[int]=mapped_column(Integer,primary_key=True)
    template_id: Mapped[int]=mapped_column(ForeignKey('quote_templates.id'))
    version: Mapped[int]=mapped_column(Integer)
    layout_json: Mapped[str]=mapped_column(Text)
    name: Mapped[str]=mapped_column(String(150))
    edited_by: Mapped[int | None]=mapped_column(ForeignKey('users.id'),nullable=True)
    changed_at: Mapped[object]=mapped_column(DateTime,default=utcnow)


Base.metadata.create_all(engine)


def bootstrap_templates():
    from .app import SessionLocal
    with SessionLocal() as db:
        for code,name,workflow,layout in DEFAULTS:
            existing=db.scalar(select(QuoteTemplate).where(QuoteTemplate.code==code))
            if not existing:
                db.add(QuoteTemplate(code=code,name=name,workflow=workflow,
                    layout_json=json.dumps(layout),version=1,is_builtin=True,is_default=True))
            elif existing.is_builtin and json.loads(existing.layout_json).get('format_style') != layout.get('format_style'):
                # Built-in layout upgrade only; leave customer-authored custom templates unchanged.
                db.add(TemplateRevision(template_id=existing.id,version=existing.version,
                    layout_json=existing.layout_json,name=existing.name,edited_by=None))
                existing.layout_json=json.dumps(layout)
                existing.name=name
                existing.version+=1
        db.commit()


bootstrap_templates()


def valid_layout(raw:dict) -> dict:
    """Permit only a small, documented set of layout choices; no dynamic code."""
    if not isinstance(raw,dict):raise HTTPException(422,'Template layout must be a JSON object')
    allowed={'title','tagline','primary_color','accent_color','intro','closing','footer','sections','format_style'}
    if set(raw)-allowed:raise HTTPException(422,'Unsupported layout keys: '+', '.join(sorted(set(raw)-allowed)))
    out={}
    for name,max_len in [('title',120),('tagline',150),('intro',700),('closing',700),('footer',350)]:
        s=raw.get(name,'')
        if not isinstance(s,str) or len(s)>max_len:raise HTTPException(422,name+' must be text of at most '+str(max_len)+' characters')
        out[name]=s
    for name in ['primary_color','accent_color']:
        s=raw.get(name,'#17344C' if name=='primary_color' else '#087E75')
        if not isinstance(s,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',s):
            raise HTTPException(422,name+' must be a 6-digit hex colour')
        out[name]=s
    sections=raw.get('sections')
    if not isinstance(sections,list) or not sections or len(sections)>len(SECTIONS):
        raise HTTPException(422,'Sections must be a nonempty array of no more than four supported sections')
    result=[];seen=set()
    for section in sections:
        if not isinstance(section,dict) or set(section)-{'key','title','enabled'}:
            raise HTTPException(422,'Invalid section definition')
        key=section.get('key')
        if key not in SECTIONS or key in seen:raise HTTPException(422,'Unknown or duplicate section')
        seen.add(key)
        title=section.get('title',key.title())
        if not isinstance(title,str) or not (2<=len(title)<=110):raise HTTPException(422,'Section headings must be 2-110 characters')
        if not isinstance(section.get('enabled',True),bool):raise HTTPException(422,'Section enabled must be boolean')
        result.append({'key':key,'title':title,'enabled':section.get('enabled',True)})
    if not all(any(x['key']==k and x['enabled'] for x in result) for k in ('pricing','terms')):
        raise HTTPException(422,'Price schedule and commercial terms must remain visible')
    out['sections']=result
    out['format_style']=raw.get('format_style','modern')
    if out['format_style'] not in ('modern','classic_equipment','classic_service'):
        raise HTTPException(422,'Choose a supported quotation layout: modern, classic_equipment or classic_service')
    # A classic layout may be selected only for its matching workflow at create/update time.
    # Bound aggregate size to avoid PDF denial-of-service through templates.
    if len(json.dumps(out))>4500:raise HTTPException(422,'Template is too large')
    return out


def get_template(db,code:str) -> QuoteTemplate | None:
    return db.scalar(select(QuoteTemplate).where(QuoteTemplate.code==code))


def get_default(db,workflow:str) -> QuoteTemplate:
    value=db.scalar(select(QuoteTemplate).where(QuoteTemplate.workflow==workflow,QuoteTemplate.is_default==True))
    if value:return value
    return get_template(db,{'service_repair':'short_service','equipment_supply':'multi_annexure',
                           'general_sale':'simple_sales'}[workflow])


def public(t:QuoteTemplate) -> dict:
    from .word_quote_templates import asset_for
    from .app import SessionLocal
    with SessionLocal() as tmp:
        asset=asset_for(tmp,t)
        source='docx' if asset else 'json'
        fields=json.loads(asset.fields_json) if asset else []
    return {'code':t.code,'name':t.name,'workflow':t.workflow,
       'layout':json.loads(t.layout_json),'version':t.version,
       'source_type':source,'placeholders':fields,
       'is_builtin':t.is_builtin,'is_default':t.is_default,'updated_at':str(t.updated_at)}


class TemplateCreate(BaseModel):
    code:str=Field(pattern=r'^[a-z][a-z0-9_]{2,63}$')
    name:str=Field(min_length=3,max_length=150)
    workflow:Literal['equipment_supply','service_repair','general_sale']
    layout:dict


class TemplateEdit(BaseModel):
    name:str=Field(min_length=3,max_length=150)
    layout:dict


def save_template(db,user,payload,old=None):
    normalized=valid_layout(payload.layout)
    workflow=old.workflow if old else payload.workflow
    if normalized['format_style']=='classic_equipment' and workflow!='equipment_supply':
        raise HTTPException(422,'Traditional equipment layout requires equipment_supply workflow')
    if normalized['format_style']=='classic_service' and workflow!='service_repair':
        raise HTTPException(422,'Traditional service layout requires service_repair workflow')
    if old:
        from .word_quote_templates import asset_for
        if asset_for(db,old):raise HTTPException(409,'Replace the uploaded Word file instead of using the JSON editor')
        if old.is_builtin:raise HTTPException(403,'Duplicate a built-in template to customize it')
        db.add(TemplateRevision(template_id=old.id,version=old.version,
            layout_json=old.layout_json,name=old.name,edited_by=user.id))
        old.name=payload.name;old.layout_json=json.dumps(normalized,ensure_ascii=False)
        old.version+=1;old.updated_at=utcnow()
        result=old;action='QUOTE_TEMPLATE_UPDATED'
    else:
        if get_template(db,payload.code):raise HTTPException(409,'Template code already exists')
        result=QuoteTemplate(code=payload.code,name=payload.name,workflow=payload.workflow,
            layout_json=json.dumps(normalized,ensure_ascii=False),created_by=user.id,
            is_builtin=False,is_default=False)
        db.add(result);action='QUOTE_TEMPLATE_CREATED'
    record(db,user,action,detail={'code':result.code,'version':result.version})
    db.commit();return public(result)


@app.get('/api/quote-templates')
def list_quote_templates(db:Session=Depends(db_session),user:User=Depends(current_user)):
    return [public(x) for x in db.scalars(select(QuoteTemplate).order_by(QuoteTemplate.workflow,QuoteTemplate.name)).all()]


@app.post('/api/quote-templates')
def create_quote_template(data:TemplateCreate,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'admin')
    return save_template(db,user,data)


@app.put('/api/quote-templates/{code}')
def edit_quote_template(code:str,data:TemplateEdit,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'admin')
    t=get_template(db,code)
    if not t:raise HTTPException(404,'Unknown template')
    return save_template(db,user,data,t)


@app.post('/api/quote-templates/import')
async def import_quote_template(file:UploadFile=File(...),db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'admin')
    if not file.filename or not file.filename.lower().endswith('.json'):
        raise HTTPException(422,'Upload a JSON template definition (.json)')
    blob=await file.read(32_001)
    if len(blob)>32_000:raise HTTPException(413,'Template file exceeds 32 KB')
    try:
        raw=json.loads(blob.decode('utf-8-sig'))
        parsed=TemplateCreate.model_validate(raw)
    except Exception:
        raise HTTPException(422,'JSON must contain a valid code, name, workflow and layout')
    return save_template(db,user,parsed)


@app.post('/api/quote-templates/{code}/default')
def make_default_quote_template(code:str,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'admin')
    t=get_template(db,code)
    if not t:raise HTTPException(404,'Unknown template')
    for x in db.scalars(select(QuoteTemplate).where(QuoteTemplate.workflow==t.workflow)).all():
        x.is_default=(x.id==t.id)
    record(db,user,'QUOTE_TEMPLATE_DEFAULT_CHANGED',detail={'code':code,'workflow':t.workflow})
    db.commit();return {'default':public(t)}


@app.get('/api/quote-templates/{code}/export.json')
def export_quote_template(code:str,db:Session=Depends(db_session),user:User=Depends(current_user)):
    t=get_template(db,code)
    if not t:raise HTTPException(404,'Unknown template')
    obj={'code':t.code,'name':t.name,'workflow':t.workflow,'layout':json.loads(t.layout_json)}
    return Response(json.dumps(obj,indent=2,ensure_ascii=False),media_type='application/json',
      headers={'Content-Disposition':f'attachment; filename="{t.code}.json"','Cache-Control':'no-store'})


@app.get('/api/quote-templates/{code}/history')
def quote_template_history(code:str,db:Session=Depends(db_session),user:User=Depends(current_user)):
    t=get_template(db,code)
    if not t:raise HTTPException(404,'Unknown template')
    revs=db.scalars(select(TemplateRevision).where(TemplateRevision.template_id==t.id).order_by(TemplateRevision.version.desc())).all()
    return {'current':public(t),'past_versions':[{'version':r.version,'name':r.name,'layout':json.loads(r.layout_json),
       'changed_at':str(r.changed_at)} for r in revs]}


@app.get('/api/quote-templates/{code}/preview.pdf')
def preview_quote_template(code:str,db:Session=Depends(db_session),user:User=Depends(current_user)):
    """Only synthetic values: no customer data is used for standalone previews."""
    t=get_template(db,code)
    if not t:raise HTTPException(404,'Unknown template')
    from .word_quote_templates import asset_for,render_asset_pdf,synthetic_pallet_context,synthetic_quote73_context
    asset=asset_for(db,t)
    if asset:
        from .company_settings import branding_for
        return Response(render_asset_pdf(asset,synthetic_quote73_context(branding_for(db)) if t.code.startswith('quote73_') else synthetic_pallet_context()),
          media_type='application/pdf',headers={'Cache-Control':'no-store'})
    from .commercial import render_pdf
    kind=t.workflow
    if kind=='service_repair':
        demo=SimpleNamespace(ref='SAMPLE-REPAIR-041',customer='Sample Service Customer (synthetic)',
                            title='5-ton hoist motor repair - sample')
        lines=[{'description':'Hoist motor rewinding, rotor and shaft service',
                'notes':'Breakdown included: rewinding 21,500; rotor 16,000; shaft 2,000',
                'mode':'FIXED','qty':'1','unit':'nos','price':'39500','line_total':'39500.00','tax_code':'998717'},
               {'description':'Motor removing and refitting at site',
                'mode':'FIXED','qty':'1','unit':'nos','price':'6000','line_total':'6000.00','tax_code':'998717'}]
        tax=[{'name':'CGST','rate':'9','amount':'4095.00'},
             {'name':'SGST','rate':'9','amount':'4095.00'}]
        subtotal='45500.00';total='53690.00';actual=[];definitive=True
        technical=[]
        terms={'scope':'Repair and refitting of a customer-supplied motor',
               'payment':'Immediately after satisfactory completion',
               'delivery':'As agreed after inspection','warranty':'As separately agreed'}
    elif kind=='equipment_supply':
        demo=SimpleNamespace(ref='SAMPLE-EOT-047',customer='Sample Equipment Customer (synthetic)',
                            title='5-ton single-girder overhead crane - sample')
        lines=[{'description':'Single girder EOT crane, 5-ton SWL, 6 m lift, 8.6 m span',
                'mode':'FIXED','qty':'1','unit':'nos','price':'850000','line_total':'850000.00','tax_code':''},
               {'description':'Erection and commissioning',
                'mode':'FIXED','qty':'1','unit':'job','price':'25000','line_total':'25000.00','tax_code':''},
               {'description':'Transportation',
                'mode':'AT_ACTUAL','qty':'','unit':'','price':'','line_total':None,'tax_code':''}]
        tax=[{'name':'Illustrative GST (not approved)','rate':'18','amount':'157500.00'}]
        subtotal='875000.00';total='1032500.00';actual=['Transportation'];definitive=False
        technical=[{'title':'GENERAL', 'fields':[
              {'label':'Type','value':'Single girder overhead','unit':''},
              {'label':'Span','value':'8.6','unit':'m'},
              {'label':'Capacity','value':'5','unit':'t'},
              {'label':'Lift','value':'6','unit':'m'},
              {'label':'Service','value':'Indoor','unit':''}]},
              {'title':'HOIST AND TRAVEL','fields':[
              {'label':'Hoisting speed','value':'4','unit':'m/min'},
              {'label':'Hoist headroom','value':'800','unit':'mm'},
              {'label':'Minimum crane headroom','value':'450','unit':'mm'}]}]
        terms={'scope':'Supply one sample crane as described in Annexure A',
               'payment':'50% with order, 50% prior to dispatch',
               'delivery':'Four weeks after advance payment',
               'warranty':'Subject to signed commercial warranty schedule',
               'inspection':'At works, by mutual arrangement',
               'transport':'At actual / additional',
               'certifications':[{'name':'Material test certificates','condition':'On request'},
                                 {'name':'Operation manual','condition':'With supply'}]}
    else:
        demo=SimpleNamespace(ref='EXAMPLE-001',customer='Example Customer (synthetic)',
                             title='Sample fabricated equipment')
        lines=[{'description':'Fabricated assembly','mode':'FIXED',
                'qty':'1','unit':'each','price':'85000','line_total':'85000.00','tax_code':''}]
        tax=[{'name':'Illustrative tax','rate':'0','amount':'0.00'}]
        subtotal='85000.00';total='85000.00';actual=[];definitive=True
        technical=[]
        terms={'scope':'Manufacture and deliver the described work',
               'payment':'As mutually agreed','delivery':'Following approval of design'}
    from .company_defaults import fresh_branding
    terms['customer_attention']='Ms. Fictional Sample Contact'
    terms['customer_address']='Sample Industrial Area (synthetic)'
    profile={'template':t.code,'branding':fresh_branding(),
             'terms':terms, 'technical':technical, 'external_reference':demo.ref}
    calc={'pricing':{'lines':lines,'subtotal_known':subtotal,'tax_components':tax,
           'known_total_including_tax':total,'additional_at_actual':actual,
           'unpriced_lines':[],'grand_total_definitive':definitive}}
    return Response(render_pdf(demo,profile,calc,False,layout=json.loads(t.layout_json)),
        media_type='application/pdf',headers={'Cache-Control':'no-store'})
