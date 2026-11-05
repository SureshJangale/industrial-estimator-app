"""Single-company-per-installation configuration: white-label settings without tenant data leakage.

Deploy one isolated database and private-file directory per customer. This is NOT
an authorization boundary for multiple companies sharing one database.
Existing quotation profiles are deliberate snapshots; updating the company
settings changes only newly created quotations unless explicitly applied.
"""
from __future__ import annotations
import json
import re
from typing import Annotated
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, Session
from .app import Base, app, engine, SessionLocal, db_session, current_user, User, require_role, record, utcnow
from .company_defaults import fresh_branding

DEFAULT_UNITS=['Nos.','Set','Pair','kg','g','tonne','m','mm','cm','m2','m3','sqft','ft','litre','hour','day','job','lot','roll','box','unit','pc']

class CompanySettings(Base):
    __tablename__='company_settings'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    branding_json:Mapped[str]=mapped_column(Text,default='{}')
    quote_prefix:Mapped[str]=mapped_column(Text,default='YE')
    units_json:Mapped[str]=mapped_column(Text,default='[]')
    updated_at:Mapped[object]=mapped_column(DateTime,default=utcnow)

Base.metadata.create_all(engine)

def ensure_company(db:Session)->CompanySettings:
    s=db.get(CompanySettings,1)
    if s is None:
        b=fresh_branding()
        b['heading']='II Shri II'
        s=CompanySettings(id=1,branding_json=json.dumps(b,ensure_ascii=False),quote_prefix='YE',
                          units_json=json.dumps(DEFAULT_UNITS),updated_at=utcnow())
        db.add(s);db.flush()
    return s

def branding_for(db:Session)->dict:
    return dict(json.loads(ensure_company(db).branding_json))

def public(s:CompanySettings)->dict:
    return {'branding':json.loads(s.branding_json),'quote_prefix':s.quote_prefix,
            'units':json.loads(s.units_json),'updated_at':str(s.updated_at),
            'deployment_model':'SINGLE_COMPANY_ISOLATED_INSTALLATION'}

class SettingsInput(BaseModel):
    branding:dict
    quote_prefix:str=Field(min_length=2,max_length=12)
    units:list[str]=Field(min_length=1,max_length=100)

    @field_validator('branding')
    @classmethod
    def validate_brand(cls,b:dict):
        keys=('name','address','works_address','gstin','contact','signature_title','heading')
        if not str(b.get('name','')).strip():raise ValueError('Company name is required')
        if any(len(str(b.get(k,'')))>maxlen for k,maxlen in {
                'name':180,'address':450,'works_address':450,'gstin':40,
                'contact':300,'signature_title':120,'heading':80}.items()):
            raise ValueError('Company field is too long for a quotation')
        return {k:str(b.get(k,'')).strip() for k in keys}

    @field_validator('quote_prefix')
    @classmethod
    def validate_prefix(cls,value:str):
        if not re.fullmatch(r'[A-Za-z0-9_-]{2,12}',value):
            raise ValueError('Use 2-12 letters, digits, underscores or hyphens in the reference prefix')
        return value.upper()

    @field_validator('units')
    @classmethod
    def validate_units(cls,items:list[str]):
        cleaned=[]
        for raw in items:
            x=str(raw).strip()
            if not re.fullmatch(r'[\w][\w ./%+-]{0,23}',x,flags=re.UNICODE):
                raise ValueError('Units must be 1-24 characters and must not contain line breaks or markup')
            if x.casefold() not in [u.casefold() for u in cleaned]:cleaned.append(x)
        return cleaned

@app.get('/api/company-profile')
def company_profile(db:Session=Depends(db_session),user:User=Depends(current_user)):
    return public(ensure_company(db))

@app.put('/api/company-profile')
def change_company_profile(data:SettingsInput,db:Session=Depends(db_session),user:User=Depends(current_user)):
    require_role(user,'admin')
    s=ensure_company(db)
    before=public(s)
    s.branding_json=json.dumps(data.branding,ensure_ascii=False)
    s.quote_prefix=data.quote_prefix
    s.units_json=json.dumps(data.units,ensure_ascii=False)
    s.updated_at=utcnow()
    record(db,user,'COMPANY_PROFILE_UPDATED',detail={'old_company':before['branding'].get('name'),
          'new_company':data.branding['name'],'quote_prefix':data.quote_prefix,
          'new_company_settings_apply_to':'future projects only'})
    db.commit()
    return public(s)


def bootstrap_company_settings():
    """Persist first-install defaults independently of demo account seeding."""
    with SessionLocal() as db:
        ensure_company(db)
        db.commit()


bootstrap_company_settings()
