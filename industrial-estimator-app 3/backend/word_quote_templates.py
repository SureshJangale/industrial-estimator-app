"""Private, reviewed DOCX quotation layouts with controlled placeholder substitution.

Word templates are not executable. Import only DOCX files already containing
supported {{field.key}} placeholders. A repeated Word table row containing
{{price_lines.*}}, {{material_lines.*}}, {{operations.*}}, or
{{certifications.*}} is expanded from app data (not literal raw HTML).
"""
from __future__ import annotations
import copy
import hashlib
import io
import json
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET
from docx import Document as WordDocument
from fastapi import Depends, Form, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column, Session

from .app import (Base, app, engine, PRIVATE_DIR, db_session, current_user, User,
                  require_role, record, utcnow, get_project, pack_records)

TOKEN=re.compile(r'\{\{\s*([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)\s*\}\}')
SCALARS={
 'seller.name','seller.heading','seller.address','seller.contact','seller.signature_title','seller.gstin','seller.works_address',
 'buyer.name','buyer.address','buyer.attention','buyer.contact_name',
 'quote.number','quote.date','quote.status','quote.footer',
 'project.title','project.reference',
 'product.name','product.category','product.quantity','product.unit',
 'spec.length_mm','spec.width_mm','spec.height_mm','spec.steel_grade',
 'spec.mesh_opening','spec.mesh_wire_diameter_mm','spec.finish_colour',
 'spec.drawing_reference','spec.drawing_revision','spec.drawing_status',
 'spec.welding_requirement','spec.marking_text','spec.serial_marking','spec.fabrication_notes',
 'scope.description','scope.inclusions','scope.exclusions',
 'pricing.basis','pricing.currency','pricing.subtotal','pricing.tax_summary',
 'pricing.total','pricing.variable_charges','pricing.total_label',
 'commercial.payment','commercial.delivery','commercial.validity','commercial.inspection',
 'commercial.transport','commercial.packing','commercial.warranty','commercial.tax_note',
 'commercial.change_control'
}
COLLECTIONS={
 'price_lines':{'no','description','qty_unit','rate','amount','tax_code'},
 'tax_lines':{'name','rate','amount'},
 'material_lines':{'no','description','qty','unit_status'},
 'operations':{'no','description','scope'},
 'certifications':{'name','condition'},
}
ALLOWED=SCALARS | {group+'.'+x for group,fields in COLLECTIONS.items() for x in fields}
REQUIRED={'quote.number','buyer.name','product.name','pricing.total'}
MAX_DOCX_BYTES=8_000_000

class WordTemplateAsset(Base):
    __tablename__='word_template_assets'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    template_id:Mapped[int]=mapped_column(ForeignKey('quote_templates.id'),unique=True,index=True)
    stored_name:Mapped[str]=mapped_column(String(80))
    original_name:Mapped[str]=mapped_column(String(200))
    checksum:Mapped[str]=mapped_column(String(64))
    fields_json:Mapped[str]=mapped_column(Text,default='[]')
    created_at:Mapped[object]=mapped_column(DateTime,default=utcnow)

class WordTemplateAssetRevision(Base):
    __tablename__='word_template_asset_revisions'
    id:Mapped[int]=mapped_column(Integer,primary_key=True)
    template_id:Mapped[int]=mapped_column(ForeignKey('quote_templates.id'),index=True)
    version:Mapped[int]=mapped_column(Integer)
    stored_name:Mapped[str]=mapped_column(String(80))
    checksum:Mapped[str]=mapped_column(String(64))
    at:Mapped[object]=mapped_column(DateTime,default=utcnow)

Base.metadata.create_all(engine)


def asset_for(db,t):
    return db.scalar(select(WordTemplateAsset).where(WordTemplateAsset.template_id==t.id)) if t else None


def safe_docx(data:bytes):
    if not data.startswith(b'PK') or len(data)>MAX_DOCX_BYTES:
        raise HTTPException(422,'Use a .docx document smaller than 8 MB')
    try:
        with ZipFile(io.BytesIO(data)) as z:
            names=z.namelist()
            if len(names)>450 or sum(x.file_size for x in z.infolist())>28_000_000:
                raise HTTPException(422,'Word document is too large or complex')
            if 'word/document.xml' not in names or '[Content_Types].xml' not in names:
                raise HTTPException(422,'Not a valid DOCX document')
            if any('vbaProject' in n or 'embeddings/' in n or n.startswith('word/activeX/') for n in names):
                raise HTTPException(422,'Macros and embedded objects are not supported')
            for name in names:
                if name.endswith('.rels'):
                    try:
                        relationships=ET.fromstring(z.read(name))
                    except ET.ParseError as ex:
                        raise HTTPException(422,'Malformed Word relationships') from ex
                    for rel in relationships:
                        if rel.attrib.get('TargetMode','').lower()=='external':
                            raise HTTPException(422,'External links in uploaded Word templates are not permitted')
        doc=WordDocument(io.BytesIO(data))
    except HTTPException:raise
    except (BadZipFile,ValueError,KeyError,Exception) as ex:
        raise HTTPException(422,'Unable to read Word document') from ex
    fields=extract_tokens(doc)
    if not REQUIRED.issubset(fields):
        raise HTTPException(422,'Required template placeholders missing: '+', '.join(sorted(REQUIRED-fields)))
    if fields-ALLOWED:
        raise HTTPException(422,'Unsupported placeholders: '+', '.join(sorted(fields-ALLOWED)))
    return sorted(fields)


def walk(doc):
    for paragraph in doc.paragraphs:yield paragraph
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:yield p
    for section in doc.sections:
        for sec in (section.header,section.footer):
            for p in sec.paragraphs:yield p
            for t in sec.tables:
                for row in t.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:yield p


def extract_tokens(doc):
    return set().union(*(set(TOKEN.findall(p.text)) for p in walk(doc)))


def replace_paragraph(par,values,allow_groups=True):
    old=par.text
    new=TOKEN.sub(lambda m:str(values.get(m.group(1),'PENDING REVIEW')),old)
    if new==old:return
    # Retain paragraph formatting and per-token styling when each token is a run;
    # fall back to the first run if Word split a placeholder across many runs.
    if all(not ('{{' in r.text and '}}' not in r.text) for r in par.runs):
        for r in par.runs:
            r.text=TOKEN.sub(lambda m:str(values.get(m.group(1),'PENDING REVIEW')),r.text)
    else:
        if par.runs:
            par.runs[0].text=new
            for r in par.runs[1:]:r.text=''
        else:par.add_run(new)


def render_word(source:bytes,context:dict)->bytes:
    doc=WordDocument(io.BytesIO(source))
    # The supplied one-page format prints rupees in the price cells but plain
    # numbers in subtotal/tax totals. Adapt display only, never the cost math.
    master=Path(__file__).resolve().parents[1]/'data'/'Quote73_One_Page_Reusable_Template.docx'
    stock=master.is_file() and hashlib.sha256(source).digest()==hashlib.sha256(master.read_bytes()).digest()
    if stock:
        from .quote73_exact import fmt_money
        context={**context,'scalars':dict(context['scalars']),
                 'price_lines':[dict(x) for x in context.get('price_lines',[])],
                 'tax_lines':[dict(x) for x in context.get('tax_lines',[])]}
        for row in context['price_lines']:
            for key in ('rate','amount'):
                raw=str(row.get(key,'') or '')
                if re.fullmatch(r'\d+(?:\.\d+)?',raw):
                    row[key]='₹ '+fmt_money(raw)
        for row in context['tax_lines']:
            row['amount']=str(row.get('amount','')).replace('INR ','',1)
        for key in ('pricing.subtotal','pricing.total'):
            raw=str(context['scalars'].get(key,'') or '')
            context['scalars'][key]=raw.replace('INR ','',1)
        if not context.get('is_synthetic') and 'NOT FINAL' in context['scalars'].get('pricing.total',''):
            context['scalars']['pricing.total']='PENDING'
    scalars=context['scalars']
    for table in doc.tables:
        for row in list(table.rows):
            used=set()
            for cell in row.cells:
                for par in cell.paragraphs:
                    used.update(TOKEN.findall(par.text))
            groups={n.split('.')[0] for n in used if n.split('.')[0] in COLLECTIONS}
            if groups:
                if len(groups)>1:raise HTTPException(422,'A dynamic row may reference only one collection')
                group=groups.pop()
                entries=context.get(group,[])
                if not entries and group!='tax_lines':
                    entries=[{col:'Not specified' for col in COLLECTIONS[group]}]
                anchor=row._tr
                for entry in entries[:150]:
                    cloned=copy.deepcopy(row._tr)
                    anchor.addnext(cloned);anchor=cloned
                    # XML clone has no python-docx table row wrapper; wrap fresh list item
                    from docx.table import _Row
                    wr=_Row(cloned,table)
                    vals={**scalars,**{group+'.'+field:str(entry.get(field,'Not specified')) for field in COLLECTIONS[group]}}
                    for cell in wr.cells:
                        for par in cell.paragraphs:replace_paragraph(par,vals)
                table._tbl.remove(row._tr)
            else:
                for cell in row.cells:
                    for par in cell.paragraphs:replace_paragraph(par,scalars)
    # tables already processed; only document-level paragraphs and header/footer now
    for par in doc.paragraphs:replace_paragraph(par,scalars)
    for section in doc.sections:
        for sec in (section.header,section.footer):
            for par in sec.paragraphs:replace_paragraph(par,scalars)
            for table in sec.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for par in cell.paragraphs:replace_paragraph(par,scalars)
    # The measured Quote 73 Word fallback has a tall blank item area.
    # Repeating multiple quotation rows must consume that spacer, not push
    # the original closing/footer to a new sheet. Only alter our own stock
    # document, never an uploaded customer-authored Word design.
    if stock:
        from docx.shared import Inches
        n=max(1,len(context.get('price_lines',[]) or []))
        # Extra rows expand in height as their descriptions wrap. Shrink the
        # empty schedule area conservatively, preserving a visible blank region.
        empty_rows=[row for table in doc.tables for row in table.rows
                    if row.height and row.height.inches > 1.5 and not row.cells[0].text.strip()]
        if empty_rows:
            empty_rows[0].height=Inches(max(.35,2.69-0.52*(n-1)))
    out=io.BytesIO();doc.save(out)
    return out.getvalue()


def docx_to_pdf(word:bytes)->bytes:
    exe=shutil.which('libreoffice') or shutil.which('soffice')
    if not exe:
        # LibreOffice.app on macOS does not normally put soffice on the user's PATH.
        for candidate in (Path('/Applications/LibreOffice.app/Contents/MacOS/soffice'),
                          Path.home()/'Applications/LibreOffice.app/Contents/MacOS/soffice'):
            if candidate.is_file():
                exe=str(candidate)
                break
    if not exe:
        raise HTTPException(503,'LibreOffice is required to produce PDFs from Word layouts. Install the free LibreOffice app on the server.')
    with tempfile.TemporaryDirectory(prefix='iq_word_layout_') as tmp:
        root=Path(tmp);src=root/'generated.docx';src.write_bytes(word)
        uri=(root/'profile').as_uri()
        args=[exe,'-env:UserInstallation='+uri,'--headless','--convert-to','pdf:writer_pdf_Export','--outdir',tmp,str(src)]
        try:
            result=subprocess.run(args,capture_output=True,text=True,timeout=45,cwd=tmp)
        except subprocess.TimeoutExpired as ex:
            raise HTTPException(503,'Word PDF conversion exceeded the safe time limit') from ex
        out=root/'generated.pdf'
        if result.returncode!=0 or not out.exists() or out.stat().st_size<500:
            raise HTTPException(503,'LibreOffice could not convert this DOCX to PDF')
        return out.read_bytes()


def val(s):
    if s is None:return 'PENDING REVIEW'
    x=str(s).strip()
    return x if x else 'PENDING REVIEW'


def context_for(p,profile,state,firm=False,number=None,db=None,synthetic=False):
    """Only public/spec/commercial fields. Internal unit-cost data is NEVER exported."""
    terms=profile.get('terms') or {}; brand=profile.get('branding') or {}
    pricing=(state.get('pricing') or {})
    specs={}
    for section in profile.get('technical',[]):
        for f in section.get('fields',[]):
            if f.get('key') and f.get('value'):
                specs[f['key']]=(str(f['value']),f.get('review_status','PENDING'))
    bom=[];operations=[];reqs=[];documents=[]
    if db is not None:
        reqs,bom,operations,documents=pack_records(db,p)
    for f in reqs:
        if f.value and f.field_key not in specs:specs[f.field_key]=(f.value,f.status)
    def field(key):
        value,status=specs.get(key,('', 'PENDING'))
        if not value:return 'PENDING REVIEW'
        return value if status=='APPROVED' else value+' (UNVERIFIED)'
    # No inference: material schedule is populated only from the explicit BOM or
    # evidence-linked extracted material *names*, never from generic allowed SKUs.
    materials=[]; known_sku=set()
    from .app import Price
    for line in bom:
        price=db.scalar(select(Price).where(Price.sku==line.sku)) if db else None
        materials.append({'no':str(len(materials)+1),'description':price.description if price else line.sku,
           'qty':line.qty if line.status=='APPROVED' else val(line.qty)+' (unverified)',
           'unit_status':line.unit+' / '+line.status})
        known_sku.add(line.sku)
    if not bom and documents:
        from .commercial import js
        for d in documents:
            for c in js(d.candidates,[]):
                if c.get('kind')=='material' and c.get('sku') not in known_sku:
                    known_sku.add(c['sku'])
                    materials.append({'no':str(len(materials)+1),'description':c['value'],
                        'qty':'PENDING','unit_status':'UNVERIFIED - extract only'})
    op_rows=[{'no':str(i+1),'description':o.description,'scope':o.status} for i,o in enumerate(operations)]
    certs=terms.get('certifications') or []
    certification_rows=[{'name':c.get('name',''),'condition':c.get('condition','')} if isinstance(c,dict) else {'name':str(c),'condition':'As agreed'} for c in certs]
    price_rows=[]
    for i,line in enumerate(pricing.get('lines',[])):
        mode=line.get('mode','')
        amount=line.get('line_total')
        if mode=='AT_ACTUAL': amount='At actual - extra'
        elif mode=='EXCLUDED':amount='Excluded'
        elif mode=='INCLUDED':amount='Included'
        elif mode=='NOTE':amount='Description only'
        elif not amount:amount='PRICE PENDING'
        price_rows.append({'no':str(i+1),'description':val(line.get('description')),
            'qty_unit':((line.get('qty') or '')+' '+(line.get('unit') or '')).strip() or '-',
            'rate':(line.get('price') or '-') if mode in ('FIXED','UNIT_RATE') else '-',
            'amount':str(amount),'tax_code':val(line.get('tax_code') or 'Not specified')})
    tax=pricing.get('tax_components',[])
    status='ISSUED' if firm else 'DRAFT - FOR REVIEW ONLY'
    ref=number or profile.get('external_reference') or p.ref+' / DRAFT'
    drawing_name=documents[-1].original_name if documents else 'PENDING SOURCE DRAWING'
    extra=pricing.get('additional_at_actual',[])
    incomplete=pricing.get('unpriced_lines',[])
    subtotal=pricing.get('subtotal_known','')
    taxsum='; '.join(str(x.get('name',''))+' '+str(x.get('rate',''))+'%: INR '+str(x.get('amount','')) for x in tax) or 'Tax basis pending approval'
    known_total=pricing.get('known_total_including_tax','')
    tax_known=bool(known_total and pricing.get('tax_status')=='APPROVED')
    finalized=bool(pricing.get('grand_total_definitive') and tax_known)
    scalars={
      'seller.name':val(brand.get('name')),'seller.heading':str(brand.get('heading','') or ''),'seller.address':val(brand.get('address')),
      'seller.contact':val(brand.get('contact')),'seller.signature_title':val(brand.get('signature_title')),
      'seller.gstin':val(brand.get('gstin')),'seller.works_address':val(brand.get('works_address')),
      'buyer.name':val(p.customer),'buyer.address':val(terms.get('customer_address')),
      'buyer.attention':val(terms.get('customer_attention')),
      'buyer.contact_name':val(terms.get('customer_attention')),
      'quote.number':str(ref),'quote.date':date.today().strftime('%d/%m/%Y'),
      'quote.status':status,'quote.footer':val(terms.get('footer') or 'Controlled industrial quotation | '+str(ref)),
      'project.title':p.title,'project.reference':p.ref,
      'product.name':p.title,'product.category':getattr(p,'product_code','fabricated_assembly'),
      'product.quantity':str(p.quantity),'product.unit':str(terms.get('product_unit') or 'Nos.'),
      'spec.length_mm':field('length_mm'),'spec.width_mm':field('width_mm'),'spec.height_mm':field('height_mm'),
      'spec.steel_grade':field('steel_grade'),'spec.mesh_opening':val(terms.get('mesh_opening')),
      'spec.mesh_wire_diameter_mm':field('mesh_wire_diameter_mm'),
      'spec.finish_colour':field('finish_colour'),'spec.drawing_reference':drawing_name,
      'spec.drawing_revision':field('drawing_revision'),
      'spec.drawing_status':field('complete_drawing_set'),
      'spec.welding_requirement':val(terms.get('welding_requirement')),
      'spec.marking_text':val(terms.get('marking_text')),
      'spec.serial_marking':val(terms.get('serial_marking')),
      'spec.fabrication_notes':val(terms.get('fabrication_notes')),
      'scope.description':val(terms.get('scope') or p.scope),'scope.inclusions':val(terms.get('inclusions')),
      'scope.exclusions':val(terms.get('exclusions') or p.exclusions),
      'pricing.basis':val(terms.get('pricing_basis') or 'Approved selling price schedule'),
      'pricing.currency':'INR','pricing.subtotal':('INR '+str(subtotal) if any((x.get('mode') in ('FIXED','UNIT_RATE') and x.get('line_total') is not None) for x in pricing.get('lines',[])) else 'PENDING'),
      'pricing.tax_summary':taxsum,'pricing.total':'INR '+str(known_total) if tax_known and finalized else 'NOT FINAL - pending approval / extras',
      'pricing.variable_charges':'; '.join(extra) if extra else ('Unpriced lines remain' if incomplete else 'None declared'),
      'pricing.total_label':'Definitive total (approved tax included)' if finalized else 'Known amounts are not a definitive total',
      'commercial.payment':val(terms.get('payment')),'commercial.delivery':val(terms.get('delivery')),
      'commercial.validity':(str(terms.get('validity_days'))+' days' if terms.get('validity_days') is not None else 'PENDING'),
      'commercial.inspection':val(terms.get('inspection')),'commercial.transport':val(terms.get('transport')),
      'commercial.packing':val(terms.get('packing')),'commercial.warranty':val(terms.get('warranty')),
      'commercial.tax_note':taxsum,'commercial.change_control':val(terms.get('change_control') or 'Any specification changes may require a revised price and lead time.'),
    }
    tax_rows=[{'name':str(t.get('name','Tax')), 'rate':str(t.get('rate','')),
               'amount':'INR '+str(t.get('amount','PENDING')) if pricing.get('tax_status')=='APPROVED' else 'PENDING TAX REVIEW'} for t in tax]
    if not tax_rows and pricing.get('tax_status')!='APPROVED':
        tax_rows=[{'name':'Tax basis requires review','rate':'-', 'amount':'PENDING'}]
    return {'scalars':scalars,'is_synthetic':synthetic,'price_lines':price_rows,'tax_lines':tax_rows,'material_lines':materials,
        'operations':op_rows,'certifications':certification_rows}


def synthetic_pallet_context():
    """Synthetic business identity and quote; real engineering section labels from drawing are still unverified."""
    from types import SimpleNamespace
    p=SimpleNamespace(ref='PALLET-SAMPLE-001',title='Fabricated steel pallet (synthetic sample)',
       product_code='fabricated_pallet',customer='SAMPLE CUSTOMER (SYNTHETIC)',quantity=1,scope='',exclusions='')
    from .company_defaults import fresh_branding
    profile={'external_reference':'SAMPLE-PALLET-001','branding':fresh_branding(),
      'technical':[{'title':'Pallet','fields':[{'key':k,'value':v,'review_status':'PENDING'} for k,v in {'length_mm':'1100','width_mm':'550','height_mm':'750'}.items()]}],
      'terms':{'customer_attention':'Mr. Test Contact (fictional)','scope':'Fabrication and supply of one steel pallet to approved drawings','payment':'To be agreed',
         'delivery':'To be agreed after approved drawing and order', 'validity_days':15,
         'mesh_opening':'1 inch x 1 inch (drawing note)',
         'welding_requirement':'All joints full welded (drawing note; engineer to confirm)',
         'marking_text':'Example pallet marking on four sides (review customer-approved text)',
         'serial_marking':'Serial number to be stencilled (drawing note)',
         'finish_colour':'To be confirmed','inclusions':'Fabrication, welding and marking subject to scope approval',
         'exclusions':'No confirmed cut lengths, freight, installation or coatings schedule',
         'inspection':'Quality checks per approved inspection plan',
         'warranty':'To be agreed','transport':'Excluded unless separately quoted',
         'certifications':[{'name':'Material test certificate','condition':'Subject to agreed procurement scope'}]}}
    state={'pricing':{'lines':[{'mode':'FIXED','description':'Supply of one fabricated industrial pallet','qty':'1','unit':'Nos.',
          'price':'','line_total':None},{'mode':'AT_ACTUAL','description':'Transport if requested','qty':'','unit':'','price':'','line_total':None}],
       'subtotal_known':'0.00','tax_components':[],'known_total_including_tax':'0.00',
       'tax_status':'PENDING','grand_total_definitive':False,'additional_at_actual':['Transport if requested'],
       'unpriced_lines':[{'line_id':0}]}}
    result=context_for(p,profile,state,synthetic=True)
    material_names=['SQ TUBE 40X40X3MM','MS FLAT 40X8MM','MS ANGLE 40X40X5MM',
       'MS FLAT 25X3MM','MS MESH 1inchX1inch','MS ANGLE 40X40X3MM','MS SHEET 1.6MM THK']
    result['material_lines']=[{'no':str(i+1),'description':x,'qty':'Not determined',
       'unit_status':'FROM DRAWING / UNVERIFIED'} for i,x in enumerate(material_names)]
    result['operations']=[{'no':str(i+1),'description':x,'scope':'Candidate only - requires approval'} for i,x in enumerate(['Cutting','Welding','Painting / finish','Stencilling and serial marking','Inspection'])]
    result['scalars']['spec.drawing_reference']='SYNTHETIC PALLET DRAWING - reference only'
    result['scalars']['spec.drawing_revision']='Unknown'
    result['scalars']['spec.drawing_status']='Drawing set completeness unconfirmed'
    result['scalars']['spec.steel_grade']='PENDING REVIEW'
    result['scalars']['spec.mesh_wire_diameter_mm']='PENDING REVIEW'
    result['scalars']['spec.finish_colour']='PENDING REVIEW'
    return result


def render_asset_pdf(asset,context):
    src=(PRIVATE_DIR/asset.stored_name).read_bytes()
    # The supplied Quote 73 form is a fixed one-page grid, not simply a set of
    # Word headings. For the intact stock layout, use the measured reference
    # geometry. If an admin replaces the DOCX, their uploaded Word file takes
    # precedence and is rendered normally (without silently ignoring edits).
    master=Path(__file__).resolve().parents[1]/'data'/'Quote73_One_Page_Reusable_Template.docx'
    if asset.original_name==master.name and master.is_file() and hashlib.sha256(src).digest()==hashlib.sha256(master.read_bytes()).digest():
        from .quote73_exact import render_quote73, LayoutOverflow
        try:
            return render_quote73(context)
        except LayoutOverflow as err:
            raise HTTPException(422, 'Quote 73 is a fixed one-page layout: '+str(err)) from err
    return docx_to_pdf(render_word(src,context))


@app.post('/api/quote-templates/import-docx')
async def upload_word_layout(code:str=Form(...),name:str=Form(...),workflow:str=Form(...),
                              file:UploadFile=File(...),db:Session=Depends(db_session),
                              user:User=Depends(current_user)):
    from .templates import QuoteTemplate,get_template,DEFAULTS,public
    require_role(user,'admin')
    if workflow not in ('equipment_supply','service_repair','general_sale'):
        raise HTTPException(422,'Invalid quotation workflow')
    if not re.fullmatch('[a-z][a-z0-9_]{2,63}',code):
        raise HTTPException(422,'Template code must use lowercase letters, digits and underscores')
    if not (3<=len(name.strip())<=150):raise HTTPException(422,'Template name must be 3-150 characters')
    if not (file.filename or '').lower().endswith('.docx'):
        raise HTTPException(422,'Upload a non-macro Word quotation template (.docx)')
    if get_template(db,code):raise HTTPException(409,'Template code already exists')
    blob=await file.read(MAX_DOCX_BYTES+1)
    fields=safe_docx(blob)
    layout=next(layout for base,_name,wf,layout in DEFAULTS if wf==workflow).copy()
    layout['title']=name.strip()[:120]
    t=QuoteTemplate(code=code,name=name.strip(),workflow=workflow,
        layout_json=json.dumps(layout),version=1,is_builtin=False,is_default=False,created_by=user.id)
    db.add(t);db.flush()
    stored='word_'+secrets.token_hex(16)+'.docx'
    (PRIVATE_DIR/stored).write_bytes(blob)
    db.add(WordTemplateAsset(template_id=t.id,stored_name=stored,original_name=file.filename[:200],
       checksum=hashlib.sha256(blob).hexdigest(),fields_json=json.dumps(fields)))
    record(db,user,'WORD_QUOTE_LAYOUT_UPLOADED',detail={'code':code,'fields':len(fields)})
    db.commit();return public(t)


@app.put('/api/quote-templates/{code}/replace-docx')
async def replace_word_layout(code:str,file:UploadFile=File(...),db:Session=Depends(db_session),
                              user:User=Depends(current_user)):
    from .templates import get_template,public,TemplateRevision
    require_role(user,'admin')
    t=get_template(db,code);asset=asset_for(db,t)
    if not t or not asset:raise HTTPException(404,'Word layout not found')
    if not (file.filename or '').lower().endswith('.docx'):raise HTTPException(422,'Expected .docx')
    blob=await file.read(MAX_DOCX_BYTES+1);fields=safe_docx(blob)
    db.add(TemplateRevision(template_id=t.id,version=t.version,layout_json=t.layout_json,
       name=t.name,edited_by=user.id))
    db.add(WordTemplateAssetRevision(template_id=t.id,version=t.version,stored_name=asset.stored_name,
       checksum=asset.checksum))
    asset.stored_name='word_'+secrets.token_hex(16)+'.docx'
    (PRIVATE_DIR/asset.stored_name).write_bytes(blob)
    asset.original_name=file.filename[:200];asset.checksum=hashlib.sha256(blob).hexdigest()
    asset.fields_json=json.dumps(fields);t.version+=1;t.updated_at=utcnow()
    record(db,user,'WORD_QUOTE_LAYOUT_REPLACED',detail={'code':code,'version':t.version})
    db.commit();return public(t)


@app.get('/api/quote-templates/{code}/source.docx')
def download_word_layout(code:str,db:Session=Depends(db_session),user:User=Depends(current_user)):
    from .templates import get_template
    require_role(user,'admin')
    t=get_template(db,code);asset=asset_for(db,t)
    if not t or not asset:raise HTTPException(404,'No uploaded Word file for this template')
    src=(PRIVATE_DIR/asset.stored_name).read_bytes()
    return Response(src,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition':'attachment; filename="'+code+'.docx"','Cache-Control':'no-store'})


@app.get('/api/quote-templates/example-pallet.docx')
def download_example_pallet_word(user:User=Depends(current_user)):
    """Synthetic reusable Word layout; never treated as a project design upload."""
    require_role(user,'admin')
    path=Path(__file__).resolve().parents[1]/'data'/'Pallet_Quotation_Reusable_Template.docx'
    return Response(path.read_bytes(),
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition':'attachment; filename="Pallet_Quotation_Reusable_Template.docx"',
                 'Cache-Control':'no-store'})



# Quote 73-inspired, single-page commercial quotation style.
# Original customer/quote number/price are never embedded in the reusable Word file.
def synthetic_quote73_context(branding=None):
    from types import SimpleNamespace
    p=SimpleNamespace(ref='SAMPLE-QUOT-001',title='Pallet lifting chain (sample supply)',
        product_code='general_sale',customer='SAMPLE CUSTOMER (SYNTHETIC)',quantity=1,scope='',exclusions='')
    from .company_defaults import fresh_branding
    profile={'external_reference':'SAMPLE-001/YE',
        'branding':branding or fresh_branding(),
        'technical':[],
        'terms':{'customer_address':'Sample Industrial Area','customer_attention':'Ms. A. Sample (fictional)',
             'scope':'Supply of a chain set to customer-approved specification',
             'payment':'As agreed','validity_days':15}}
    state={'pricing':{'lines':[{'mode':'FIXED',
            'description':'Illustrative pallet lifting chain set, 2.6 m (4 pieces), 8 mm diameter - subject to approved specification',
            'qty':'1','unit':'set','price':'15500.00','line_total':'15500.00','tax_code':''}],
        'subtotal_known':'15500.00',
        'tax_components':[{'name':'CGST','rate':'9','amount':'1395.00'},
                          {'name':'SGST','rate':'9','amount':'1395.00'}],
        'known_total_including_tax':'18290.00','tax_status':'APPROVED',
        'grand_total_definitive':True,'additional_at_actual':[], 'unpriced_lines':[]}}
    return context_for(p,profile,state)


def bootstrap_quote73_defaults():
    """Install the supplied Quote 73 visual style as the default for new quotations.

    Runs once per quote workflow. On future restarts admin overrides are preserved.
    Existing quote records retain their explicitly saved template code.
    """
    from .app import SessionLocal
    from .templates import QuoteTemplate, DEFAULTS
    docx_path=Path(__file__).resolve().parents[1]/'data'/'Quote73_One_Page_Reusable_Template.docx'
    raw=docx_path.read_bytes()
    fields=safe_docx(raw)
    assert {'quote.number','buyer.name','product.name','pricing.total'}<=set(fields)
    workflows=[('equipment_supply','quote73_equipment'),
               ('service_repair','quote73_service'),
               ('general_sale','quote73_general')]
    with SessionLocal() as db:
        for workflow,code in workflows:
            old=db.scalar(select(QuoteTemplate).where(QuoteTemplate.code==code))
            if old:
                # Update an untouched stock v1 Word fallback when the shipped
                # placeholder contract evolves. Do not touch admin-replaced layouts.
                asset=asset_for(db,old)
                if old.is_builtin and old.version==1 and asset and asset.original_name==docx_path.name:
                    current=(PRIVATE_DIR/asset.stored_name).read_bytes()
                    if hashlib.sha256(current).hexdigest()!=hashlib.sha256(raw).hexdigest():
                        db.add(WordTemplateAssetRevision(template_id=old.id,version=old.version,
                            stored_name=asset.stored_name,checksum=asset.checksum))
                        stored='default_quote73_v07_'+workflow+'.docx'
                        (PRIVATE_DIR/stored).write_bytes(raw)
                        asset.stored_name=stored;asset.checksum=hashlib.sha256(raw).hexdigest()
                        asset.fields_json=json.dumps(fields)
                        old.version+=1;old.updated_at=utcnow()
                continue  # Keep the admin-selected default unchanged.
            layout=next(dict(raw_layout) for (_c,_n,wf,raw_layout) in DEFAULTS if wf==workflow)
            layout['title']='STANDARD QUOTATION'
            template=QuoteTemplate(code=code,
                name='Classic one-page | Quote 73 reference pattern',workflow=workflow,
                layout_json=json.dumps(layout),version=1,is_builtin=True,is_default=True)
            db.add(template)
            db.flush()
            stored=f'default_quote73_{workflow}.docx'
            (PRIVATE_DIR/stored).write_bytes(raw)
            db.add(WordTemplateAsset(template_id=template.id,stored_name=stored,
                original_name=docx_path.name,checksum=hashlib.sha256(raw).hexdigest(),
                fields_json=json.dumps(fields)))
            for row in db.scalars(select(QuoteTemplate).where(QuoteTemplate.workflow==workflow)).all():
                row.is_default=(row.id==template.id)
        db.commit()


bootstrap_quote73_defaults()
