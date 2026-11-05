const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert');
const code=fs.readFileSync(path.join(__dirname,'..','frontend','assets','app.js'),'utf8');
const root={innerHTML:''};
const context={Intl,Number,Date,JSON,console,Math,String,Boolean,encodeURIComponent,FormData:class{},setTimeout:()=>{},sessionStorage:{getItem:()=>null,removeItem:()=>{},setItem:()=>{}},document:{getElementById:()=>root,querySelectorAll:()=>[],addEventListener:()=>{},body:{appendChild:()=>{}}},fetch:async()=>({ok:true,json:async()=>({demo_mode:false})}),window:{scrollTo:()=>{}},URL:{revokeObjectURL:()=>{},createObjectURL:()=>''},confirm:()=>false};
vm.createContext(context);
vm.runInContext(code+'\n;globalThis.BRIDGE={APP,newProject};',context,{timeout:3000});
const {APP,newProject}=context.BRIDGE;
APP.configs=[{product_type:'fabricated_pallet',label:'Fabricated steel pallet/cage'},
{product_type:'eot_crane',label:'EOT crane'},
{product_type:'belt_conveyor',label:'Belt conveyor'},
{product_type:'generic_service',label:'Repair service'}];
for(const family of APP.configs){
  newProject(family.product_type);
  const body=APP.modal.body;
  assert(body.includes('Cost-plus estimation (all products)'),`${family.product_type} missing unified workflow note`);
  assert(body.includes('name="product_code"'),`${family.product_type} missing family selector`);
  assert(body.includes('value="'+family.product_type+'" selected'),`${family.product_type} wrong initial selection`);
  assert(!body.includes('name="quote_workflow"'),`${family.product_type} exposes deprecated workflow choice`);
  assert(!body.includes('data-commercial-details'),`${family.product_type} exposes unused contact input`);
  assert(!body.includes('Add price line'),`${family.product_type} exposes selling-price workflow`);
}
// Submission must not send a workflow choice or condition on pallet type.
const submit=code.slice(code.indexOf("if(kind==='new-project')"),code.indexOf("if(kind==='settings')"));
assert(!submit.includes('quote_workflow'));
assert(!submit.includes('fabricated_pallet'));
console.log('All four product family create forms use the same cost-plus workflow');
