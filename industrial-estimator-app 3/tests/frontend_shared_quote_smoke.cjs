// Structural regression: all new projects show cost-plus AND quotation exports.
// This is NOT a full browser interaction/visual test.
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert');
const root={innerHTML:''};
const code=fs.readFileSync(path.join(__dirname,'..','frontend','assets','app.js'),'utf8');
const context={Intl,Number,Date,JSON,console,Math,String,Boolean,encodeURIComponent,
 FormData:class{},setTimeout:()=>{},
 sessionStorage:{getItem:()=>null,removeItem:()=>{},setItem:()=>{}},
 document:{getElementById:()=>root,querySelectorAll:()=>[],addEventListener:()=>{},body:{appendChild:()=>{}}},
 fetch:async()=>({ok:true,json:async()=>({demo_mode:false})}),
 window:{scrollTo:()=>{}},URL:{revokeObjectURL:()=>{},createObjectURL:()=>''},confirm:()=>false};
vm.createContext(context);
vm.runInContext(code+'\n;globalThis.BRIDGE={APP,render,quoteTemplateModal,quoteTermsModal};',context,{timeout:4000});
const {APP,render,quoteTemplateModal,quoteTermsModal}=context.BRIDGE;
APP.user={username:'demo',display_name:'Demo',role:'admin'};
APP.configs=[{product_type:'eot_crane',label:'EOT crane',config_version:'1.0',required_fields:[],allowed_components:[],required_operations:[]}];
APP.templates=[{code:'quote73_equipment',name:'Quote 73',workflow:'equipment_supply',version:1},{code:'short_service',name:'Service',workflow:'service_repair',version:1}];
APP.projects=[{id:1,title:'Crane Estimate',customer:'Fixture Customer',product_code:'eot_crane',ref:'Q-TEST-001',status:'DRAFT'}];
APP.detail={project:{...APP.projects[0],quantity:2,margin_pct:'20',overhead_pct:'8',contingency_pct:'5'},
 config:APP.configs[0],requirements:[],bom:[],operations:[],documents:[],issues:[],
 estimate:{material_cost:'100.00',operation_cost:'80.00',overhead:'15.00',contingency:'10.00',total_cost:'205.00',unit_price:'256.25',order_value:'512.50',warnings:[]},
 gates:{drawing_complete:false,requirements_verified:false,quantities_approved:false,rates_verified:false,engineering_approved:false,pricing_approved:false,commercial_approved:false,product_release_enabled:true,firm_ready:false},
 commercial:null,
 quotation:{profile:{template:'quote73_equipment',external_reference:'',technical:[],
    terms:{customer_attention:'Ms. Named Recipient',customer_address:'Plant 1',product_unit:'Pair',quotation_line_description:'Crane offer',payment:'30 days',delivery:'FOB factory',certifications:[]},
    tax_config:{mode:'EXCLUSIVE',status:'PENDING',components:[]},branding:{name:'TEST ENGINEERING',address:'Test office',works_address:'Test works',gstin:'DUMMY',contact:'test',signature_title:'Authorized signatory'}},
    pricing:{subtotal_known:'512.50',known_total_including_tax:'512.50',tax_status:'PENDING',tax_components:[]},
    gates:{firm_ready:false,cost_plus_approved:false,tax_approved:false,customer_contact_confirmed:true,terms_complete:true,template_valid:true,missing:['Cost-plus release approvals']}}};
APP.view='project';APP.tab='quotation';render();
const html=root.innerHTML;
for(const token of ['BOM & materials','Cost & approvals','Quotation','Choose format','Download editable Word','Quotation details','Crane offer','2 Pair','Edit contact, terms & taxes']){
 assert(html.includes(token),'Missing shared feature: '+token);
}
assert(!html.includes('Add customer charge'),'Separate selling-price workflow returned for new project');
APP.tab='review';render();assert(root.innerHTML.includes('Edit pricing rules')&&root.innerHTML.includes('Cost breakdown'));
quoteTemplateModal();assert(root.innerHTML.includes('Service')&&root.innerHTML.includes('Quote 73'),'All presentation format categories should be offered');
quoteTermsModal();assert(root.innerHTML.includes('Product')||root.innerHTML.includes('Customer contact'));
assert(root.innerHTML.includes('product_unit')&&root.innerHTML.includes('quotation_line_description'));
console.log('Single cost-plus UI and shared quotation feature smoke: PASS');
