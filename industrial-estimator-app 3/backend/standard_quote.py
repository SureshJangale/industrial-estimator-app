"""Shared quotation output for the single cost-plus estimation workflow.

This module does NOT create a second pricing model. Cost-plus order_value is
its sole numeric selling-price source. Quotation identity, tax, contact and
layout are separately configurable on all cost-plus projects (old and new).
Archived commercial projects retain their historical model unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, HTTPException
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from .app import (Base, app, engine, db_session, current_user, User, Project,
                  IssuedQuote, PRIVATE_DIR, get_project, compute, checks,
                  project_json, overview, record, utcnow, require_role, dec)
from .company_settings import branding_for
from .app import pack_records, get_config, config_dict
from .commercial import contact_is_named, require_contact
from .templates import get_default, get_template
from .word_quote_templates import asset_for, context_for, render_asset_pdf
from .docx_exports import export_word
from .commercial import render_pdf as layout_pdf


class StandardQuotation(Base):
    __tablename__ = 'standard_quotation_settings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), unique=True, index=True)
    template: Mapped[str] = mapped_column(String(64))
    tax_config: Mapped[str] = mapped_column(Text, default='{}')
    terms: Mapped[str] = mapped_column(Text, default='{}')
    branding: Mapped[str] = mapped_column(Text, default='{}')
    external_reference: Mapped[str] = mapped_column(String(60), default='')
    updated_at: Mapped[object] = mapped_column(DateTime, default=utcnow)


Base.metadata.create_all(engine)  # additive schema, no destructive migration
DOCX_MEDIA = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
CENT = Decimal('.01')


def settings_for(db, pid):
    return db.scalar(select(StandardQuotation).where(StandardQuotation.project_id == pid))


def init_settings(db, p):
    existing = settings_for(db, p.id)
    if existing:
        return existing
    # Default source is admin-selected company and Quote 73 layout, not a
    # specific company's identity hardcoded into the quotation engine.
    chosen = get_default(db, 'equipment_supply')
    q = StandardQuotation(project_id=p.id, template=chosen.code,
        tax_config=json.dumps({'mode':'EXCLUSIVE', 'status':'PENDING', 'components':[],
                               'basis_note':'Requires review by accounting/commercial'}),
        terms=json.dumps({'customer_attention':'', 'customer_address':'',
            'scope':p.scope, 'delivery':p.delivery, 'payment':p.payment_terms,
            'exclusions':p.exclusions, 'validity_days':p.validity_days,
            'product_unit':'Nos.', 'quotation_line_description':p.title,
            'warranty':'', 'inspection':'', 'transport':'', 'certifications':[]},
            ensure_ascii=False),
        branding=json.dumps(branding_for(db), ensure_ascii=False))
    db.add(q)
    db.flush()
    return q


def _parse(s, fallback):
    try:
        return json.loads(s or '')
    except (TypeError, ValueError):
        return fallback


def profile_data(q):
    return {'template':q.template, 'tax_config':_parse(q.tax_config, {}),
        'terms':_parse(q.terms, {}), 'branding':_parse(q.branding, {}),
        'external_reference':q.external_reference, 'technical':[]}


def quote_fingerprint(q, db=None):
    """Include live template versions and quotation settings in approval signatures."""
    result={'template':q.template, 'terms':_parse(q.terms, {}),
            'branding':_parse(q.branding, {}), 'tax_config':_parse(q.tax_config, {}),
            'external_reference':q.external_reference}
    if db is not None:
        template=get_template(db, q.template)
        result['template_version']=template.version if template else None
        result['template_layout']=template.layout_json if template else None
        word=asset_for(db,template) if template else None
        result['template_docx_checksum']=word.checksum if word else None
    return result


def _terms_ok(terms):
    return all(str(terms.get(k) or '').strip().lower() not in
               ('', 'to be agreed', 'to be confirmed', 'tbd')
               for k in ('delivery','payment'))


def quote_state(db, p):
    q = settings_for(db, p.id)
    if q is None:
        # Old cost-plus projects (e.g. seeded pallet) gain the same quotation
        # controls without touching their BOM, operations, pricing or history.
        q = init_settings(db, p)
        db.commit()
    profile = profile_data(q)
    # One source of truth for specifications: the reviewed Requirements tab.
    # The same values appear in Quote 73, Word and declarative PDF layouts.
    reqs, _, _, _ = pack_records(db, p)
    bykey = {r.field_key:r for r in reqs}
    cfg = config_dict(get_config(db, p.product_code))
    sections = cfg.get('specification_sections') or [{
        'id':'general', 'title':'Technical specification',
        'fields':cfg.get('required_fields',[])}]
    profile['technical'] = [{
        'id':sec.get('id','general'), 'title':sec.get('title','Technical specification'),
        'fields':[{'key':f.get('key',''), 'label':f.get('label',f.get('key','')),
                   'unit':f.get('unit',''),
                   'value':bykey[f['key']].value if f.get('key') in bykey else '',
                   'evidence':bykey[f['key']].evidence if f.get('key') in bykey else '',
                   'review_status':bykey[f['key']].status if f.get('key') in bykey else 'PENDING'}
                  for f in sec.get('fields',[])]} for sec in sections]
    calc = compute(db, p)
    cost_gates = checks(db, p, calc)
    terms = profile['terms']; tax = profile['tax_config']
    subtotal = Decimal(calc['order_value'])
    qty = max(1, int(p.quantity))
    taxes = []
    total_tax = Decimal('0')
    for component in tax.get('components', []):
        rate = dec(component['rate'], 'tax percent', 0, 100)
        amount = (subtotal*rate/100).quantize(CENT, rounding=ROUND_HALF_UP)
        taxes.append({'name':component['name'], 'rate':str(rate), 'amount':str(amount)})
        total_tax += amount
    subtotal = subtotal.quantize(CENT)
    has_tax_approval = tax.get('status') == 'APPROVED'
    contact_ok = contact_is_named(profile)
    template = get_template(db, q.template)
    template_ok = template is not None
    terms_ok = _terms_ok(terms)
    ready = bool(cost_gates['firm_ready'] and has_tax_approval and contact_ok and template_ok and terms_ok)
    missing = []
    if not cost_gates['firm_ready']:missing.append('Cost-plus engineering, rates and release approvals')
    if not has_tax_approval:missing.append('Tax calculation and accountant/commercial confirmation')
    if not contact_ok:missing.append('Named customer contact person (Kind Attendance)')
    if not terms_ok:missing.append('Payment and delivery terms')
    if not template_ok:missing.append('Selected quotation format')
    description = str(terms.get('quotation_line_description') or p.title).strip()
    unit = str(terms.get('product_unit') or 'Nos.').strip()
    line = {'id':None, 'ordinal':10, 'description':description, 'mode':'UNIT_RATE',
        'qty':str(qty), 'unit':unit, 'price':calc['unit_price'],
        'line_total':str(subtotal), 'tax_applicable':True,
        'tax_code':'', 'notes':'Derived from internal approved cost-plus estimate'}
    pricing = {'lines':[line], 'subtotal_known':str(subtotal),
        'taxable_subtotal':str(subtotal), 'tax_components':taxes,
        'tax_amount':str(total_tax), 'known_total_including_tax':str(subtotal+total_tax),
        'grand_total_definitive':bool(ready), 'tax_status':tax.get('status','PENDING'),
        'additional_at_actual':[], 'unpriced_lines':[]}
    return {'profile':profile, 'pricing':pricing, 'gates':{
        'firm_ready':ready, 'cost_plus_approved':cost_gates['firm_ready'],
        'tax_approved':has_tax_approval, 'customer_contact_confirmed':contact_ok,
        'terms_complete':terms_ok, 'template_valid':template_ok, 'missing':missing}}


class QuotationUpdate(BaseModel):
    template: str | None = None
    tax_config: dict | None = None
    terms: dict | None = None
    branding: dict | None = None
    external_reference: str | None = Field(default=None, max_length=60)


@app.get('/api/projects/{pid}/quotation')
def get_quote(pid:int, db:Session=Depends(db_session), user:User=Depends(current_user)):
    p = get_project(db, pid)
    from .commercial import profile_for
    if profile_for(db, pid):
        raise HTTPException(409, 'Historical commercial quotation: use its existing archived controls')
    return quote_state(db, p)


@app.put('/api/projects/{pid}/quotation')
def update_quote(pid:int, data:QuotationUpdate,
                 db:Session=Depends(db_session), user:User=Depends(current_user)):
    require_role(user, 'estimator', 'commercial')
    p = get_project(db, pid)
    from .commercial import profile_for
    if profile_for(db, pid):
        raise HTTPException(409, 'This historical project uses its archived quotation configuration')
    q = init_settings(db, p)
    if data.template is not None:
        if not get_template(db, data.template):
            raise HTTPException(422, 'Choose an available quotation format')
        q.template = data.template
    if data.terms is not None:
        terms = data.terms
        if len(json.dumps(terms)) > 15000:
            raise HTTPException(422, 'Quotation terms are too long')
        if str(terms.get('customer_attention') or '').strip() and not contact_is_named({'terms':terms}):
            raise HTTPException(422, 'Contact must name an actual person, not Purchase Team')
        unit = str(terms.get('product_unit') or 'Nos.').strip()
        if not re.fullmatch(r'[\w][\w ./%+-]{0,23}', unit):
            raise HTTPException(422, 'Enter a valid quotation quantity unit')
        if len(str(terms.get('quotation_line_description') or '')) > 500:
            raise HTTPException(422, 'Quotation description must be under 500 characters')
        if terms.get('validity_days') is not None:
            dec(terms['validity_days'], 'validity days', 1, 365)
        q.terms = json.dumps(terms, ensure_ascii=False)
    if data.tax_config is not None:
        tax = data.tax_config
        if tax.get('mode', 'EXCLUSIVE') != 'EXCLUSIVE':
            raise HTTPException(422, 'Only explicitly tax-exclusive quotations supported')
        items = tax.get('components', [])
        if not isinstance(items, list) or len(items) > 6:
            raise HTTPException(422, 'Use up to six tax components')
        for item in items:
            if not isinstance(item, dict) or not str(item.get('name') or '').strip():
                raise HTTPException(422, 'Each tax needs a name')
            dec(item.get('rate'), 'tax %', 0, 100)
        if tax.get('status') == 'APPROVED':
            if tax != _parse(q.tax_config, {}):
                require_role(user, 'commercial', 'procurement')
            if not str(tax.get('basis_note') or '').strip():
                raise HTTPException(422, 'Provide an accountant-approved tax basis')
        else:
            tax['status'] = 'PENDING'
        q.tax_config = json.dumps(tax, ensure_ascii=False)
    if data.branding is not None:
        if len(json.dumps(data.branding)) > 5000:
            raise HTTPException(422, 'Seller branding too long')
        q.branding = json.dumps(data.branding, ensure_ascii=False)
    if data.external_reference is not None:
        q.external_reference = data.external_reference.strip()
    q.updated_at = utcnow();p.status = 'DRAFT';p.updated_at = utcnow()
    record(db, user, 'STANDARD_QUOTATION_UPDATED', pid)
    db.commit()
    return quote_state(db, p)


@app.post('/api/projects/{pid}/quotation/apply-company-profile')
def apply_company(pid:int, db:Session=Depends(db_session), user:User=Depends(current_user)):
    require_role(user, 'estimator', 'commercial')
    p = get_project(db, pid)
    from .commercial import profile_for
    if profile_for(db, pid):
        raise HTTPException(409, 'This historical project has archived commercial settings')
    q = init_settings(db, p)
    q.branding = json.dumps(branding_for(db), ensure_ascii=False)
    q.updated_at = utcnow();p.status = 'DRAFT'
    record(db, user, 'STANDARD_QUOTATION_BRANDING_REFRESHED', pid)
    db.commit()
    return quote_state(db, p)


def _generate(db, p, state, firm=False, number=None):
    selected = get_template(db, state['profile']['template'])
    if not selected:
        raise HTTPException(409, 'Quotation format no longer exists')
    word_asset = asset_for(db, selected)
    if word_asset:
        ctx = context_for(p, state['profile'], state, firm=firm, number=number, db=db)
        pdf = render_asset_pdf(word_asset, ctx)
    else:
        pdf = layout_pdf(p, state['profile'], state, firm=firm, number=number,
                         layout=json.loads(selected.layout_json))
    docx = export_word(p, state['profile'], state, selected, db, firm=firm, number=number)
    return pdf, docx, selected


@app.get('/api/projects/{pid}/quotation/preview.pdf')
def preview_pdf(pid:int, db:Session=Depends(db_session), user:User=Depends(current_user)):
    p = get_project(db, pid)
    from .commercial import profile_for
    if profile_for(db, pid):raise HTTPException(409, 'Use historical commercial export for this archived project')
    state = quote_state(db, p)
    require_contact(state['profile'])
    pdf, _, _ = _generate(db, p, state)
    return Response(pdf, media_type='application/pdf', headers={'Cache-Control':'no-store',
        'Content-Disposition':f'inline; filename="{p.ref}-draft.pdf"'})


@app.get('/api/projects/{pid}/quotation/preview.docx')
def preview_word(pid:int, db:Session=Depends(db_session), user:User=Depends(current_user)):
    p = get_project(db, pid)
    from .commercial import profile_for
    if profile_for(db, pid):raise HTTPException(409, 'Use historical commercial export for this archived project')
    state = quote_state(db, p)
    require_contact(state['profile'])
    selected = get_template(db, state['profile']['template'])
    if not selected:raise HTTPException(409, 'Selected quotation format no longer exists')
    word = export_word(p, state['profile'], state, selected, db)
    return Response(word, media_type=DOCX_MEDIA, headers={'Cache-Control':'no-store',
        'Content-Disposition':f'attachment; filename="{p.ref}-draft.docx"',
        'X-Content-Type-Options':'nosniff'})


def issue_standard(pid, db, user):
    p = get_project(db, pid)
    state = quote_state(db, p)
    require_contact(state['profile'])
    if not state['gates']['firm_ready']:
        raise HTTPException(409, 'Firm quotation blocked: '+', '.join(state['gates']['missing']))
    past = db.scalars(select(IssuedQuote).where(IssuedQuote.project_id==pid)).all()
    base = state['profile']['external_reference'] or p.ref
    number = base + '-R' + f'{len(past)+1:02d}'
    pdf, word, selected = _generate(db, p, state, firm=True, number=number)
    pdf_name = secrets.token_hex(24)+'.pdf'
    docx_name = secrets.token_hex(24)+'.docx'
    (PRIVATE_DIR/pdf_name).write_bytes(pdf)
    try:(PRIVATE_DIR/docx_name).write_bytes(word)
    except Exception:
        (PRIVATE_DIR/pdf_name).unlink(missing_ok=True)
        raise
    snapshot = {'project':project_json(p), 'quote_settings':state,
                'estimate':compute(db,p), 'approval_gates':checks(db,p),
                'template_code':selected.code, 'template_version':selected.version,
                'docx_stored_name':docx_name, 'docx_sha256':hashlib.sha256(word).hexdigest()}
    db.add(IssuedQuote(project_id=pid, number=number, snapshot=json.dumps(snapshot, default=str),
                       stored_name=pdf_name, checksum=hashlib.sha256(pdf).hexdigest(), issued_by=user.id))
    p.status = 'ISSUED'
    record(db, user, 'COST_PLUS_QUOTATION_ISSUED', pid, {'number':number})
    db.commit()
    return overview(db, p)


@app.get('/api/projects/{pid}/issued/{iid}.docx')
def issued_word(pid:int, iid:int, db:Session=Depends(db_session), user:User=Depends(current_user)):
    get_project(db, pid)
    quote = db.scalar(select(IssuedQuote).where(IssuedQuote.id==iid, IssuedQuote.project_id==pid))
    if not quote:raise HTTPException(404,'Quotation missing')
    snap = _parse(quote.snapshot, {})
    word_name = snap.get('docx_stored_name')
    if not word_name:
        raise HTTPException(404, 'This older quotation did not archive an editable Word file')
    path = PRIVATE_DIR / word_name
    if not path.is_file():raise HTTPException(404, 'Archived editable Word file missing')
    return FileResponse(path, media_type=DOCX_MEDIA, filename=quote.number.replace('/','-')+'.docx',
                        headers={'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'})
