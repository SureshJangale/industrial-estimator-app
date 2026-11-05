"""Industrial Estimator: free, self-hosted modular-monolith MVP.

This application is an estimator and quotation workflow, not an engineering design tool.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader
from .extraction import local_document_text, extract_candidates as extract_generic_candidates, conflicts_from_docs
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, select, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parent.parent
DB_URL = os.getenv('DATABASE_URL') or f"sqlite:///{(ROOT / 'runtime' / 'estimator.db').as_posix()}"
PRIVATE_DIR = Path(os.getenv('PRIVATE_DIR') or ROOT / 'runtime' / 'files').resolve()
PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
IS_SQLITE = DB_URL.startswith('sqlite')
if os.getenv('APP_ENV') == 'production' and not os.getenv('APP_SECRET'):
    raise RuntimeError('APP_SECRET must be configured in production')
secret = os.getenv('APP_SECRET') or secrets.token_urlsafe(48)
serializer = URLSafeTimedSerializer(secret, salt='industrial-estimator-auth-v1')
connect_args = {'check_same_thread': False} if IS_SQLITE else {}
if DB_URL == 'sqlite://':
    engine = create_engine(DB_URL, connect_args=connect_args, poolclass=StaticPool)
else:
    engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
TOKEN_AGE_SECONDS = 8 * 60 * 60
MAX_UPLOAD = 15 * 1024 * 1024
MONEY = Decimal('0.01')
RATES_FIRM = {'SUPPLIER_APPROVED', 'INTERNAL_AUTHORIZED_RATE'}
Q_APPROVED = {'APPROVED'}
STATUS_OPTIONS = {'PUBLIC_BENCHMARK', 'DEMO_ASSUMPTION', 'RANGE_MIDPOINT', 'NON_MATCHED_SPEC_BENCHMARK', 'PROXY_ESTIMATE', 'SUPPLIER_APPROVED', 'INTERNAL_AUTHORIZED_RATE'}


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, default='')
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default='')
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RecoveryCode(Base):
    """One-time offline recovery codes, hashed at rest; never email them or log plaintext."""
    __tablename__ = 'account_recovery_codes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProductConfig(Base):
    __tablename__ = 'product_configs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    label: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(30))
    definition: Mapped[str] = mapped_column(Text)


class Price(Base):
    __tablename__ = 'prices'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(300))
    unit: Mapped[str] = mapped_column(String(16))
    rate: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(300), default='')
    vendor: Mapped[str] = mapped_column(String(200), default='')
    url: Mapped[str] = mapped_column(String(500), default='')
    valid_until: Mapped[str] = mapped_column(String(20), default='')
    profile: Mapped[str] = mapped_column(Text, default='{}')
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(180))
    customer: Mapped[str] = mapped_column(String(180))
    product_code: Mapped[str] = mapped_column(String(80))
    config_version: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    overhead_pct: Mapped[str] = mapped_column(String(24), default='8')
    contingency_pct: Mapped[str] = mapped_column(String(24), default='5')
    margin_pct: Mapped[str] = mapped_column(String(24), default='20')
    scope: Mapped[str] = mapped_column(Text, default='')
    exclusions: Mapped[str] = mapped_column(Text, default='')
    delivery: Mapped[str] = mapped_column(String(240), default='To be confirmed')
    payment_terms: Mapped[str] = mapped_column(String(240), default='To be agreed')
    validity_days: Mapped[int] = mapped_column(Integer, default=15)
    status: Mapped[str] = mapped_column(String(30), default='DRAFT')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id'), nullable=True)


class Requirement(Base):
    __tablename__ = 'requirements'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    field_key: Mapped[str] = mapped_column(String(90))
    value: Mapped[str] = mapped_column(Text, default='')
    unit: Mapped[str] = mapped_column(String(30), default='')
    status: Mapped[str] = mapped_column(String(20), default='PENDING')
    evidence: Mapped[str] = mapped_column(String(700), default='')
    document_id: Mapped[int | None] = mapped_column(ForeignKey('documents.id'), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BOMLine(Base):
    __tablename__ = 'bom_lines'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    sku: Mapped[str] = mapped_column(String(100))
    qty: Mapped[str] = mapped_column(String(30))
    unit: Mapped[str] = mapped_column(String(16))
    waste_pct: Mapped[str] = mapped_column(String(24), default='0')
    status: Mapped[str] = mapped_column(String(20), default='ASSUMED')
    note: Mapped[str] = mapped_column(Text, default='')


class Operation(Base):
    __tablename__ = 'operations'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    code: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(200))
    hours: Mapped[str] = mapped_column(String(30))
    rate: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default='ASSUMED')


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    original_name: Mapped[str] = mapped_column(String(240))
    stored_name: Mapped[str] = mapped_column(String(80))
    checksum: Mapped[str] = mapped_column(String(64))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default='')
    candidates: Mapped[str] = mapped_column(Text, default='[]')
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BOMVerification(Base):
    """Evidence-backed quantity approval; historical decisions are never overwritten."""
    __tablename__ = 'bom_verifications'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), nullable=False)
    bom_line_id: Mapped[int] = mapped_column(ForeignKey('bom_lines.id'), nullable=False)
    confirmed_qty: Mapped[str] = mapped_column(String(30), nullable=False)
    confirmed_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(380), nullable=False)
    verification_note: Mapped[str] = mapped_column(String(250), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CandidateReview(Base):
    """Durable bridge between source extraction and reviewed project data.

    Creating or updating a BOM entry is NOT equivalent to engineering approval.
    State is computed from the current linked row each time a project is opened.
    The table is additive for existing SQLite development databases.
    """
    __tablename__ = 'document_candidate_reviews'
    __table_args__ = (UniqueConstraint('document_id', 'candidate_index', name='uq_document_candidate_review'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'), nullable=False)
    candidate_index: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)  # LINKED or DISMISSED
    target_kind: Mapped[str] = mapped_column(String(30), default='')
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(500), default='')
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = 'approvals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    kind: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    fingerprint: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(String(600), default='')
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IssuedQuote(Base):
    __tablename__ = 'issued_quotes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'))
    number: Mapped[str] = mapped_column(String(50))
    snapshot: Mapped[str] = mapped_column(Text)
    stored_name: Mapped[str] = mapped_column(String(80))
    checksum: Mapped[str] = mapped_column(String(64))
    issued_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey('projects.id'), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default='{}')
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


Base.metadata.create_all(engine)


def migrate_account_columns():
    """Non-destructive additive migration for existing 0.8.3 SQLite/PostgreSQL databases."""
    cols = {column['name'] for column in inspect(engine).get_columns('users')}
    definitions = {
        'email': "VARCHAR(254) NOT NULL DEFAULT ''",
        'phone': "VARCHAR(32) NOT NULL DEFAULT ''",
        'auth_version': 'INTEGER NOT NULL DEFAULT 0',
        'must_change_password': 'BOOLEAN NOT NULL DEFAULT FALSE',
    }
    with engine.begin() as connection:
        for column, definition in definitions.items():
            if column not in cols:
                connection.exec_driver_sql(f'ALTER TABLE users ADD COLUMN {column} {definition}')


migrate_account_columns()
app = FastAPI(title='IndustriQuote - Configurable Industrial Estimator', version='0.8.4-dev', docs_url=None if os.getenv('APP_ENV') == 'production' else '/api/docs', openapi_url='/api/openapi.json')
bearer = HTTPBearer(auto_error=False)


def db_session():
    with SessionLocal() as db:
        yield db


def hashed_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    rounds = 390000
    derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, rounds)
    return f'pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(derived).decode()}'


def valid_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, expected = stored.split('$')
        got = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(got, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(db_session)):
    if not creds:
        raise HTTPException(status_code=401, detail='Sign in required')
    try:
        data = serializer.loads(creds.credentials, max_age=TOKEN_AGE_SECONDS)
        user = db.get(User, int(data['uid']))
    except (BadSignature, SignatureExpired, ValueError, KeyError):
        raise HTTPException(status_code=401, detail='Session expired')
    if not user or not user.active:
        raise HTTPException(status_code=401, detail='Invalid user')
    if int(data.get('v', 0)) != user.auth_version:
        raise HTTPException(status_code=401, detail='Session revoked; sign in again')
    change_allowed = (request.url.path in {'/api/me', '/api/profile/password'} or
                      (request.url.path == '/api/profile' and request.method == 'GET'))
    if user.must_change_password and not change_allowed:
        raise HTTPException(status_code=403, detail='Change your temporary password to continue')
    return user


def require_role(user: User, *roles: str):
    if user.role != 'admin' and user.role not in roles:
        raise HTTPException(status_code=403, detail=f'Requires role: {", ".join(roles)}')


def record(db: Session, user: User | None, action: str, project_id=None, detail=None):
    db.add(Audit(user_id=user.id if user else None, action=action, project_id=project_id, detail=json.dumps(detail or {}, default=str)))


def dec(value, name='number', minimum=None, maximum=None):
    try:
        d = Decimal(str(value))
        if not d.is_finite():
            raise ValueError()
        if minimum is not None and d < Decimal(str(minimum)):
            raise ValueError()
        if maximum is not None and d > Decimal(str(maximum)):
            raise ValueError()
        return d
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, f'Invalid {name}')


def money(value: Decimal):
    return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def config_dict(row: ProductConfig):
    return json.loads(row.definition)


def get_project(db: Session, id: int) -> Project:
    p = db.get(Project, id)
    if not p:
        raise HTTPException(404, 'Project not found')
    return p


def get_config(db: Session, code: str) -> ProductConfig:
    cfg = db.scalar(select(ProductConfig).where(ProductConfig.code == code))
    if not cfg:
        raise HTTPException(404, 'Product configuration not found')
    return cfg


def pack_records(db, p):
    return (
        db.scalars(select(Requirement).where(Requirement.project_id == p.id).order_by(Requirement.id)).all(),
        db.scalars(select(BOMLine).where(BOMLine.project_id == p.id).order_by(BOMLine.id)).all(),
        db.scalars(select(Operation).where(Operation.project_id == p.id).order_by(Operation.id)).all(),
        db.scalars(select(Document).where(Document.project_id == p.id).order_by(Document.id)).all(),
    )


def public_rate(row: Price):
    return {'id': row.id, 'sku': row.sku, 'description': row.description, 'unit': row.unit, 'rate': row.rate, 'status': row.status, 'source': row.source, 'vendor': row.vendor, 'url': row.url, 'valid_until': row.valid_until, 'profile': json.loads(row.profile or '{}'), 'updated_at': str(row.updated_at)}


def requirement_json(x):
    return {'id': x.id, 'key': x.field_key, 'value': x.value, 'unit': x.unit, 'status': x.status, 'evidence': x.evidence, 'document_id': x.document_id}


def line_json(x):
    return {'id': x.id, 'sku': x.sku, 'qty': x.qty, 'unit': x.unit, 'waste_pct': x.waste_pct, 'status': x.status, 'note': x.note}


def op_json(x):
    return {'id': x.id, 'code': x.code, 'description': x.description, 'hours': x.hours, 'rate': x.rate, 'status': x.status}


def sync_technical_requirement(db:Session,pid:int,r:Requirement):
    """Keep the customer-facing specification's shared field in sync with the
    engineer's authoritative requirement; do not duplicate approval decisions.
    """
    from .commercial import profile_for, js
    cp=profile_for(db,pid)
    if cp is None:return
    technical=js(cp.technical,[])
    modified=False
    for section in technical:
        for f in section.get('fields',[]):
            if f.get('key')==r.field_key:
                f['value']=r.value;f['evidence']=r.evidence
                f['review_status']='APPROVED' if r.status=='APPROVED' else 'PENDING'
                modified=True
    if modified:
        cp.technical=json.dumps(technical,ensure_ascii=False)
        cp.updated_at=utcnow()


def get_candidate(db:Session,pid:int,did:int,index:int,expected_kind:str|None=None):
    """Locate source candidates by persisted document and index, never by client text."""
    doc=db.scalar(select(Document).where(Document.project_id==pid,Document.id==did))
    if doc is None:raise HTTPException(404,'Supporting design document was not found')
    candidates=json.loads(doc.candidates or '[]')
    if index<0 or index>=len(candidates):raise HTTPException(422,'Unknown extracted candidate index')
    candidate=candidates[index]
    if expected_kind and candidate.get('kind')!=expected_kind:
        raise HTTPException(422,f'Expected a {expected_kind} source candidate')
    return doc,candidate


def link_candidate(db:Session,pid:int,did:int|None,index:int|None,kind:str,target:int,user:User,sku:str|None=None,key:str|None=None):
    if did is None and index is None:return
    if did is None or index is None:raise HTTPException(422,'Source document and candidate index must be supplied together')
    expected={'BOM':'material','OPERATION':'operation','REQUIREMENT':'field'}[kind]
    doc,candidate=get_candidate(db,pid,did,index,expected)
    if sku is not None and candidate.get('sku')!=sku:
        raise HTTPException(422,'Source material does not match the selected catalogue SKU')
    if key is not None and candidate.get('key')!=key:
        raise HTTPException(422,'Source requirement does not match the selected field')
    entry=db.scalar(select(CandidateReview).where(CandidateReview.document_id==did,CandidateReview.candidate_index==index))
    if entry and entry.decision=='LINKED' and (entry.target_kind!=kind or entry.target_id!=target):
        raise HTTPException(409,'Candidate is already linked to a different record; open that record to edit it')
    if not entry:
        entry=CandidateReview(project_id=pid,document_id=did,candidate_index=index,decision='LINKED',user_id=user.id)
        db.add(entry)
    entry.decision='LINKED';entry.target_kind=kind;entry.target_id=target
    entry.user_id=user.id;entry.updated_at=utcnow()
    entry.note='Linked to saved project record; awaiting independent approval'[:500]
    record(db,user,'DOCUMENT_CANDIDATE_LINKED',pid,{'document_id':did,'candidate_index':index,'kind':kind,'target_id':target})


def decorate_documents(db:Session,pid:int,docs:list,reqs:list,bom:list,ops:list):
    """Reconstruct live review state on every GET; do not cache a stale copy of values."""
    reviews=db.scalars(select(CandidateReview).where(CandidateReview.project_id==pid)).all()
    mapping={(r.document_id,r.candidate_index):r for r in reviews}
    req_by_id={r.id:r for r in reqs}; bom_by_id={b.id:b for b in bom}; op_by_id={o.id:o for o in ops}
    req_by_key={r.field_key:r for r in reqs}
    docs_by_id={d['id']:d for d in docs}
    for d in docs:
        enriched=[]
        for i,raw in enumerate(d['candidates']):
            c=dict(raw);c['candidate_index']=i
            item={'state':'UNREVIEWED','label':'Not reviewed','target_kind':'','target_id':None}
            entry=mapping.get((d['id'],i))
            if entry and entry.decision=='DISMISSED':
                item.update(state='DISMISSED',label='Marked not applicable',note=entry.note)
            elif entry and entry.decision=='LINKED':
                target={'REQUIREMENT':req_by_id,'BOM':bom_by_id,'OPERATION':op_by_id}.get(entry.target_kind,{}).get(entry.target_id)
                if target:
                    v=(f'{target.value} {target.unit}'.strip() if entry.target_kind=='REQUIREMENT' else
                       f'{target.qty} {target.unit}, {target.waste_pct}% allowance' if entry.target_kind=='BOM' else
                       f'{target.hours} hours @ INR {target.rate}/hour')
                    approved=(target.status=='APPROVED')
                    item.update(state='VERIFIED' if approved else 'SAVED_PENDING',
                        label='Verified' if approved else 'Saved; approval pending',
                        target_kind=entry.target_kind,target_id=target.id,value=v,
                        record_status=target.status)
                else:
                    item.update(state='SOURCE_LINK_BROKEN',label='Linked record removed; review again')
            elif c.get('kind')=='field':
                r=req_by_key.get(c.get('key'))
                if r and r.document_id==d['id'] and r.value==str(c.get('value','')):
                    item.update(state='VERIFIED' if r.status=='APPROVED' else 'AUTO_PREFILLED',
                        label='Requirement verified' if r.status=='APPROVED' else 'Prefilled; not verified',
                        target_kind='REQUIREMENT',target_id=r.id,value=f'{r.value} {r.unit}'.strip(),record_status=r.status)
            c['review']=item
            enriched.append(c)
        d['candidates']=enriched
        d['review_counts']={
          'total':len(enriched),
          'verified':sum(x['review']['state']=='VERIFIED' for x in enriched),
          'pending':sum(x['review']['state'] in ('SAVED_PENDING','AUTO_PREFILLED') for x in enriched),
          'unreviewed':sum(x['review']['state'] in ('UNREVIEWED','SOURCE_LINK_BROKEN') for x in enriched),
          'dismissed':sum(x['review']['state']=='DISMISSED' for x in enriched)}
    sources={}
    for entry in reviews:
        if entry.decision!='LINKED' or not entry.target_id:continue
        d=docs_by_id.get(entry.document_id)
        if not d:continue
        raw=d['candidates'][entry.candidate_index] if entry.candidate_index<len(d['candidates']) else {}
        info={'document_id':d['id'],'document_name':d['original_name'],
              'source_location':raw.get('source_location') or f'Candidate {entry.candidate_index+1}',
              'candidate_index':entry.candidate_index,'evidence':raw.get('evidence','')}
        sources[(entry.target_kind,entry.target_id)]=info
    return sources


def doc_json(x):
    candidates=json.loads(x.candidates)
    return {'id': x.id, 'original_name': x.original_name, 'checksum': x.checksum,
      'pages': x.pages, 'uploaded_at': str(x.uploaded_at), 'candidates': candidates,
      'document_type': 'DOCX' if x.original_name.lower().endswith('.docx') else 'PDF',
      'text_quality': 'TEXT_AVAILABLE' if x.text.strip() else 'NO_MACHINE_READABLE_TEXT',
      'extraction_note': 'Candidates are unverified heuristic matches, not certain facts.'}



def project_json(p):
    return {'id': p.id, 'ref': p.ref, 'title': p.title, 'customer': p.customer, 'product_code': p.product_code, 'config_version': p.config_version, 'quantity': p.quantity, 'overhead_pct': p.overhead_pct, 'contingency_pct': p.contingency_pct, 'margin_pct': p.margin_pct, 'scope': p.scope, 'exclusions': p.exclusions, 'delivery': p.delivery, 'payment_terms': p.payment_terms, 'validity_days': p.validity_days, 'status': p.status, 'created_at': str(p.created_at), 'updated_at': str(p.updated_at)}


# Nominal weights use idealized rectangular section geometry, not certified manufacturer data.
def nominal_conversion(profile, unit):
    k = profile.get('kind')
    if k == 'shs' and unit == 'm':
        w, h, t = (dec(profile[x], x, 0) for x in ('width_mm', 'height_mm', 'thickness_mm'))
        if t == 0 or 2*t >= min(w,h): raise HTTPException(422,'Invalid SHS dimensions')
        return (w*h - (w-2*t)*(h-2*t))*Decimal('0.00785')
    if k == 'flat' and unit == 'm':
        return dec(profile['width_mm'])*dec(profile['thickness_mm'])*Decimal('0.00785')
    if k == 'angle' and unit == 'm':
        a,b,t = (dec(profile[x], x, 0) for x in ('a_mm','b_mm','thickness_mm'))
        if t==0 or t>=min(a,b): raise HTTPException(422,'Invalid angle dimensions')
        return t*(a+b-t)*Decimal('0.00785')
    if k == 'sheet' and unit == 'm2':
        return dec(profile['thickness_mm'])*Decimal('7.85')
    return None


def price_is_valid(rate: Price):
    if rate.status not in RATES_FIRM:
        return False
    if not rate.source.strip():
        return False
    if rate.status == 'SUPPLIER_APPROVED' and (not rate.vendor.strip() or not rate.valid_until):
        return False
    if rate.valid_until:
        try:
            if date.fromisoformat(rate.valid_until) < date.today():
                return False
        except ValueError:
            return False
    return True


def compute(db: Session, p: Project):
    reqs, bom, operations, docs = pack_records(db, p)
    warnings = []
    lines = []
    subtotal = Decimal(0)
    price_snapshots = []
    for b in bom:
        pr = db.scalar(select(Price).where(Price.sku == b.sku))
        if not pr:
            raise HTTPException(422, f'Missing price record for {b.sku}')
        qty = dec(b.qty, 'quantity',0)
        waste = dec(b.waste_pct, 'waste %',0,99)/100
        rate = dec(pr.rate, 'unit price',0)
        conv = Decimal(1)
        derived = False
        if b.unit != pr.unit:
            if pr.unit == 'kg':
                factor = nominal_conversion(json.loads(pr.profile), b.unit)
                if factor is None:
                    raise HTTPException(422, f'No valid conversion from {b.unit} to {pr.unit} for {b.sku}')
                conv = factor;derived=True
            elif b.unit == 'm2' and pr.unit == 'sqft':
                conv = Decimal('10.763910416709722')
            elif b.unit == 'mm' and pr.unit == 'm':
                conv = Decimal('0.001')
            else:
                raise HTTPException(422, f'Incompatible units: {b.unit} / {pr.unit} for {b.sku}')
        purchase_qty = qty * (1+waste) * conv
        cost = purchase_qty*rate
        subtotal += cost
        if derived: warnings.append(f'{b.sku}: idealized theoretical weight, verify actual stock weight')
        if b.status != 'APPROVED': warnings.append(f'{b.sku}: quantity not approved')
        if not price_is_valid(pr): warnings.append(f'{b.sku}: price is indicative or expired')
        lines.append({'id':b.id,'sku':b.sku,'description':pr.description,'qty':str(qty),'unit':b.unit,'waste_pct':str(waste*100),'purchase_qty':str(purchase_qty.quantize(Decimal('0.0001'))),'rate':str(rate),'rate_unit':pr.unit,'rate_status':pr.status,'conversion_factor':str(conv),'nominal_weight':derived,'line_total':money(cost),'quantity_status':b.status})
        price_snapshots.append({'sku': pr.sku,'rate':pr.rate,'unit':pr.unit,'status':pr.status,'valid_until':pr.valid_until,'updated_at':str(pr.updated_at),'profile':pr.profile})
    op_lines=[]; operation_cost=Decimal(0)
    for o in operations:
        h = dec(o.hours,'hours',0)
        r = dec(o.rate,'hourly rate',0)
        cost=h*r; operation_cost+=cost
        if o.status!='APPROVED':warnings.append(f'{o.code}: operation not approved')
        op_lines.append({**op_json(o),'line_total':money(cost)})
    base = subtotal + operation_cost
    overhead_pct=dec(p.overhead_pct,'overhead %',0,100)
    contingency_pct=dec(p.contingency_pct,'contingency %',0,100)
    margin_pct=dec(p.margin_pct,'margin %',0,99)
    overhead=base*overhead_pct/100
    contingency=base*contingency_pct/100
    cost=base+overhead+contingency
    selling=cost/(1-margin_pct/100)
    fingerprint_input={
        'project':project_json(p),
        'config':config_dict(get_config(db,p.product_code)),
        'requirements':[requirement_json(x) for x in reqs],
        'bom':[line_json(x) for x in bom],
        'operations':[op_json(x) for x in operations],
        'docs':[{'id':d.id,'hash':d.checksum} for d in docs],
        'rates':price_snapshots,
    }
    # Quotation settings are shared output controls, not a second pricing engine.
    # Include them in the ordinary cost-plus approval fingerprint: changing tax,
    # contact, seller or the layout requires re-approval before firm issuance.
    from .standard_quote import settings_for, quote_fingerprint
    quote_settings = settings_for(db, p.id)
    if quote_settings is not None:
        fingerprint_input['quotation_settings'] = quote_fingerprint(quote_settings,db)
    # Avoid changing the fingerprint with timestamps not relevant to substantive approval.
    fingerprint_input['project'].pop('updated_at',None)
    fingerprint_input['project'].pop('status',None)
    fp = hashlib.sha256(json.dumps(fingerprint_input,sort_keys=True,default=str).encode()).hexdigest()
    return {'lines':lines,'operations':op_lines,'material_cost':money(subtotal),'operation_cost':money(operation_cost),'overhead':money(overhead),'contingency':money(contingency),'total_cost':money(cost),'unit_price':money(selling),'order_value':money(selling*p.quantity),'target_margin_pct':p.margin_pct,'currency':'INR','tax':'EXCLUDED - confirm separately','warnings':sorted(set(warnings)),'fingerprint':fp}


def checks(db: Session, p: Project, calc=None):
    calc=calc or compute(db,p)
    reqs,bom,ops,docs=pack_records(db,p)
    fields={r.field_key:r for r in reqs}
    cfg=config_dict(get_config(db,p.product_code))
    req_valid=True; missing=[]
    for f in cfg.get('required_fields',[]):
        r=fields.get(f['key'])
        if f.get('firm_required',False):
            if not r or r.status!='APPROVED' or not r.value.strip() or (f['key'].endswith('_approved') or f['key']=='complete_drawing_set') and r.value.strip().lower() not in ('true','yes','1'):
                req_valid=False;missing.append(f['key'])
    quantity_valid=bool(bom) and all(b.status=='APPROVED' for b in bom)
    required_op_codes=set(cfg.get('required_operations', []))
    ops_valid=all(o.status=='APPROVED' for o in ops) and required_op_codes.issubset({o.code for o in ops})
    rates=[]
    for b in bom:
        pr=db.scalar(select(Price).where(Price.sku==b.sku))
        rates.append(pr is not None and price_is_valid(pr))
    pricing_valid=bool(bom) and all(rates) and ops_valid
    doc_valid=bool(docs) if cfg.get('requires_document',True) else True
    aps=db.scalars(select(Approval).where(Approval.project_id==p.id).order_by(Approval.id.desc())).all()
    current={}
    for a in aps:
        if a.kind not in current and a.fingerprint==calc['fingerprint']:
            current[a.kind]=a
    conflicts=conflicts_from_docs([doc_json(x) for x in docs])
    tech_ok=doc_valid and req_valid and quantity_valid and not conflicts
    eng=bool(current.get('engineering'))
    pric=bool(current.get('pricing'))
    comm=bool(current.get('commercial'))
    product_release_enabled=bool(cfg.get('firm_release_enabled', True))
    firm_ready=product_release_enabled and tech_ok and pricing_valid and eng and pric and comm
    return {'drawing_complete':doc_valid,'requirements_verified':req_valid,'source_conflicts_unresolved':[x['key'] for x in conflicts],'missing_fields':missing,'quantities_approved':quantity_valid,'operations_approved':ops_valid,'rates_verified':pricing_valid,'engineering_approved':eng,'pricing_approved':pric,'commercial_approved':comm,'product_release_enabled':product_release_enabled,'firm_ready':firm_ready,'budgetary_preview_allowed':True,'approval_records':[{'kind':a.kind,'by':a.user_id,'at':str(a.approved_at),'note':a.note} for a in current.values()]}


def overview(db:Session,p:Project):
    # Add quotation-only settings to existing cost-plus projects before the
    # estimate fingerprint is computed. Do not migrate historical commercial projects.
    from .standard_quote import settings_for, init_settings
    if not commercial.profile_for(db,p.id) and not settings_for(db,p.id):
        init_settings(db,p);db.commit()
    reqs,bom,ops,docs=pack_records(db,p)
    calc=compute(db,p)
    issues=db.scalars(select(IssuedQuote).where(IssuedQuote.project_id==p.id).order_by(IssuedQuote.id.desc())).all()
    document_data=[doc_json(x) for x in docs]
    linked_sources=decorate_documents(db,p.id,document_data,reqs,bom,ops)
    latest_bom_reviews={}
    for v in db.scalars(select(BOMVerification).where(BOMVerification.project_id==p.id).order_by(BOMVerification.id.desc())).all():
        if v.bom_line_id not in latest_bom_reviews:latest_bom_reviews[v.bom_line_id]=v
    fields=[]
    for r in reqs:
        record_data=requirement_json(r)
        matching=[]
        for doc in document_data:
            if doc['id']==r.document_id:
                matching=[x for x in doc['candidates'] if x.get('kind')=='field' and x.get('key')==r.field_key and x.get('value')==r.value]
        candidate=matching[0] if matching else None
        record_data['source_link']=linked_sources.get(('REQUIREMENT',r.id))
        record_data.update({'confidence_score':candidate.get('confidence_score') if candidate else None,
          'confidence_basis':candidate.get('confidence_basis') if candidate else ('MANUAL_ENTRY' if r.value else 'NOT_EXTRACTED'),
          'source_page':candidate.get('page') if candidate else None,
          'extraction_method':candidate.get('method') if candidate else ('MANUAL' if r.value else None),
          'verification_status':r.status})
        fields.append(record_data)
    result={'project':project_json(p),'config':config_dict(get_config(db,p.product_code)),
      'requirements':fields,'bom':[{**line_json(x),'source_link':linked_sources.get(('BOM',x.id)),
            'verification':({'source_reference':latest_bom_reviews[x.id].source_reference,
                  'note':latest_bom_reviews[x.id].verification_note,
                  'verified_by_user_id':latest_bom_reviews[x.id].user_id,
                  'verified_at':str(latest_bom_reviews[x.id].verified_at)}
                if x.status=='APPROVED' and x.id in latest_bom_reviews else None)} for x in bom],
      'operations':[{**op_json(x),'source_link':linked_sources.get(('OPERATION',x.id))} for x in ops],'documents':document_data,
      'extraction_conflicts':conflicts_from_docs(document_data),
      'extraction_policy':'Confidence is match strength only; never a guaranteed probability. All critical fields need source review.',
      'estimate':calc,'gates':checks(db,p,calc),
      'issues':[{'id':i.id,'number':i.number,'issued_at':str(i.issued_at),'checksum':i.checksum,
                 'has_docx':bool(json.loads(i.snapshot or '{}').get('docx_stored_name'))} for i in issues]}
    if commercial.profile_for(db,p.id):
        result['commercial']=commercial.commercial_overview(db,p)
        result['quotation']=None  # Historical commercial project remains intact.
    else:
        result['commercial']=None
        from .standard_quote import quote_state
        result['quotation']=quote_state(db,p)
    return result



class LoginBody(BaseModel):
    username: str
    password: str


class NewProject(BaseModel):
    customer: str = Field(min_length=1,max_length=180)
    title: str = Field(min_length=1,max_length=180)
    product_code: str
    quote_workflow: str = 'legacy_cost_plus'


class ProjectSettings(BaseModel):
    customer: str = Field(min_length=1,max_length=180)
    title: str = Field(min_length=1,max_length=180)
    quantity: int = Field(ge=1,le=1000000)
    overhead_pct: str
    contingency_pct: str
    margin_pct: str
    scope: str = Field(max_length=5000)
    exclusions: str = Field(max_length=5000)
    delivery: str = Field(max_length=240)
    payment_terms: str = Field(max_length=240)
    validity_days: int = Field(ge=1,le=365)


class RequirementBody(BaseModel):
    value: str = Field(max_length=500)
    evidence: str = Field(default='',max_length=700)
    document_id: int | None = None


class RequirementVerifyBody(BaseModel):
    value: str = Field(min_length=1,max_length=500)
    source_reference: str = Field(min_length=8,max_length=380)
    verification_note: str = Field(min_length=12,max_length=250)
    document_id: int | None = None
    candidate_index: int | None = None


class CandidateDismissBody(BaseModel):
    explanation: str = Field(min_length=8,max_length=500)


class BOMVerifyBody(BaseModel):
    source_reference: str = Field(min_length=8,max_length=380)
    verification_note: str = Field(min_length=12,max_length=250)


class BOMBody(BaseModel):
    sku: str
    qty: str
    unit: str
    waste_pct: str = '0'
    status: Literal['ASSUMED','APPROVED'] = 'ASSUMED'
    note: str = Field(default='',max_length=500)
    source_document_id: int | None = None
    source_candidate_index: int | None = None


class OpBody(BaseModel):
    code: str = Field(min_length=1,max_length=60)
    description: str = Field(min_length=1,max_length=200)
    hours: str
    rate: str
    status: Literal['ASSUMED','APPROVED']='ASSUMED'
    source_document_id: int | None = None
    source_candidate_index: int | None = None


class PriceBody(BaseModel):
    sku: str = Field(min_length=1,max_length=100)
    description: str = Field(min_length=1,max_length=300)
    rate: str
    unit: str = Field(min_length=1,max_length=16,pattern=r'^[\w][\w ./%+-]{0,15}$')
    status: str
    source: str = Field(default='',max_length=300)
    vendor: str = Field(default='',max_length=200)
    url: str = Field(default='',max_length=500)
    valid_until: str = ''
    profile: dict = Field(default_factory=dict)


class NewConfig(BaseModel):
    code: str = Field(pattern=r'^[a-z][a-z0-9_]{2,59}$')
    label: str = Field(min_length=3,max_length=160)
    required_fields: list[dict] = Field(default_factory=list,max_length=60)
    allowed_components: list[str] = Field(default_factory=list,max_length=150)
    required_operations: list[str] = Field(default_factory=list,max_length=30)
    material_matchers: list[dict] = Field(default_factory=list,max_length=150)
    specification_sections: list[dict] = Field(default_factory=list,max_length=40)
    requires_document: bool = True


class ApprovalBody(BaseModel):
    note: str = Field(default='',max_length=600)


@app.get('/api/health')
def health():
    return {'status':'ok','app':'IndustriQuote','version':app.version,'demo_mode':os.getenv('APP_DEMO_MODE') == '1'}


@app.post('/api/auth/login')
def login(payload: LoginBody, db: Session=Depends(db_session)):
    user=db.scalar(select(User).where(User.username==payload.username.strip().lower()))
    if not user or not user.active or not valid_password(payload.password,user.password_hash):
        raise HTTPException(401,'Incorrect credentials')
    token=serializer.dumps({'uid':user.id,'v':user.auth_version})
    record(db,user,'LOGIN')
    db.commit()
    return {'token':token,'user':public_user(user)}


@app.get('/api/me')
def me(user:User=Depends(current_user)):
    return public_user(user)



# Account management: no SMTP dependency or unauthenticated email-reset shortcut.
# User-saved recovery codes work entirely offline on the Windows PC.

def public_user(user: User) -> dict:
    return {'id': user.id, 'username': user.username, 'display_name': user.display_name,
            'email': user.email or '', 'phone': user.phone or '',
            'role': user.role, 'active': user.active,
            'must_change_password': user.must_change_password}


def check_password_strength(password: str):
    if not 12 <= len(password) <= 128 or not password.strip():
        raise HTTPException(422, 'Use a password of 12 to 128 characters')


def normalized_email(value: str) -> str:
    value = value.strip().lower()
    if value and (len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)):
        raise HTTPException(422, 'Enter a valid email address or leave it blank')
    return value


def _clear_recovery_codes(db: Session, uid: int):
    for row in db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == uid)).all():
        db.delete(row)


def generate_recovery_codes(db: Session, user: User) -> list[str]:
    _clear_recovery_codes(db, user.id)
    codes = []
    for _ in range(6):
        raw = secrets.token_hex(16).upper()  # 128 bits, secure to show once.
        code = '-'.join(raw[i:i+8] for i in range(0, 32, 8))
        db.add(RecoveryCode(user_id=user.id, code_hash=hashlib.sha256(raw.encode('ascii')).hexdigest()))
        codes.append(code)
    return codes


class ProfileBody(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(default='', max_length=254)
    phone: str = Field(default='', max_length=32)


class PasswordChangeBody(BaseModel):
    current_password: str
    new_password: str


class PasswordConfirmBody(BaseModel):
    current_password: str


class RecoveryBody(BaseModel):
    username: str
    recovery_code: str
    new_password: str


@app.get('/api/profile')
def get_profile(user: User = Depends(current_user), db: Session = Depends(db_session)):
    available = db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id)).all()
    return {**public_user(user), 'recovery_codes_remaining': len(available)}


@app.put('/api/profile')
def edit_profile(data: ProfileBody, user: User = Depends(current_user), db: Session = Depends(db_session)):
    user.display_name = data.display_name.strip()
    if len(user.display_name) < 2:
        raise HTTPException(422, 'Display name is too short')
    user.email = normalized_email(data.email)
    user.phone = data.phone.strip()
    record(db, user, 'PROFILE_UPDATED')
    db.commit()
    return public_user(user)


@app.post('/api/profile/password')
def change_password(data: PasswordChangeBody, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if not valid_password(data.current_password, user.password_hash):
        raise HTTPException(403, 'Current password is incorrect')
    check_password_strength(data.new_password)
    if valid_password(data.new_password, user.password_hash):
        raise HTTPException(422, 'New password must differ from your current password')
    user.password_hash = hashed_password(data.new_password)
    user.must_change_password = False
    user.auth_version += 1  # Immediately revoke old signed tokens.
    record(db, user, 'PASSWORD_CHANGED')
    db.commit()
    return {'changed': True, 'sign_in_required': True}


@app.get('/api/profile/recovery-codes')
def recovery_status(user: User = Depends(current_user), db: Session = Depends(db_session)):
    return {'remaining': len(db.scalars(select(RecoveryCode).where(RecoveryCode.user_id == user.id)).all())}


@app.post('/api/profile/recovery-codes')
def create_recovery_codes(data: PasswordConfirmBody, user: User = Depends(current_user), db: Session = Depends(db_session)):
    if not valid_password(data.current_password, user.password_hash):
        raise HTTPException(403, 'Password is incorrect')
    codes = generate_recovery_codes(db, user)
    record(db, user, 'RECOVERY_CODES_REGENERATED')
    db.commit()
    return {'codes': codes, 'notice': 'Save these codes offline. Each can reset your password once; previous codes are invalid.'}


@app.post('/api/auth/recover')
def recover_account(data: RecoveryBody, db: Session = Depends(db_session)):
    check_password_strength(data.new_password)
    username = data.username.strip().lower()
    raw = re.sub(r'[-\s]', '', data.recovery_code).upper()
    account = db.scalar(select(User).where(User.username == username))
    # Same response for wrong username, missing code, inactive user or consumed code.
    if not re.fullmatch(r'[A-F0-9]{32}', raw) or not account or not account.active:
        raise HTTPException(400, 'Invalid username or recovery code')
    code_hash = hashlib.sha256(raw.encode('ascii')).hexdigest()
    valid_code = db.scalar(select(RecoveryCode).where(RecoveryCode.user_id == account.id,
                                                       RecoveryCode.code_hash == code_hash))
    if not valid_code:
        raise HTTPException(400, 'Invalid username or recovery code')
    if valid_password(data.new_password, account.password_hash):
        raise HTTPException(422, 'New password must differ from your current password')
    account.password_hash = hashed_password(data.new_password)
    account.auth_version += 1
    account.must_change_password = False
    _clear_recovery_codes(db, account.id)  # No leftover recovery credentials after reset.
    record(db, account, 'PASSWORD_RECOVERED')
    db.commit()
    return {'changed': True}


@app.post('/api/profile/signout-all')
def signout_all(user: User = Depends(current_user), db: Session = Depends(db_session)):
    user.auth_version += 1
    record(db, user, 'ALL_SESSIONS_REVOKED')
    db.commit()
    return {'revoked': True}


@app.get('/api/configs')
def configs(db:Session=Depends(db_session),user:User=Depends(current_user)):
    return [config_dict(x) for x in db.scalars(select(ProductConfig).order_by(ProductConfig.label)).all()]


@app.post('/api/configs')
def add_config(data:NewConfig,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'admin')
    if db.scalar(select(ProductConfig).where(ProductConfig.code==data.code)):
        raise HTTPException(409,'Product code exists')
    fields=[];seen=set()
    for x in data.required_fields:
        key=x.get('key','')
        if not re.fullmatch(r'[a-z][a-z0-9_]{1,59}',key) or key in seen:
            raise HTTPException(422,'Invalid or repeated field key')
        seen.add(key)
        fields.append({'key':key,'label':str(x.get('label') or key.replace('_',' ').title())[:100],'unit':str(x.get('unit') or '')[:16],'firm_required':bool(x.get('firm_required',True)),'aliases':[str(a)[:90] for a in x.get('aliases',[])[:12]],'extraction_type':str(x.get('extraction_type') or '')[:20]})
    definition={'product_type':data.code,'label':data.label,'config_version':'1.0.0','required_fields':fields,'allowed_components':data.allowed_components,'required_operations':data.required_operations,'requires_document':data.requires_document,'material_matchers':data.material_matchers,'specification_sections':data.specification_sections,'notes':'User-configured; no engineering design automation.'}
    db.add(ProductConfig(code=data.code,label=data.label,version='1.0.0',definition=json.dumps(definition)))
    record(db,user,'CONFIG_CREATED',detail={'code':data.code})
    db.commit()
    return definition


@app.get('/api/prices')
def prices(db:Session=Depends(db_session),user:User=Depends(current_user)):
    return [public_rate(p) for p in db.scalars(select(Price).order_by(Price.sku)).all()]


def save_price(data:PriceBody,db,user, existing=None):
    require_role(user,'procurement')
    if data.status not in STATUS_OPTIONS:raise HTTPException(422,'Invalid rate status')
    dec(data.rate,'rate',0)
    if data.valid_until:
        try:date.fromisoformat(data.valid_until)
        except ValueError:raise HTTPException(422,'Date must be YYYY-MM-DD')
    row=existing or Price(sku=data.sku)
    if existing and data.sku!=row.sku:raise HTTPException(422,'Cannot change SKU')
    for field,value in {'description':data.description,'rate':data.rate,'unit':data.unit,'status':data.status,'source':data.source,'vendor':data.vendor,'url':data.url,'valid_until':data.valid_until,'profile':json.dumps(data.profile,sort_keys=True),'updated_at':utcnow()}.items():
        setattr(row,field,value)
    if not existing:db.add(row)
    db.flush()
    affected=db.scalars(select(BOMLine).where(BOMLine.sku==data.sku)).all()
    for pid in {b.project_id for b in affected}:
        compute(db,get_project(db,pid))  # Reject rate/unit changes that break an existing estimate.
    record(db,user,'PRICE_UPDATED',detail={'sku':data.sku,'rate':data.rate,'status':data.status})
    db.commit()
    return public_rate(row)


@app.post('/api/prices')
def create_price(data:PriceBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    if db.scalar(select(Price).where(Price.sku==data.sku)):raise HTTPException(409,'SKU exists')
    return save_price(data,db,user)


@app.put('/api/prices/{sku}')
def update_price(sku:str,data:PriceBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    row=db.scalar(select(Price).where(Price.sku==sku))
    if not row:raise HTTPException(404,'Rate not found')
    return save_price(data,db,user,row)


@app.get('/api/projects')
def projects(db:Session=Depends(db_session),user:User=Depends(current_user)):
    rows=db.scalars(select(Project).order_by(Project.updated_at.desc(),Project.id.desc())).all()
    out=[]
    for p in rows:
        d=project_json(p)
        try:
            if commercial.profile_for(db,p.id):
                cq=commercial.commercial_overview(db,p)
                d['estimate']=cq['pricing']['known_total_including_tax']
                d['firm_ready']=cq['gates']['firm_ready']
            else:
                d['estimate']=compute(db,p)['order_value']
                # Ready-to-issue requires BOTH the original cost-plus gates and
                # shared quotation requirements (named contact, taxes, terms).
                from .standard_quote import quote_state
                d['firm_ready']=quote_state(db,p)['gates']['firm_ready']
        except HTTPException:
            d['estimate']=None;d['firm_ready']=False
        out.append(d)
    return out


@app.post('/api/projects')
def create_project(data:NewProject,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator')
    config=get_config(db,data.product_code)
    from .company_settings import ensure_company
    prefix=ensure_company(db).quote_prefix
    ref=prefix+'-'+datetime.now().strftime('%y%m%d')+'-'+secrets.token_hex(3).upper()
    p=Project(ref=ref,title=data.title,customer=data.customer,product_code=config.code,config_version=config.version,created_by=user.id)
    db.add(p);db.flush()
    # One new-project workflow for every product family: the original
    # cost-plus estimator. Deprecated quote_workflow values from cached
    # browsers are accepted but ignored so that the server remains authoritative.
    # Existing commercial records must remain untouched (no silent migration).
    workflow='legacy_cost_plus'
    # Every new project receives quotation settings independently of costing.
    from .standard_quote import init_settings
    init_settings(db, p)
    for f in config_dict(config).get('required_fields',[]):
        db.add(Requirement(project_id=p.id,field_key=f['key'],unit=f.get('unit') or ''))
    record(db,user,'PROJECT_CREATED',p.id,{'ref':p.ref,'product':p.product_code,'workflow':workflow,'requested_workflow':data.quote_workflow})
    db.commit()
    return overview(db,p)


@app.get('/api/projects/{pid}')
def project_detail(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    return overview(db,get_project(db,pid))


@app.put('/api/projects/{pid}/settings')
def save_settings(pid:int,data:ProjectSettings,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator')
    p=get_project(db,pid)
    for field in ('overhead_pct','contingency_pct','margin_pct'):
        dec(getattr(data,field),field,0,99)
    from .standard_quote import settings_for
    standard=settings_for(db,pid)
    if standard is not None:
        terms=json.loads(standard.terms or '{}')
        for attr,term in [('scope','scope'),('exclusions','exclusions'),('delivery','delivery'),
                          ('payment_terms','payment'),('validity_days','validity_days')]:
            # Keep custom quote overrides intact; sync only values still mirroring
            # the former project setting, preventing stale quotation defaults.
            if terms.get(term)==getattr(p,attr):terms[term]=getattr(data,attr)
        standard.terms=json.dumps(terms,ensure_ascii=False)
    for field in data.model_fields:
        setattr(p,field,getattr(data,field))
    p.updated_at=utcnow();p.status='DRAFT'
    record(db,user,'PROJECT_SETTINGS_CHANGED',pid)
    db.commit()
    return overview(db,p)


@app.put('/api/projects/{pid}/requirements/{key}')
def save_requirement(pid:int,key:str,data:RequirementBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator','engineer')
    p=get_project(db,pid)
    r=db.scalar(select(Requirement).where(Requirement.project_id==pid,Requirement.field_key==key))
    if not r:raise HTTPException(404,'Requirement not defined for product')
    if data.document_id and not db.scalar(select(Document).where(Document.id==data.document_id,Document.project_id==pid)):
        raise HTTPException(422,'Invalid supporting document')
    r.value=data.value.strip();r.evidence=data.evidence;r.document_id=data.document_id;r.status='PENDING';r.updated_at=utcnow()
    # Manual edits may change the source, so the previous extraction-to-verification
    # decision is no longer linked to the active requirement.
    for link in db.scalars(select(CandidateReview).where(CandidateReview.project_id==pid,CandidateReview.target_kind=='REQUIREMENT',CandidateReview.target_id==r.id)).all():
        db.delete(link)
    sync_technical_requirement(db,pid,r)
    p.updated_at=utcnow();p.status='DRAFT';record(db,user,'REQUIREMENT_UPDATED',pid,{'key':key})
    db.commit();return overview(db,p)


@app.post('/api/projects/{pid}/requirements/{key}/verify')
def verify_requirement(pid:int,key:str,data:RequirementVerifyBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    """Atomic review: corrected value, accountable source, and reviewer note in one action."""
    require_role(user,'engineer')
    p=get_project(db,pid)
    r=db.scalar(select(Requirement).where(Requirement.project_id==pid,Requirement.field_key==key))
    if r is None:raise HTTPException(404,'Requirement not defined for this product')
    if data.document_id is not None:
        doc=db.scalar(select(Document).where(Document.project_id==pid,Document.id==data.document_id))
        if not doc:raise HTTPException(422,'Supporting design document is not in this project')
    if data.candidate_index is not None and data.document_id is None:
        raise HTTPException(422,'Candidate index requires a supporting document')
    if data.candidate_index is not None:
        _,candidate=get_candidate(db,pid,data.document_id,data.candidate_index,'field')
        if candidate.get('key')!=key:raise HTTPException(422,'Source candidate belongs to a different field')
    value=data.value.strip();source=data.source_reference.strip();note=data.verification_note.strip()
    if not value or not source or not note:raise HTTPException(422,'Verified value, source and reviewer note are required')
    r.value=value;r.evidence=f'{source} | Engineer verification: {note}'[:700]
    r.document_id=data.document_id
    r.status='APPROVED';r.updated_at=utcnow();p.updated_at=utcnow();p.status='DRAFT'
    for old_link in db.scalars(select(CandidateReview).where(CandidateReview.project_id==pid,CandidateReview.target_kind=='REQUIREMENT',CandidateReview.target_id==r.id)).all():
        if old_link.document_id!=data.document_id or old_link.candidate_index!=data.candidate_index:
            db.delete(old_link)
    if data.candidate_index is not None:
        link_candidate(db,pid,data.document_id,data.candidate_index,'REQUIREMENT',r.id,user,key=key)
    sync_technical_requirement(db,pid,r)
    record(db,user,'REQUIREMENT_EVIDENCE_VERIFIED',pid,{'key':key,'value':r.value,
      'source_reference':source,'reviewer_note':note,'document_id':data.document_id})
    db.commit();return overview(db,p)


@app.post('/api/projects/{pid}/requirements/{key}/approve')
def approve_requirement(pid:int,key:str,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'engineer')
    p=get_project(db,pid)
    r=db.scalar(select(Requirement).where(Requirement.project_id==pid,Requirement.field_key==key))
    if not r:raise HTTPException(404,'Requirement not found')
    if not r.value.strip():raise HTTPException(422,'Cannot approve blank requirement')
    if not r.evidence.strip():raise HTTPException(422,'Open Review & verify and enter the source drawing/page and your verification note')
    if r.evidence.startswith('Extracted (unverified)'):
        raise HTTPException(422,'Auto-extracted evidence is not verified. Use Review & verify to confirm the source and value')
    r.status='APPROVED';r.updated_at=utcnow();p.updated_at=utcnow();p.status='DRAFT'
    sync_technical_requirement(db,pid,r)
    record(db,user,'REQUIREMENT_APPROVED',pid,{'key':key,'value':r.value})
    db.commit();return overview(db,p)


def validate_bom(data:BOMBody,db,proj):
    dec(data.qty,'quantity',0);dec(data.waste_pct,'waste %',0,99)
    if not db.scalar(select(Price).where(Price.sku==data.sku)):
        raise HTTPException(422,'Select a SKU from the price book')
    cfg=config_dict(get_config(db,proj.product_code))
    allowed=cfg.get('allowed_components',[])
    if allowed and data.sku not in allowed:
        raise HTTPException(422,f'SKU not enabled for {proj.product_code}; add it to a new product config or choose another SKU')
    if data.status=='APPROVED':raise HTTPException(403,'Engineer must approve quantities separately')


@app.post('/api/projects/{pid}/bom')
def add_bom(pid:int,data:BOMBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator')
    p=get_project(db,pid);validate_bom(data,db,p)
    row=BOMLine(project_id=pid,sku=data.sku,qty=data.qty,unit=data.unit,waste_pct=data.waste_pct,status='ASSUMED',note=data.note)
    db.add(row);db.flush()
    link_candidate(db,pid,data.source_document_id,data.source_candidate_index,'BOM',row.id,user,sku=data.sku)
    compute(db,p);p.updated_at=utcnow();p.status='DRAFT';record(db,user,'BOM_ADDED',pid,{'sku':data.sku});db.commit()
    return overview(db,p)


@app.put('/api/projects/{pid}/bom/{lid}')
def change_bom(pid:int,lid:int,data:BOMBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator')
    p=get_project(db,pid);validate_bom(data,db,p)
    row=db.scalar(select(BOMLine).where(BOMLine.id==lid,BOMLine.project_id==pid))
    if not row:raise HTTPException(404,'Line not found')
    for key in ('sku','qty','unit','waste_pct','note'):
        setattr(row,key,getattr(data,key))
    row.status='ASSUMED';db.flush()
    link_candidate(db,pid,data.source_document_id,data.source_candidate_index,'BOM',row.id,user,sku=data.sku)
    compute(db,p);p.updated_at=utcnow();p.status='DRAFT';record(db,user,'BOM_CHANGED',pid,{'id':lid});db.commit()
    return overview(db,p)


@app.post('/api/projects/{pid}/bom/{lid}/approve')
def approve_bom(pid:int,lid:int,data:BOMVerifyBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'engineer')
    p=get_project(db,pid)
    row=db.scalar(select(BOMLine).where(BOMLine.id==lid,BOMLine.project_id==pid))
    if not row:raise HTTPException(404,'Line not found')
    dec(row.qty,'quantity',Decimal('0.00000001'))
    source=data.source_reference.strip();note=data.verification_note.strip()
    if not source or not note:raise HTTPException(422,'Source and verification note are required')
    db.add(BOMVerification(project_id=pid,bom_line_id=lid,confirmed_qty=row.qty,
        confirmed_unit=row.unit,source_reference=source,verification_note=note,user_id=user.id))
    row.status='APPROVED';p.updated_at=utcnow();p.status='DRAFT'
    record(db,user,'BOM_QUANTITY_APPROVED',pid,{'sku':row.sku,'id':lid,'quantity':row.qty,'unit':row.unit,
      'source_reference':source,'verification_note':note});db.commit()
    return overview(db,p)


@app.delete('/api/projects/{pid}/bom/{lid}')
def delete_bom(pid:int,lid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator')
    p=get_project(db,pid);row=db.scalar(select(BOMLine).where(BOMLine.id==lid,BOMLine.project_id==pid))
    if not row:raise HTTPException(404,'Line not found')
    for link in db.scalars(select(CandidateReview).where(CandidateReview.project_id==pid,CandidateReview.target_kind=='BOM',CandidateReview.target_id==lid)).all():db.delete(link)
    db.delete(row);p.updated_at=utcnow();p.status='DRAFT';record(db,user,'BOM_REMOVED',pid,{'id':lid});db.commit();return overview(db,p)


def validate_op(data):
    dec(data.hours,'hours',0);dec(data.rate,'operation rate',0)


@app.post('/api/projects/{pid}/operations')
def add_operation(pid:int,data:OpBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator');validate_op(data)
    if data.status=='APPROVED':raise HTTPException(403,'Procurement must approve operation rates separately')
    p=get_project(db,pid)
    row=Operation(project_id=pid,code=data.code,description=data.description,hours=data.hours,rate=data.rate,status='ASSUMED')
    db.add(row);db.flush()
    link_candidate(db,pid,data.source_document_id,data.source_candidate_index,'OPERATION',row.id,user)
    p.updated_at=utcnow();p.status='DRAFT';record(db,user,'OPERATION_ADDED',pid,{'code':data.code});db.commit();return overview(db,p)


@app.put('/api/projects/{pid}/operations/{oid}')
def save_operation(pid:int,oid:int,data:OpBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator');validate_op(data)
    if data.status=='APPROVED':raise HTTPException(403,'Procurement must approve operation rates separately')
    p=get_project(db,pid);o=db.scalar(select(Operation).where(Operation.id==oid,Operation.project_id==pid))
    if not o:raise HTTPException(404,'Operation not found')
    for key in ('code','description','hours','rate'):
        setattr(o,key,getattr(data,key))
    o.status='ASSUMED'
    link_candidate(db,pid,data.source_document_id,data.source_candidate_index,'OPERATION',o.id,user)
    p.updated_at=utcnow();p.status='DRAFT';record(db,user,'OPERATION_UPDATED',pid,{'id':oid});db.commit();return overview(db,p)


@app.post('/api/projects/{pid}/operations/{oid}/approve')
def approve_operation(pid:int,oid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'procurement')
    p=get_project(db,pid);o=db.scalar(select(Operation).where(Operation.id==oid,Operation.project_id==pid))
    if not o:raise HTTPException(404,'Operation not found')
    o.status='APPROVED';p.updated_at=utcnow();p.status='DRAFT';record(db,user,'OPERATION_RATE_APPROVED',pid,{'id':oid});db.commit();return overview(db,p)


@app.delete('/api/projects/{pid}/operations/{oid}')
def remove_operation(pid:int,oid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator');p=get_project(db,pid)
    o=db.scalar(select(Operation).where(Operation.id==oid,Operation.project_id==pid))
    if not o:raise HTTPException(404,'Operation not found')
    for link in db.scalars(select(CandidateReview).where(CandidateReview.project_id==pid,CandidateReview.target_kind=='OPERATION',CandidateReview.target_id==oid)).all():db.delete(link)
    db.delete(o);p.updated_at=utcnow();p.status='DRAFT';record(db,user,'OPERATION_REMOVED',pid,{'id':oid});db.commit();return overview(db,p)


def extract_candidates(text, pages, config=None, catalogue=None, source_kind='PDF'):
    # Source-linked, configuration-driven extraction. Candidate confidence is never human verification.
    fallback={'required_fields':[
        {'key':'length_mm','label':'Length','unit':'mm','aliases':['Overall Length']},
        {'key':'width_mm','label':'Width','unit':'mm','aliases':['Overall Width']},
        {'key':'height_mm','label':'Height','unit':'mm','aliases':['Overall Height']},
        {'key':'span_m','label':'Span','unit':'m'},
        {'key':'capacity_t','label':'Capacity','unit':'t','aliases':['SWL']}],
        'material_matchers':[]}
    return extract_generic_candidates(pages,config or fallback,catalogue or [],source_kind)


@app.post('/api/projects/{pid}/documents')
async def upload_pdf(pid:int,file:UploadFile=File(...),db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator','engineer')
    p=get_project(db,pid)
    if not file.filename or Path(file.filename).suffix.lower() not in ('.pdf','.docx'):
        raise HTTPException(415,'Only PDF and DOCX are supported for document extraction')
    body=await file.read(MAX_UPLOAD+1)
    if len(body)>MAX_UPLOAD:raise HTTPException(413,'Maximum file size is 15 MB')
    try:
        extracted,source_kind=local_document_text(file.filename,body,max_pages=60)
    except ValueError as e:raise HTTPException(422,str(e))
    except Exception:raise HTTPException(422,'Document could not be read (possibly damaged or encrypted)')
    stored=secrets.token_hex(24)+Path(file.filename).suffix.lower()
    (PRIVATE_DIR/stored).write_bytes(body)
    text='\n\n'.join(extracted)
    cfg=config_dict(get_config(db,p.product_code))
    candidates=extract_candidates(text,extracted,cfg,cfg.get('material_matchers',[]),source_kind)
    row=Document(project_id=pid,original_name=Path(file.filename).name[:240],stored_name=stored,
      checksum=hashlib.sha256(body).hexdigest(),pages=len(extracted),text=text[:200000],
      candidates=json.dumps(candidates,ensure_ascii=False))
    db.add(row);db.flush()
    # Reviewable prefill: one unambiguous value per named field, never a human approval.
    from collections import defaultdict
    options=defaultdict(list)
    for candidate in candidates:
        if candidate.get('kind')=='field' and candidate.get('value'):
            options[candidate['key']].append(candidate)
    suggested={}
    for key,matches in options.items():
        distinct={str(c['value']).strip() for c in matches}
        if len(distinct)!=1:
            continue  # conflicting values remain visible but unselected
        best=max(matches,key=lambda c:c.get('confidence_score',0))
        requirement=db.scalar(select(Requirement).where(Requirement.project_id==pid,Requirement.field_key==key))
        if requirement and not requirement.value.strip() and requirement.status!='APPROVED':
            requirement.value=str(best['value'])
            requirement.evidence='Extracted (unverified) from '+row.original_name+' | '+best['source_location']+' | '+best['evidence']
            requirement.document_id=row.id
            requirement.status='PENDING'
            requirement.updated_at=utcnow()
            suggested[key]=best
    if suggested:
        from .commercial import profile_for, js
        cp=profile_for(db,pid)
        if cp:
            technical=js(cp.technical,[])
            for section in technical:
                for field in section.get('fields',[]):
                    match=suggested.get(field.get('key'))
                    if match and not str(field.get('value','')).strip():
                        field['value']=match['value']
                        field['evidence']='Unverified '+row.original_name+' | '+match['evidence']
                        field['review_status']='PENDING'
            cp.technical=json.dumps(technical,ensure_ascii=False)
    p.updated_at=utcnow();p.status='DRAFT'
    record(db,user,'DOCUMENT_UPLOADED',pid,{'filename':row.original_name,'pages_or_sections':len(extracted),
      'checksum':row.checksum,'candidates':len(candidates),'autofilled_unverified_fields':list(suggested),'text_quality':bool(text.strip())})
    db.commit()
    return overview(db,p)


@app.post('/api/projects/{pid}/documents/{did}/candidates/{candidate_index}/dismiss')
def dismiss_candidate(pid:int,did:int,candidate_index:int,data:CandidateDismissBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator','engineer')
    p=get_project(db,pid)
    get_candidate(db,pid,did,candidate_index)
    entry=db.scalar(select(CandidateReview).where(CandidateReview.document_id==did,CandidateReview.candidate_index==candidate_index))
    if entry and entry.decision=='LINKED':
        raise HTTPException(409,'This candidate is linked to a record. Remove or correct the linked record before dismissing the source')
    _,candidate=get_candidate(db,pid,did,candidate_index)
    if candidate.get('kind')=='field':
        r=db.scalar(select(Requirement).where(Requirement.project_id==pid,Requirement.field_key==candidate.get('key')))
        if r and r.document_id==did and r.value==str(candidate.get('value','')):
            if r.status=='APPROVED':
                raise HTTPException(409,'Cannot dismiss a source behind an approved field; first reopen its engineering review')
            if r.evidence.startswith('Extracted (unverified)'):
                r.value='';r.evidence='';r.document_id=None;r.status='PENDING';r.updated_at=utcnow()
                sync_technical_requirement(db,pid,r)
    if entry is None:
        entry=CandidateReview(project_id=pid,document_id=did,candidate_index=candidate_index,
          decision='DISMISSED',user_id=user.id)
        db.add(entry)
    entry.decision='DISMISSED';entry.target_kind='';entry.target_id=None
    entry.note=data.explanation.strip();entry.user_id=user.id;entry.updated_at=utcnow()
    p.updated_at=utcnow();record(db,user,'DOCUMENT_CANDIDATE_DISMISSED',pid,{'document_id':did,'candidate_index':candidate_index,'reason':entry.note})
    db.commit();return overview(db,p)


@app.delete('/api/projects/{pid}/documents/{did}/candidates/{candidate_index}/dismiss')
def restore_candidate(pid:int,did:int,candidate_index:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'estimator','engineer')
    p=get_project(db,pid);get_candidate(db,pid,did,candidate_index)
    entry=db.scalar(select(CandidateReview).where(CandidateReview.document_id==did,CandidateReview.candidate_index==candidate_index))
    if entry and entry.decision=='DISMISSED':db.delete(entry)
    record(db,user,'DOCUMENT_CANDIDATE_RESTORED',pid,{'document_id':did,'candidate_index':candidate_index})
    db.commit();return overview(db,p)


@app.post('/api/projects/{pid}/bom/import')
async def import_bom(pid:int,file:UploadFile=File(...),db:Session=Depends(db_session),user:User=Depends(current_user)):
    """Import CSV/XLSX cost quantities as unapproved BOM lines; never import approval status."""
    import csv
    require_role(user,'estimator')
    p=get_project(db,pid)
    name=(file.filename or '').lower()
    if not name.endswith(('.csv','.xlsx')):
        raise HTTPException(415,'Upload CSV or XLSX')
    content=await file.read(1024*1024+1)
    if len(content)>1024*1024:raise HTTPException(413,'BOM import limited to 1 MB')
    try:
        if name.endswith('.csv'):
            rows=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
        else:
            from openpyxl import load_workbook
            book=load_workbook(io.BytesIO(content),read_only=True,data_only=True)
            sheet=book.active
            sheet.reset_dimensions()
            raw=list(sheet.iter_rows(values_only=True))
            if len(raw)>301:raise HTTPException(413,'Limit 300 BOM rows')
            keys=[str(x or '').strip().lower() for x in raw[0]]
            rows=[dict(zip(keys,row)) for row in raw[1:] if any(v is not None for v in row)]
        if len(rows)>300:raise HTTPException(413,'Limit 300 BOM rows')
        if not rows:raise HTTPException(422,'No BOM data found')
        for required in ('sku','qty','unit'):
            if required not in rows[0]:raise HTTPException(422,f'Missing column: {required}')
        for i,row in enumerate(rows,2):
            data=BOMBody(sku=str(row.get('sku') or '').strip(),qty=str(row.get('qty') or ''),unit=str(row.get('unit') or '').strip(),waste_pct=str(row.get('waste_pct') or '0'),status='ASSUMED',note=str(row.get('note') or 'Imported; quantity not reviewed')[:500])
            try:validate_bom(data,db,p)
            except HTTPException as exc:raise HTTPException(exc.status_code,f'Row {i}: {exc.detail}')
            db.add(BOMLine(project_id=pid,sku=data.sku,qty=data.qty,unit=data.unit,waste_pct=data.waste_pct,status='ASSUMED',note=data.note))
        db.flush()
        compute(db,p)  # all items and unit conversions must be valid before commit
        p.updated_at=utcnow();p.status='DRAFT'
        record(db,user,'BOM_IMPORTED',pid,{'filename':Path(file.filename).name,'rows':len(rows)})
        db.commit()
        return overview(db,p)
    except HTTPException:
        raise
    except (UnicodeDecodeError,KeyError,ValueError,IndexError,TypeError) as exc:
        raise HTTPException(422,'Could not parse BOM; expected columns sku, qty, unit, waste_pct, note')


@app.get('/api/projects/{pid}/documents/{did}/file')
def original_pdf(pid:int,did:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    get_project(db,pid)
    d=db.scalar(select(Document).where(Document.project_id==pid,Document.id==did))
    if not d:raise HTTPException(404,'Document missing')
    return FileResponse(PRIVATE_DIR/d.stored_name,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document' if d.stored_name.endswith('.docx') else 'application/pdf',filename=d.original_name,content_disposition_type='attachment' if d.stored_name.endswith('.docx') else 'inline',headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; sandbox"})


@app.get('/api/projects/{pid}/documents/{did}/extracted-text')
def document_text(pid:int,did:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    get_project(db,pid)
    d=db.scalar(select(Document).where(Document.project_id==pid,Document.id==did))
    if not d:raise HTTPException(404,'Document missing')
    return {'text':d.text[:50000],'pages':d.pages}


@app.get('/api/projects/{pid}/estimate')
def project_estimate(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    return overview(db,get_project(db,pid))


@app.post('/api/projects/{pid}/approve/{kind}')
def approve(pid:int,kind:str,data:ApprovalBody,db:Session=Depends(db_session),user:User=Depends(current_user)):
    if kind not in ('engineering','pricing','commercial'):raise HTTPException(404,'Unknown approval type')
    require_role(user,{'engineering':'engineer','pricing':'procurement','commercial':'commercial'}[kind])
    p=get_project(db,pid)
    if commercial.profile_for(db,p.id):
        raise HTTPException(409,'Use /commercial/approve/{kind} for customer-facing quotation approvals')
    cal=compute(db,p);g=checks(db,p,cal)
    if kind=='engineering' and not (g['drawing_complete'] and g['requirements_verified'] and g['quantities_approved']):
        raise HTTPException(409,'Engineering release gates incomplete')
    if kind=='pricing' and not g['rates_verified']:
        raise HTTPException(409,'Rates and operations must be approved first')
    if kind=='commercial':
        if not g['product_release_enabled']:
            raise HTTPException(409,'Product family is schema-only and cannot issue firm quotes')
        if not (g['engineering_approved'] and g['pricing_approved']):raise HTTPException(409,'Engineering and pricing approval needed first')
        engineer=db.scalar(select(Approval).where(Approval.project_id==pid,Approval.kind=='engineering',Approval.fingerprint==cal['fingerprint']).order_by(Approval.id.desc()))
        if engineer and engineer.user_id==user.id:
            raise HTTPException(409,'Commercial approval must be by a different user than engineering approval')
    db.add(Approval(project_id=pid,kind=kind,user_id=user.id,fingerprint=cal['fingerprint'],note=data.note))
    record(db,user,'APPROVED_'+kind.upper(),pid,{'fingerprint':cal['fingerprint'][:12]})
    db.commit();return overview(db,p)


def quote_pdf(p:Project,cfg:dict,overview_data:dict,firm=False,number=None):
    """Customer-facing PDF; do NOT show internal costs or margins."""
    output=io.BytesIO()
    doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=19*mm,leftMargin=19*mm,topMargin=17*mm,bottomMargin=17*mm)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BigTitleIQ',parent=styles['Title'],fontName='Helvetica-Bold',fontSize=19,leading=24,textColor=colors.HexColor('#12324b'),spaceAfter=12))
    styles.add(ParagraphStyle(name='IQMeta',parent=styles['Normal'],fontSize=9,leading=14,textColor=colors.HexColor('#526578')))
    styles.add(ParagraphStyle(name='IQBody',parent=styles['Normal'],fontSize=10,leading=15,spaceAfter=6))
    styles.add(ParagraphStyle(name='IQHeader',parent=styles['Heading2'],fontSize=11,spaceBefore=15,spaceAfter=7,textColor=colors.HexColor('#12324b')))
    def safe(x):
        from xml.sax.saxutils import escape
        return escape(str(x or ''))
    story=[Paragraph('INDUSTRIAL ESTIMATION',styles['BigTitleIQ']),Paragraph('TECHNICAL & COMMERCIAL OFFER' if firm else 'INTERNAL PROVISIONAL ESTIMATE — NOT FOR CUSTOMER ISSUE',styles['IQMeta']),Spacer(1,10*mm)]
    meta=[('Quote / Reference',number or (p.ref+'-DRAFT')),('Customer',p.customer),('Project',p.title),('Product family',cfg['label']),('Quantity',str(p.quantity)),('Date',date.today().isoformat())]
    table=Table([[Paragraph(safe(k),styles['IQMeta']),Paragraph(safe(v),styles['IQBody'])] for k,v in meta],colWidths=[49*mm,120*mm])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f0f4f8')),('LEFTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-2),.25,colors.HexColor('#d7e0e8'))]))
    story.extend([table,Paragraph('Technical specification',styles['IQHeader'])])
    for r in overview_data['requirements']:
        if r['value'] and not r['key'].endswith('_approved') and r['key']!='complete_drawing_set':
            label=next((f.get('label') or r['key'].replace('_',' ').title() for f in cfg.get('required_fields',[]) if f['key']==r['key']),r['key'].replace('_',' ').title())
            story.append(Paragraph(f'<b>{safe(label)}:</b> {safe(r["value"])} {safe(r["unit"])}',styles['IQBody']))
    story.append(Paragraph('Scope of supply',styles['IQHeader']))
    story.append(Paragraph(safe(p.scope or 'Scope to be confirmed during review.'),styles['IQBody']))
    story.append(Paragraph('Commercial summary',styles['IQHeader']))
    price=overview_data['estimate']['order_value']
    moneytable=Table([[Paragraph('Quantity',styles['IQMeta']),Paragraph(str(p.quantity),styles['IQBody'])],[Paragraph('Total offered price (INR)' if firm else 'Provisional price before tax (INR)',styles['IQMeta']),Paragraph(f'<b>INR {price}</b>',styles['IQBody'])]],colWidths=[87*mm,82*mm])
    moneytable.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f0f4f8')),('LEFTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)]))
    story.extend([moneytable,Paragraph('<b>Tax:</b> Applicable taxes are excluded and require confirmation.',styles['IQBody']),Paragraph('<b>Delivery:</b> '+safe(p.delivery),styles['IQBody']),Paragraph('<b>Payment terms:</b> '+safe(p.payment_terms),styles['IQBody']),Paragraph(f'<b>Validity:</b> {p.validity_days} days from issue date, subject to approval.',styles['IQBody'])])
    story.append(Paragraph('Exclusions and conditions',styles['IQHeader']))
    story.append(Paragraph(safe(p.exclusions or 'Specifications and commercial inclusions require confirmation.'),styles['IQBody']))
    if not firm:
        story.append(Paragraph('<b>WARNING:</b> This is an internal cost-based preview using potentially assumed quantities and provisional rates. It is not authorized for external issue, design manufacture, or certification.',styles['IQBody']))
    else:
        story.append(Paragraph('Released by authorized personnel under the recorded approval workflow. Engineering compliance and certification are separate activities.',styles['IQMeta']))
    def decorate(canvas, _doc):
        canvas.saveState()
        canvas.setFont('Helvetica',8)
        canvas.setFillColor(colors.HexColor('#708090'))
        canvas.drawString(19*mm,12*mm,'Generated by IndustriQuote • v0.1')
        canvas.drawRightString(190*mm,12*mm,f'Page {_doc.page}')
        if not firm:
            canvas.saveState()
            canvas.translate(A4[0]/2,A4[1]/2)
            canvas.rotate(45)
            canvas.setFont('Helvetica-Bold',31)
            canvas.setFillColor(colors.Color(.77,.18,.18,alpha=.12))
            canvas.drawCentredString(0,0,'PROVISIONAL - NOT FOR ISSUE')
            canvas.restoreState()
        canvas.restoreState()
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    return output.getvalue()


@app.get('/api/projects/{pid}/preview.pdf')
def pdf_preview(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    p=get_project(db,pid)
    if commercial.profile_for(db,p.id):return commercial.preview_commercial(pid,db,user)
    data=overview(db,p)
    from .standard_quote import preview_pdf as standard_preview_pdf
    return standard_preview_pdf(pid,db,user)


@app.post('/api/projects/{pid}/issue')
def issue(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'commercial')
    p=get_project(db,pid)
    if commercial.profile_for(db,p.id):
        commercial.issue_commercial(pid,db,user)
        return overview(db,p)
    from .standard_quote import issue_standard
    return issue_standard(pid, db, user)

@app.get('/api/projects/{pid}/issued/{iid}.pdf')
def issued_pdf(pid:int,iid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    get_project(db,pid)
    quote=db.scalar(select(IssuedQuote).where(IssuedQuote.project_id==pid,IssuedQuote.id==iid))
    if not quote:raise HTTPException(404,'Quotation missing')
    return FileResponse(PRIVATE_DIR/quote.stored_name,media_type='application/pdf',filename=quote.number+'.pdf',headers={'Cache-Control':'no-store'})


@app.get('/api/projects/{pid}/audit')
def audit_log(pid:int,db:Session=Depends(db_session),user:User=Depends(current_user)):
    get_project(db,pid)
    logs=db.scalars(select(Audit).where(Audit.project_id==pid).order_by(Audit.id.desc()).limit(100)).all()
    return [{'id':x.id,'action':x.action,'user_id':x.user_id,'at':str(x.at),'detail':json.loads(x.detail)} for x in logs]


@app.get('/api/auth/users')
def users(db: Session = Depends(db_session), user: User = Depends(current_user)):
    require_role(user, 'admin')
    return [public_user(u) for u in db.scalars(select(User).order_by(User.username)).all()]


class NewUser(BaseModel):
    username: str = Field(pattern=r'^[a-z0-9._-]{3,50}$')
    display_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=12, max_length=128)
    role: Literal['admin', 'estimator', 'engineer', 'procurement', 'commercial']
    email: str = Field(default='', max_length=254)
    phone: str = Field(default='', max_length=32)


@app.post('/api/auth/users')
def create_user(data: NewUser, db: Session = Depends(db_session), user: User = Depends(current_user)):
    require_role(user, 'admin')
    check_password_strength(data.password)
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(409, 'Username exists')
    row = User(username=data.username, display_name=data.display_name.strip(),
               password_hash=hashed_password(data.password), role=data.role,
               email=normalized_email(data.email), phone=data.phone.strip(),
               must_change_password=True)
    db.add(row)
    record(db, user, 'USER_CREATED', detail={'username': data.username, 'role': data.role})
    db.commit()
    return {'created': True, 'user': public_user(row)}


class EditUserBody(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(default='', max_length=254)
    phone: str = Field(default='', max_length=32)
    role: Literal['admin', 'estimator', 'engineer', 'procurement', 'commercial']
    active: bool
    admin_password: str


def confirm_admin_password(user: User, password: str):
    if not valid_password(password, user.password_hash):
        raise HTTPException(403, 'Administrator password is incorrect')


@app.put('/api/auth/users/{uid}')
def edit_user(uid: int, data: EditUserBody,
              db: Session = Depends(db_session), user: User = Depends(current_user)):
    require_role(user, 'admin')
    confirm_admin_password(user, data.admin_password)
    target = db.get(User, uid)
    if not target:
        raise HTTPException(404, 'User not found')
    if target.id == user.id:
        raise HTTPException(403, 'Edit your own details in My Profile; do not change your own role or status')
    if target.role == 'admin' and target.active and (data.role != 'admin' or not data.active):
        remaining_admin = db.scalars(select(User).where(User.role == 'admin', User.active.is_(True), User.id != target.id)).first()
        if not remaining_admin:
            raise HTTPException(409, 'Cannot remove the last active administrator')
    old_role, old_status = target.role, target.active
    target.display_name = data.display_name.strip()
    if len(target.display_name) < 2:
        raise HTTPException(422, 'Display name is too short')
    target.email = normalized_email(data.email)
    target.phone = data.phone.strip()
    target.role = data.role
    target.active = data.active
    if target.role != old_role or target.active != old_status:
        target.auth_version += 1  # Permissions or status changed: revoke all sessions.
    record(db, user, 'USER_UPDATED', detail={'username': target.username,
            'old_role': old_role, 'role': target.role, 'active': target.active})
    db.commit()
    return public_user(target)


@app.post('/api/auth/users/{uid}/reset-password')
def reset_user_password(uid: int, data: PasswordConfirmBody,
                        db: Session = Depends(db_session), user: User = Depends(current_user)):
    require_role(user, 'admin')
    confirm_admin_password(user, data.current_password)
    target = db.get(User, uid)
    if not target:
        raise HTTPException(404, 'User not found')
    if target.id == user.id:
        raise HTTPException(403, 'Use My Profile to change your own password or a saved recovery code')
    generated = secrets.token_urlsafe(18)  # 24 chars; shown to the admin only once.
    target.password_hash = hashed_password(generated)
    target.must_change_password = True
    target.auth_version += 1
    _clear_recovery_codes(db, target.id)
    record(db, user, 'ADMIN_PASSWORD_RESET', detail={'target_id': target.id})
    db.commit()
    return {'reset': True, 'username': target.username,
            'temporary_password': generated, 'must_change_password': True}


# Single-origin static app; no JS/CDN package installation required.
app.mount('/assets',StaticFiles(directory=ROOT/'frontend'/'assets'),name='assets') if (ROOT/'frontend'/'assets').exists() else None


@app.get('/')
def index():
    return FileResponse(ROOT/'frontend'/'index.html',media_type='text/html',headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'"})


@app.get('/favicon.ico')
def favicon():
    raise HTTPException(404)


# Register additive generic selling-price and source-conflict modules after base routes.
from . import company_settings, commercial, templates, word_quote_templates, standard_quote  # noqa: E402,F401
