"""Initialize product packs, public/synthetic demo rates and optional sandbox users/jobs.

Do not seed actual proprietary user drawings or customer data.
"""
import argparse
import json
import os
from pathlib import Path
from sqlalchemy import select
from .app import SessionLocal, User, ProductConfig, Price, Project, Requirement, BOMLine, Operation, hashed_password, utcnow, ROOT, record


def load_defaults(demo=False):
    source=ROOT/'data'
    from .company_settings import ensure_company
    with SessionLocal() as db:
        ensure_company(db)
        if demo:
            known_accounts={'demo','estimator','engineer','procurement','commercial'}
            existing=db.scalars(select(User)).all()
            if any(u.username not in known_accounts for u in existing):
                raise SystemExit('Refusing to add demo accounts to a non-demo database')
            existing_projects=db.scalars(select(Project)).all()
            if any(p.ref not in {'PALLET-PROOF-001','CONVEYOR-PROOF-001'} for p in existing_projects):
                raise SystemExit('Refusing to seed a database containing non-demo projects')
        for file in ('fabricated_pallet.json','belt_conveyor.json','eot_crane.json'):
            cfg=json.loads((source/file).read_text())
            code=cfg['product_type']
            if db.scalar(select(ProductConfig).where(ProductConfig.code==code)):
                continue
            fields=[]
            for f in cfg.get('required_fields',[]):
                label_key=f['key']
                unit=f.get('unit') or ''
                if unit and label_key.endswith('_'+unit.replace('/','_')):
                    label_key=label_key[:-(len(unit)+1)]
                fields.append({'key':f['key'],'label':label_key.replace('_',' ').title(),'unit':unit,'firm_required':bool(f.get('firm_required',False)),'aliases':f.get('aliases',[]),'extraction_type':f.get('extraction_type',''),'exclude_prefixes':f.get('exclude_prefixes',[])})
            clean={'product_type':code,'label':cfg['label'],'config_version':cfg['config_version'],'required_fields':fields,'allowed_components':cfg['allowed_components'],'required_operations':cfg['required_operations'],'requires_document':True,'firm_release_enabled':code!='eot_crane','notes':cfg.get('notes',''),'material_matchers':cfg.get('material_matchers',[]),'specification_sections':cfg.get('specification_sections',[])}
            db.add(ProductConfig(code=code,label=cfg['label'],version=cfg['config_version'],definition=json.dumps(clean)))
        # Blank-slate generic pack: add any catalogue SKU, with manually verified quantities.
        if not db.scalar(select(ProductConfig).where(ProductConfig.code=='general_fabrication')):
            data={'product_type':'general_fabrication','label':'General made-to-order fabrication','config_version':'1.0.0','required_fields':[{'key':'job_specification','label':'Approved job specification','unit':'','firm_required':True},{'key':'drawing_revision','label':'Drawing revision','unit':'','firm_required':True}],'allowed_components':[],'required_operations':[],'requires_document':False,'notes':'For verified one-off fabrication, not automated engineering design.'}
            db.add(ProductConfig(code='general_fabrication',label=data['label'],version=data['config_version'],definition=json.dumps(data)))
        if not db.scalar(select(ProductConfig).where(ProductConfig.code=='generic_service')):
            cfg={'product_type':'generic_service','label':'Generic repair and field service','config_version':'1.0.0',
                 'required_fields':[],'allowed_components':[],'required_operations':[],
                 'requires_document':False,'firm_release_enabled':True,
                 'material_matchers':[],'specification_sections':[],
                 'notes':'Service quotation: no drawing or structural BOM needed.'}
            db.add(ProductConfig(code='generic_service',label=cfg['label'],version='1.0.0',definition=json.dumps(cfg)))
        db.flush()
        book=json.loads((source/'sample_prices.json').read_text())
        for item in book['prices']:
            if db.scalar(select(Price).where(Price.sku==item['sku'])):continue
            p=Price(sku=item['sku'],description=item['description'],unit=item['price_uom'],rate=str(item['rate']),status=item['status'],source=item.get('source',''),vendor='',url=item.get('url',''),valid_until='',profile=json.dumps(book['profiles'].get(item['sku'],{})))
            db.add(p)
        db.commit()
        if demo:
            password='demo-pass-123'  # Sandbox account password. CHANGE for any real-use deployment.
            for role in ('admin','estimator','engineer','procurement','commercial'):
                username='demo' if role=='admin' else role
                if db.scalar(select(User).where(User.username==username)):continue
                db.add(User(username=username,display_name=role.title()+' Demo',password_hash=hashed_password(password),role=role))
            db.flush()
            for filename in ('sample_pallet.json','sample_conveyor.json'):
                example=json.loads((source/filename).read_text())
                ref=example['job_id']
                if db.scalar(select(Project).where(Project.ref==ref)):continue
                c=db.scalar(select(ProductConfig).where(ProductConfig.code==example['config_id']))
                p=Project(ref=ref,title='Fabricated pallet — sample' if example['config_id']=='fabricated_pallet' else '6 m conveyor — synthetic',customer='DEMO CUSTOMER (NO REAL DATA)',product_code=c.code,config_version=c.version,scope='Budgetary supply; engineering inputs to be verified.',exclusions='Taxes, site conditions and final engineering scope not yet confirmed.',overhead_pct='8',contingency_pct='5',margin_pct='20')
                db.add(p);db.flush()
                for field in json.loads(c.definition)['required_fields']:
                    item=example.get('fields',{}).get(field['key'],{})
                    val=item.get('value')
                    db.add(Requirement(project_id=p.id,field_key=field['key'],value='' if val is None else str(val).lower() if isinstance(val,bool) else str(val),unit=field.get('unit') or '',status='PENDING',evidence=str(item.get('provenance',''))))
                for b in example.get('components',[]):
                    db.add(BOMLine(project_id=p.id,sku=b['sku'],qty=str(b['qty']),unit=b['unit'],waste_pct=str(b['waste_pct']),status='ASSUMED',note=b.get('source','Synthetic test quantity')))
                for o in example.get('operations',[]):
                    db.add(Operation(project_id=p.id,code=o['code'],description=o['description'],hours=str(o['hours']),rate=str(o['rate_inr_hour']),status='ASSUMED'))
                record(db,None,'DEMO_PROJECT_CREATED',p.id)
            db.commit()
    from .commercial import upgrade_placeholder_seller_branding
    migrated=upgrade_placeholder_seller_branding()
    print('Database initialized.', 'Sandbox accounts demo, estimator, engineer, procurement, commercial with password demo-pass-123' if demo else 'No sandbox accounts were created.',f'Company defaults applied to {migrated} untouched placeholder quotation(s).')


def admin_from_env(interactive=False):
    username=os.getenv('ADMIN_USERNAME','').strip().lower()
    password=os.getenv('ADMIN_PASSWORD','')
    if interactive:
        from getpass import getpass
        username=input('Administrator username: ').strip().lower()
        password=getpass('Administrator password (12+ characters): ')
        confirm=getpass('Confirm password: ')
        if password!=confirm:raise SystemExit('Passwords do not match')
    if not username or not password or len(password)<12:
        raise SystemExit('Set ADMIN_USERNAME and ADMIN_PASSWORD (12+ characters) in the environment')
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username==username)):
            raise SystemExit('Admin username already exists; no password overwritten')
        db.add(User(username=username,display_name='Administrator',password_hash=hashed_password(password),role='admin'))
        db.commit()
    print('Administrator created')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--demo',action='store_true',help='Create sample accounts/projects with public known demo credentials; local development only')
    parser.add_argument('--admin-from-env',action='store_true',help='Create admin from ADMIN_USERNAME and ADMIN_PASSWORD')
    parser.add_argument('--admin-interactive',action='store_true',help='Prompt for an administrator password without echo')
    args=parser.parse_args()
    if args.demo and os.getenv('APP_ENV')=='production':
        raise SystemExit('Demo accounts cannot be created in production mode')
    if args.demo and (args.admin_from_env or args.admin_interactive):
        raise SystemExit('Choose either demo or production administrator initialization')
    load_defaults(args.demo)
    if args.admin_from_env:admin_from_env()
    if args.admin_interactive:admin_from_env(interactive=True)
