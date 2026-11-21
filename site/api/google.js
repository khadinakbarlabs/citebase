'use strict';
const crypto=require('node:crypto');
const {trustedPost,actorCredential,googleCallbackCredential}=require('./session');
const {projectStorage,apifyStorage}=require('./actor');
const {dispatch}=require('./_lib/google-mail');
const {scopes,scan,report}=require('./_lib/google-reporting');
const nonce=()=>crypto.randomBytes(32).toString('base64url');
const cookie='__Host-cbgoogle';
const tokenUrl='https://oauth2.googleapis.com/token';
function crypt(key,binding,value,open=false){
 const buf=open?Buffer.from(value,'base64url'):null;
 const iv=open?buf.subarray(0,12):crypto.randomBytes(12);
 const c=open?crypto.createDecipheriv('aes-256-gcm',key,iv):crypto.createCipheriv('aes-256-gcm',key,iv);
 c.setAAD(Buffer.from(binding));
 if(open){c.setAuthTag(buf.subarray(12,28));return JSON.parse(Buffer.concat([c.update(buf.subarray(28)),c.final()]));}
 const encrypted=Buffer.concat([c.update(JSON.stringify(value)),c.final()]);
 return Buffer.concat([iv,c.getAuthTag(),encrypted]).toString('base64url');
}
async function request(url,options){
 const res=await fetch(url,{...options,redirect:'error',cache:'no-store',signal:AbortSignal.timeout(20000)});
 if(!res.ok){await res.body?.cancel();throw Error('Upstream unavailable');}
 const chunks=[];let size=0;
 for await(const chunk of res.body){
  size+=chunk.byteLength;
  if(size>4*1024*1024)throw Error('Reply too large');
  chunks.push(chunk);
 }
 return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
module.exports=async function(req,res){
 res.setHeader('Cache-Control','private, no-store');
 res.setHeader('Referrer-Policy','no-referrer');
 const json=(status,data)=>{res.statusCode=status;res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));};
 try{
  const callback=req.method==='GET';
  if(!callback && (req.method!=='POST'||!trustedPost(req)))return json(403,{error:'Open your Citebase dashboard.'});
  const access=callback?googleCallbackCredential(req):actorCredential(req);
  if(!access)return json(401,{error:'Sign in again.'});
  const client_id=process.env.CITEBASE_GOOGLE_CLIENT_ID, client_secret=process.env.CITEBASE_GOOGLE_CLIENT_SECRET;
  const redirect_uri=process.env.CITEBASE_GOOGLE_REDIRECT_URI;
  const key=Buffer.from(process.env.CITEBASE_GOOGLE_TOKEN_KEY||'','base64');
  if(!callback && (Number(req.headers['content-length'])>262144||Buffer.byteLength(typeof req.body==='string'?req.body:JSON.stringify(req.body||{}))>262144))return json(413,{error:'Request too large.'});
  const body=callback?{}:typeof req.body==='string'?JSON.parse(req.body):req.body||{};
  const disabled=!client_id||!client_secret||key.length!==32||!redirect_uri;
  if(disabled)return json(body.action==='status'?200:503,{configured:false,error:'Google connections are unavailable on this deployment.'});
  const redirect=new URL(redirect_uri);
  if(redirect.protocol!=='https:'||!['/api/google','/api/google/'].includes(redirect.pathname)||redirect.href!==redirect.origin+redirect.pathname)throw Error('Configuration');
  const setFlow=(value,seconds)=>res.setHeader('Set-Cookie',cookie+'='+value+'; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age='+seconds);
  let flow;
  if(callback){
   const query=new URL(req.url,redirect.origin).searchParams;
   const raw=(req.headers.cookie||'').split(';').map(s=>s.trim()).find(s=>s.startsWith(cookie+'='))?.slice(cookie.length+1);
   setFlow('',0);
   flow=crypt(key,'oauth-flow',raw,true);
   if(flow.expires<Date.now()||flow.state!==query.get('state')||!query.get('code')||query.get('code').length>4096)return json(400,{error:'Google connection cancelled or expired.'});
  }
  const {project,service}=flow||body;
  if(!Object.hasOwn(scopes,service)||!(/^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/).test(project))return json(400,{error:'Choose a saved project and service.'});
  const api=(path,opts)=>apifyStorage(access,path,opts);
  const store=await projectStorage('dashboard_storage_review',{project},api);
  if(store.access!=='RESTRICTED')return json(409,{error:'Set this project store to Restricted in Apify before connecting Google.'});
  const base='key-value-stores/'+store.id+'/records/';
  const meta=await api(base+'p.'+project+'.meta');
  const site=meta?.brand?.site||meta?.brand?.domain;
  if(!site) return json(409,{error:'Save the project website first.'});
  const binding=store.id+'|'+project+'|'+service;
  const record=base+'oauth.google.'+project+'.'+service;
  const grant=params=>request(tokenUrl,{method:'POST',body:new URLSearchParams({client_id,client_secret,...params})});
  const save=value=>api(record,{method:'PUT',body:{ciphertext:crypt(key,binding,value)}});
  if(callback){
   if(binding!==flow.binding)return json(403,{error:'The signed-in project changed.'});
   const reply=await grant({grant_type:'authorization_code',code:new URL(req.url,redirect.origin).searchParams.get('code'),redirect_uri,code_verifier:flow.verifier});
   if(!reply.refresh_token||!reply.scope?.split(' ').includes(scopes[service]))throw Error('Missing grant');
   await save({refresh:reply.refresh_token,property:null});
   res.statusCode=303;res.setHeader('Location',redirect.origin+'/app/#/p/'+project+(service==='gmail'?'/outreach':'/setup'));return res.end();
  }
  if(body.action==='connect'){
   const state=nonce(),verifier=nonce();
   setFlow(crypt(key,'oauth-flow',{binding,service,project,state,verifier,expires:Date.now()+600000}),600);
   const params=new URLSearchParams({client_id,redirect_uri,response_type:'code',scope:scopes[service],state,code_challenge:crypto.createHash('sha256').update(verifier).digest('base64url'),code_challenge_method:'S256',access_type:'offline',prompt:'consent'});
   return json(200,{url:'https://accounts.google.com/o/oauth2/v2/auth?'+params});
  }
  const stored=await api(record);
  const conn=stored?.ciphertext?crypt(key,binding,stored.ciphertext,true):null;
  // Each encrypted credential write has a fresh IV. Its fingerprint also identifies pre-generation grants.
  const generation=conn?.refresh?crypto.createHash('sha256').update(stored.ciphertext).digest('hex'):null;
  const selectionRecord=record+'.property.'+generation;
  const selectedProperty=async()=>generation?(await api(selectionRecord))?.property||conn.property||null:null;
  const requireActive=async()=>{
   if(!generation||(await api(record))?.ciphertext!==stored.ciphertext){
    const error=new Error('Google connection changed. Review the current connection.');error.code='GRANT_CHANGED';throw error;
   }
  };
  const lastImportKey=selectionRecord+'.last-import';
  if(body.action==='status'){
   const property=await selectedProperty();
   const last=property && service!=='gmail'?await api(lastImportKey):null;
   return json(200,{configured:true,connected:!!conn?.refresh,property,last_import:last?.property===property?last:null});
  }
  if(body.action==='disconnect'){await save({});return json(200,{disconnected:true,googlePermissionRevoked:false});}
  if(!conn?.refresh)return json(409,{error:'Connect your Google account.'});
  const token=await grant({grant_type:'refresh_token',refresh_token:conn.refresh});
  if(!token.access_token)throw Error('Grant expired');
  const google=(url,payload)=>request(url,{method:payload?'POST':'GET',headers:{Authorization:'Bearer '+token.access_token,'Content-Type':'application/json'},body:payload?JSON.stringify(payload):undefined});
  if(service==='gmail'){
   if(body.action!=='send'||!token.scope?.split(' ').includes(scopes.gmail))return json(403,{error:'Reconnect Gmail and approve sending this saved draft.'});
   const credential='Bearer '+access;
   const work=async(operation,data)=>{
    await requireActive();
    const response=await request('https://khadinakbar--citebase.apify.actor/run',{method:'POST',headers:{'Content-Type':'application/json','X-Apify-Authorization':credential,'X-Citebase-Authorization':credential},body:JSON.stringify({tool:'project_work',arguments:{project,operation,data}})});
    if(response.ok!==true||!response.result?.result)throw Error('Draft unavailable');
    return response.result.result;
   };
   let outcome;
   try{
    outcome=await dispatch(body.draft,{work,send:async payload=>{await requireActive();return google('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',payload);},
     save:receipt=>api(base+'p.'+project+'.gmail-receipt.'+receipt.claimId,{method:'PUT',body:receipt})});
   }catch{return json(409,{error:'Could not confirm an unused handoff for this exact approved draft. Review project activity and your Sent folder.'});}
   return json(outcome.status==='outcome_unknown'?409:200,outcome);
  }
  const found=await scan(service,google,site),choices=found.choices;
  await requireActive();
  if(body.action==='properties')return json(200,{choices:choices.map(({id,label})=>({id,label})),
   website:found.website,checked:found.checked,unverified:found.unverified,others:found.others});
  const property=body.action==='select'?body.property:await selectedProperty();
  const selected=choices.find(p=>p.id===property);
  if(!selected)return json(409,{error:'Select an accessible property for this project.'});
  if(body.action==='select'){await api(selectionRecord,{method:'PUT',body:{property}});await requireActive();return json(200,{property});}
  if(body.action!=='sync')return json(400,{error:'Unknown action.'});
  const {observations,...summary}=await report(service,property,google,site,selected.streams);
  await requireActive();
  if(await selectedProperty()!==property)return json(409,{error:'Selected property changed. Review the connection.'});
  const source=service==='gsc'?'Google Search Console':'Google Analytics 4';
  const evidence={service,source,website:site,property,start_date:summary.startDate,end_date:summary.endDate,
   observed_at:new Date().toISOString().slice(0,10),count:summary.count};
  const snapshotKey=base+'p.'+project+'.google.'+service+'.'+summary.endDate;
  // A self-contained dated record also records a legitimate empty report for this exact site.
  await api(snapshotKey,{method:'PUT',body:{...evidence,rows:observations}});
  await api(lastImportKey,{method:'PUT',body:evidence});
  return json(200,{...summary,property,saved:summary.count>0});
 }catch(error){if(error?.code==='GRANT_CHANGED')return json(409,{error:error.message});return json(400,{error:'Could not confirm this Google operation. Check project history before retrying an import, or reconnect Google.'});}
};
