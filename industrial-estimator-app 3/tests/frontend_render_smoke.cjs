// Render all UI pages in a minimal DOM harness; no external Node packages.
// This is structural smoke coverage, NOT a substitute for a real-browser visual test.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert');
const root={innerHTML:''};
const code=fs.readFileSync(path.join(__dirname,'..','frontend','assets','app.js'),'utf8');
const context={Intl,Number,Date,JSON,console,Math,String,Boolean,encodeURIComponent,FormData:class{},setTimeout:()=>{},sessionStorage:{getItem:()=>null,removeItem:()=>{},setItem:()=>{}},document:{getElementById:()=>root,querySelectorAll:()=>[],addEventListener:()=>{},body:{appendChild:()=>{}}},fetch:async()=>({ok:true,json:async()=>({demo_mode:false})}),window:{scrollTo:()=>{}},URL:{revokeObjectURL:()=>{},createObjectURL:()=>''},confirm:()=>false};
vm.createContext(context);
vm.runInContext(code+'\n;globalThis.BRIDGE={APP,render,templateEditorModal,quoteTemplateModal};',context,{timeout:3000});
const {APP,render}=context.BRIDGE;
function page(view,token){APP.view=view;render();assert(root.innerHTML.includes(token),`${view} missing ${token}`);console.log('Rendered',view,root.innerHTML.length,'characters')}
APP.user={username:'demo',display_name:'Demo',role:'admin'};
APP.configs=[{product_type:'fabricated_pallet',label:'Steel pallet',config_version:'1.0.0',required_fields:[{key:'length_mm',label:'Length',unit:'mm'}],allowed_components:['SHS-40-40-3'],required_operations:['weld'],notes:'Example'}];
APP.prices=[{sku:'SHS-40-40-3',description:'MS Square Tube',unit:'kg',rate:'65',status:'PUBLIC_BENCHMARK',valid_until:'',profile:{}}];
APP.projects=[{id:1,ref:'Q-001',customer:'Demo',title:'Training pallet',product_code:'fabricated_pallet',status:'DRAFT',estimate:'1000',firm_ready:false,quantity:1}];
APP.detail={project:{...APP.projects[0],config_version:'1.0.0',margin_pct:'20',overhead_pct:'8',contingency_pct:'5',scope:'Sample scope',exclusions:'Tax excluded',delivery:'TBC',payment_terms:'TBC',validity_days:15},config:APP.configs[0],requirements:[{id:1,key:'length_mm',value:'1200',unit:'mm',status:'PENDING',evidence:'Training schematic'}],bom:[{id:1,sku:'SHS-40-40-3',qty:'10',unit:'m',waste_pct:'8',status:'ASSUMED',note:'Demo'}],operations:[{id:1,code:'weld',description:'Welding',hours:'2',rate:'400',status:'ASSUMED'}],documents:[],estimate:{material_cost:'500',operation_cost:'800',overhead:'100',contingency:'50',total_cost:'1450',unit_price:'1812.50',order_value:'1812.50',lines:[{id:1,rate:'65',rate_unit:'kg',line_total:'500'}],warnings:['Assumed quantity']},gates:{drawing_complete:false,requirements_verified:false,quantities_approved:false,rates_verified:false,engineering_approved:false,pricing_approved:false,commercial_approved:false,product_release_enabled:true,firm_ready:false},issues:[]};
page('dashboard','Good to see you again');
page('projects','Quotation register');
for(const [tab,token] of [['overview','Quotation progress'],['documents','Design documents & persistent review log'],['requirements','Technical requirements'],['bom','Materials & assemblies'],['operations','Fabrication & labour'],['review','Cost breakdown'],['history','Issued quotation snapshots']]){
 APP.view='project';APP.tab=tab;render();assert(root.innerHTML.includes(token),`tab ${tab} missing ${token}`);console.log('Rendered tab',tab,root.innerHTML.length,'characters');
}
page('prices','Item catalogue');
page('configs','Product library');
APP.users=[{id:1,username:'demo',display_name:'Demo',role:'admin',active:true}];page('users','Accounts');
console.log('Frontend structural render: 12 checks passed');

// v0.3 customer-facing commercial quotation and confidence-field screens.
APP.detail.commercial={
 profile:{workflow:'service_repair',template:'short_service',external_reference:'TEST-41',
  terms:{scope:'Motor repair','payment':'On completion','delivery':'After inspection',certifications:[]},
  tax_config:{status:'APPROVED',mode:'EXCLUSIVE',components:[{name:'CGST',rate:'9'},{name:'SGST',rate:'9'}],basis_note:'Reviewed'},
  technical:[],branding:{name:'Synthetic Sample Engineering'}},
 pricing:{lines:[{id:1,description:'Motor rewind',mode:'FIXED',price:'39500',qty:'1',unit:'each',line_total:'39500.00',ordinal:10,tax_applicable:true,tax_code:'',parent_id:null,notes:''}],
  subtotal_known:'39500.00',tax_components:[{name:'CGST',rate:'9',amount:'3555.00'}],known_total_including_tax:'43055.00',grand_total_definitive:true,unpriced_lines:[],additional_at_actual:[]},
 gates:{firm_ready:false,workflow:'service_repair',technical_verified:true,price_lines_complete:true,tax_approved:true,terms_complete:true,unresolved_conflicts:[],engineering_approved:true,pricing_approved:false,commercial_approved:false,missing:[]},conflicts:[]};
for(const [tab,token] of [['overview','Customer quotation progress'],['selling','Customer price schedule'],['review','Current customer quotation']]){
 APP.view='project';APP.tab=tab;render();assert(root.innerHTML.includes(token),`commercial ${tab} missing ${token}`);
 console.log('Rendered commercial tab',tab,root.innerHTML.length,'characters');
}
APP.view='project';APP.tab='selling';render();assert(root.innerHTML.includes('What does Add customer charge do?'),'Selling line explanation is missing');
APP.detail.documents=[{id:7,original_name:'synthetic.pdf',document_type:'PDF',pages:1,checksum:'e'.repeat(64),uploaded_at:'2026-01-01',candidates:[{kind:'field',key:'length_mm',value:'1200',evidence:'Length: 1200 mm',page:1,confidence_score:96,confidence_basis:'LABEL_THEN_VALUE_EXPLICIT_UNIT',source_location:'PDF page 1'}]}];
APP.view='project';APP.tab='documents';render();assert(root.innerHTML.includes('96/99'),'Missing source confidence label');
console.log('Rendered candidate confidence source review');
APP.detail.documents[0].candidates[0].review={state:'VERIFIED',label:'Requirement verified',target_kind:'REQUIREMENT',target_id:1,value:'1200 mm',record_status:'APPROVED'};
APP.view='project';APP.tab='documents';render();assert(root.innerHTML.includes('Saved value:')&&root.innerHTML.includes('Requirement verified'),'Persistent candidate review state missing from Documents');
console.log('Saved extraction state displayed on Documents tab');

// v0.5 visible quotation format gallery + editor + project selection.
APP.templates=[{code:'multi_annexure',name:'Equipment - Technical / commercial',workflow:'equipment_supply',version:1,is_builtin:true,is_default:true,layout:{title:'TECHNO-COMMERCIAL OFFER',primary_color:'#17344C',accent_color:'#087E75',tagline:'',intro:'',closing:'',footer:'',sections:[{key:'technical',title:'Technical',enabled:true},{key:'pricing',title:'Price Schedule',enabled:true},{key:'terms',title:'Terms',enabled:true}]}},{code:'short_service',name:'Service - Repair',workflow:'service_repair',version:1,is_builtin:true,is_default:true,layout:{title:'REPAIR OFFER',primary_color:'#17344C',accent_color:'#087E75',tagline:'',intro:'',closing:'',footer:'',sections:[{key:'pricing',title:'Work and charges',enabled:true},{key:'terms',title:'Terms',enabled:true}]}}];
APP.view='templates';render();assert(root.innerHTML.includes('Import JSON layout')&&root.innerHTML.includes('Preview sample PDF')&&root.innerHTML.includes('Upload quotation template (.docx)'),'Visible template gallery missing controls');
context.BRIDGE.templateEditorModal('multi_annexure',true);
assert(root.innerHTML.includes('Duplicate template')&&root.innerHTML.includes('section_lines'),'Template duplication editor missing');
APP.detail.commercial.profile.template='short_service';
context.BRIDGE.quoteTemplateModal();
assert(root.innerHTML.includes('Choose quotation layout'),'Template assignment editor missing');
console.log('v0.6 template gallery UI structural checks passed');

APP.templates.push({code:'pallet_word',name:'Pallet Word',workflow:'equipment_supply',source_type:'docx',placeholders:['quote.number','buyer.name'],version:1,is_builtin:false,is_default:false,layout:{title:'PALLET',format_style:'classic_equipment'}});APP.view='templates';render();assert(root.innerHTML.includes('Download Word')&&root.innerHTML.includes('Replace Word'),'Word template controls missing');console.log('Word template gallery controls passed');

// Semantic separation: reusable Word formats exist only in Quote formats UI.
APP.view='project';APP.tab='documents';render();
assert(root.innerHTML.includes('Upload design / specification'));
assert(root.innerHTML.includes('Reusable quotation layouts belong in'));
assert(!root.innerHTML.includes('Upload quotation template (.docx)'));
APP.view='templates';render();
assert(root.innerHTML.includes('Upload quotation template (.docx)'));
assert(root.innerHTML.includes('Download pallet example'));
console.log('Independent design-document and quotation-template controls passed');

// v0.7: company setup and editable commercial UOM (no fixed dropdown).
APP.company={branding:{name:'DEMO TEST ENGINEERING',address:'Test office',gstin:'TESTGST',contact:'Test phone',signature_title:'Owner'},quote_prefix:'TEST',units:['Nos.','Set','Pair','m2','sq ft','kg']};
page('company','DEMO TEST ENGINEERING');
APP.view='company';context.BRIDGE.render();
assert(root.innerHTML.includes('Quotation reference prefix'));
console.log('v0.7 company configuration screen passed');
