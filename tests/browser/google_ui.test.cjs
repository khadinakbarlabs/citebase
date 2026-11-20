const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {runInNewContext}=require('node:vm');
const {join}=require('node:path');

function element(tag,attributes,...children){
 return {tag,...attributes,children,
  replaceChildren(...nodes){this.children=nodes;},
  append(...nodes){this.children.push(...nodes);}};
}
const nodes=root=>[root,...(root.children||[]).flatMap(nodes)];
const texts=root=>nodes(root).map(n=>n.textContent??n.text).filter(Boolean);
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));

async function mount(service,replies){
 const calls=[];
 const fetch=async(_,opts)=>{
  const body=JSON.parse(opts.body);
  if(body.service!==service)return {ok:true,json:async()=>({configured:false,error:'off'})};
  calls.push(body);
  return {ok:true,json:async()=>replies[body.action]};
 };
 const CB={h:element,token:'t',refresh(){},demo:false};
 runInNewContext(readFileSync(join(__dirname,'../../site/app/google.js'),'utf8'),{window:{CB},fetch,location:{assign(){}}});
 const box=CB.googleUI.panel('featured-forge');
 await settle();
 const section=box.children.find(n=>n.children?.[0]?.text===(service==='gsc'?'Search Console':'Google Analytics 4'));
 const click=async text=>{await nodes(section).find(n=>n.tag==='button'&&n.text===text).onclick();await settle();};
 return {section,calls,click};
}

for(const [service,label,need] of [['gsc','Search Console','URL-prefix property for https://featuredforge.vercel.app/'],['ga4','Google Analytics 4','web stream for https://featuredforge.vercel.app/']])
test(label+' empty state names the website checked and the next step',async()=>{
 const {section,click}=await mount(service,{
  status:{configured:true,connected:true,property:null},
  properties:{choices:[],website:'featuredforge.vercel.app',checked:2,unverified:[],others:['sc-domain:featuredforge.com']}});
 await click('Choose property');
 const shown=texts(section).join('\n');
 assert.match(shown,new RegExp('No '+label+' property matches featuredforge\\.vercel\\.app yet\\.'));
 assert.match(shown,/Citebase checked 2 /);
 assert.ok(shown.includes(need),shown);
 assert.match(shown,/sc-domain:featuredforge\.com/);
 assert.doesNotMatch(shown,/No eligible properties found/);
 for(const text of ['Check again','Reconnect','Back'])assert.ok(nodes(section).some(n=>n.tag==='button'&&n.text===text),text);
});

test('an unverified Search Console match asks to finish verification',async()=>{
 const {section,click}=await mount('gsc',{status:{configured:true,connected:true},
  properties:{choices:[],website:'featuredforge.vercel.app',checked:1,unverified:['https://featuredforge.vercel.app/'],others:[]}});
 await click('Choose property');
 assert.ok(texts(section).some(t=>t.startsWith('https://featuredforge.vercel.app/ is added to this Google account but not verified')));
});

test('a matching property can be selected and then imported',async()=>{
 const replies={status:{configured:true,connected:true,property:null},
  properties:{choices:[{id:'sc-domain:featuredforge.com',label:'sc-domain:featuredforge.com'}],website:'featuredforge.com',checked:1,unverified:[],others:[]},
  select:{property:'sc-domain:featuredforge.com'}};
 const {section,calls,click}=await mount('gsc',replies);
 await click('Choose property');
 assert.ok(texts(section).includes('One property covers featuredforge.com. Choose the one to import from.'));
 assert.equal(nodes(section).find(n=>n.class==='google-help').children.length,0);
 const select=nodes(section).find(n=>n.tag==='select');select.value=select.children[0].value;
 replies.status={configured:true,connected:true,property:'sc-domain:featuredforge.com'};
 await click('Use selected property');
 assert.equal(calls.find(c=>c.action==='select').property,'sc-domain:featuredforge.com');
 replies.sync={measure:'Up to 1,000 Google Search queries by clicks',startDate:'2026-10-21',endDate:'2026-11-17',count:12,saved:true};
 await click('Import 28 days');
 assert.ok(texts(section).includes('Up to 1,000 Google Search queries by clicks · 2026-10-21 to 2026-11-17 · 12 rows imported.'));
});
