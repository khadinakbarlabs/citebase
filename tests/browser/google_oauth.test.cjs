const {test}=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const actor=require('../../site/api/actor');
const session=require('../../site/api/session');
let store='store1';
const records=new Map();
actor.projectStorage=async()=>({id:store,access:'RESTRICTED'});
actor.apifyStorage=async(_,path,opt)=>{
 if(path.endsWith('.meta'))return {brand:{domain:'example.com'}};
 if(opt){records.set(path,opt.body);return null;}
 return records.get(path);
};
session.trustedPost=req=>req.headers.origin==='https://citebase.test';
session.actorCredential=()=> 'apify-fixture';
session.googleCallbackCredential=()=> 'apify-fixture';
const handler=require('../../site/api/google');
async function run(method,url,body,headers={}){
 const res={headers:{},setHeader(k,v){this.headers[k]=v;},end(v){this.data=v?JSON.parse(v):null;}};
 await handler({method,url,body,headers:{origin:'https://citebase.test',...headers}},res);
 return res;
}
test('binds one OAuth flow and its property to the owner’s restricted project',async t=>{
 Object.assign(process.env,{CITEBASE_GOOGLE_CLIENT_ID:'test',CITEBASE_GOOGLE_CLIENT_SECRET:'secret',CITEBASE_GOOGLE_TOKEN_KEY:crypto.randomBytes(32).toString('base64'),CITEBASE_GOOGLE_REDIRECT_URI:'https://citebase.test/api/google/'});
 const calls=[];
 t.mock.method(global,'fetch',async(url,opts)=>{
  calls.push(String(url));
  if(String(url).includes('oauth2.googleapis.com/token'))return Response.json({refresh_token:'fixture-refresh',access_token:'fixture-google',scope:'https://www.googleapis.com/auth/webmasters.readonly'});
  if(String(url).endsWith('/sites'))return Response.json({siteEntry:[{siteUrl:'sc-domain:example.com',permissionLevel:'siteOwner'}]});
  if(String(url).endsWith('/query'))return Response.json({rows:[{keys:['test'],clicks:3,impressions:5,position:1,ctr:.6}]});
  assert.equal(opts.headers['X-Citebase-Authorization'],'Bearer apify-fixture');
  assert.equal(JSON.parse(opts.body).arguments.project,'site-one');
  assert.doesNotMatch(opts.body,/fixture-refresh|fixture-google/);
  return Response.json({ok:true});
 });
 const base={project:'site-one',service:'gsc'};
 const post=(action,extra,headers)=>run('POST','/api/google/',{...base,action,...extra},headers);
 assert.equal((await post('connect',{}, {origin:'https://foreign.test'})).statusCode,403);
 const flow=await post('connect'), state=new URL(flow.data.url).searchParams.get('state');
 const cookie=flow.headers['Set-Cookie'].split(';')[0];
 const callback=s=>run('GET','/api/google/?code=test&state='+s,null,{cookie});
 assert.equal((await callback('invalid')).statusCode,400);
 store='wrong-store';assert.equal((await callback(state)).statusCode,403);
 assert.equal(calls.length,0);
 store='store1';assert.equal((await callback(state)).statusCode,303);
 assert.doesNotMatch(JSON.stringify([...records]),/fixture-refresh/);
 const listed=(await post('properties')).data;
 assert.deepEqual(listed,{choices:[{id:'sc-domain:example.com',label:'sc-domain:example.com'}],website:'example.com',checked:1,unverified:[],others:[]});
 assert.equal((await post('select',{property:'sc-domain:unrelated.com'})).statusCode,409);
 assert.equal((await post('select',{property:'sc-domain:example.com'})).statusCode,200);
 const synced=await post('sync');
 assert.equal(synced.data.saved,true);
 const snapshot=records.get('key-value-stores/store1/records/p.site-one.google.gsc.'+synced.data.endDate);
 assert.equal(snapshot.property,'sc-domain:example.com');
 assert.equal(snapshot.website,'example.com');
 assert.equal(snapshot.start_date,synced.data.startDate);
 assert.deepEqual(snapshot.rows,[{term:'test',clicks:3,impressions:5,position:1}]);
 assert.equal(calls.some(url=>url.includes('apify.actor/run')),false,'Native reporting has one website-bound source of truth');
 assert.equal((await post('status')).data.last_import.end_date,synced.data.endDate);
 assert.equal((await post('disconnect')).data.disconnected,true);
 assert.equal((await post('status')).data.connected,false);
});
test('Gmail needs its own grant and exact approval, sends once and stores its receipt',async t=>{
 const scope='https://www.googleapis.com/auth/gmail.send';
 let granted=scope,claimed=false,sends=0,operations=0;
 const draft={prospectId:'fixture',version:'c'.repeat(32),to:'editor@example.test',subject:'Fixture',body:'Test only',confirm:true};
 const base={project:'site-one',service:'gmail'};
 const post=(action,extra)=>run('POST','/api/google/',{...base,action,...extra});
 t.mock.method(global,'fetch',async(url,opts)=>{
  if(url.includes('oauth2.googleapis.com/token'))return Response.json({refresh_token:'refresh',access_token:'token',scope:granted});
  if(url.includes('apify.actor/run')){
   operations++;
   const {operation}=JSON.parse(opts.body).arguments;
   if(claimed)return Response.json({ok:false});
   if(operation==='outreach_claim')claimed=true;
   return Response.json({ok:true,result:{result:{...draft,claimId:'d'.repeat(32)}}});
  }
  assert.equal(url,'https://gmail.googleapis.com/gmail/v1/users/me/messages/send');
  assert.equal(opts.redirect,'error');sends++;return Response.json({id:'abcd'});
 });
 assert.equal((await post('send',{draft})).statusCode,409);
 const flow=await post('connect');
 const params=new URL(flow.data.url).searchParams;
 assert.equal(params.get('scope'),scope);
 await run('GET','/api/google/?code=test&state='+params.get('state'),null,{cookie:flow.headers['Set-Cookie'].split(';')[0]});
 granted='https://www.googleapis.com/auth/analytics.readonly';
 assert.equal((await post('send',{draft})).statusCode,403);assert.equal(operations,0);
 granted=scope;
 assert.equal((await post('send',{draft:{...draft,body:'Edited'}})).statusCode,409);
 const accepted=await post('send',{draft});assert.equal(accepted.data.messageId,'abcd');
 assert.equal(accepted.data.receiptSaved,true);
 assert.equal((await post('send',{draft})).statusCode,409);assert.equal(sends,1);
});
for(const reconnect of [false,true])test('delayed selection cannot restore a legacy grant after '+(reconnect?'reconnect':'disconnect'),async t=>{
 const base={project:reconnect?'second-site':'first-site',service:'gsc'};
 const post=(action,extra)=>run('POST','/api/google/',{...base,action,...extra});
 const binding=store+'|'+base.project+'|gsc',iv=crypto.randomBytes(12);
 const cipher=crypto.createCipheriv('aes-256-gcm',Buffer.from(process.env.CITEBASE_GOOGLE_TOKEN_KEY,'base64'),iv);
 cipher.setAAD(Buffer.from(binding));
 const bytes=Buffer.concat([cipher.update(JSON.stringify({refresh:'legacy',property:'sc-domain:example.com'})),cipher.final()]);
 const record='key-value-stores/'+store+'/records/oauth.google.'+base.project+'.gsc';
 records.set(record,{ciphertext:Buffer.concat([iv,cipher.getAuthTag(),bytes]).toString('base64url')});
 const reached=Promise.withResolvers(),resume=Promise.withResolvers();
 t.mock.method(global,'fetch',async url=>{
  if(url.endsWith('/sites')){
   reached.resolve();await resume.promise;
   return Response.json({siteEntry:[{siteUrl:'sc-domain:example.com',permissionLevel:'siteOwner'}]});
  }
  return Response.json({access_token:'access',refresh_token:'new',scope:'https://www.googleapis.com/auth/webmasters.readonly'});
 });
 assert.equal((await post('status')).data.property,'sc-domain:example.com');
 const slow=post('select',{property:'sc-domain:example.com'});
 await reached.promise;await post('disconnect');
 if(reconnect){
  const flow=await post('connect');
  const state=new URL(flow.data.url).searchParams.get('state');
  assert.equal((await run('GET','/api/google/?code=fixture&state='+state,null,{cookie:flow.headers['Set-Cookie'].split(';')[0]})).statusCode,303);
 }
 resume.resolve();
 assert.equal((await slow).statusCode,409);
 const result=await post('status');
 assert.equal(result.data.connected,reconnect);assert.equal(result.data.property,null);
});

test('a Google sign-in started on the Connections page returns there; others keep their old page',async t=>{
 Object.assign(process.env,{CITEBASE_GOOGLE_CLIENT_ID:'test',CITEBASE_GOOGLE_CLIENT_SECRET:'secret',CITEBASE_GOOGLE_TOKEN_KEY:crypto.randomBytes(32).toString('base64'),CITEBASE_GOOGLE_REDIRECT_URI:'https://citebase.test/api/google/'});
 store='store1';
 t.mock.method(global,'fetch',async()=>Response.json({refresh_token:'r',access_token:'a',scope:'https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/gmail.send'}));
 const back=async(service,extra)=>{
  const flow=await run('POST','/api/google/',{project:'site-one',service,action:'connect',...extra});
  const state=new URL(flow.data.url).searchParams.get('state');
  const done=await run('GET','/api/google/?code=x&state='+state,null,{cookie:flow.headers['Set-Cookie'].split(';')[0]});
  assert.equal(done.statusCode,303);
  return done.headers.Location;
 };
 assert.equal(await back('gsc',{return_to:'connections'}),'https://citebase.test/app/#/p/site-one/connections');
 assert.equal(await back('gsc',{return_to:'search'}),'https://citebase.test/app/#/p/site-one/search');
 assert.equal(await back('ga4',{}),'https://citebase.test/app/#/p/site-one/setup');
 assert.equal(await back('gsc',{return_to:'https://evil.test/'}),'https://citebase.test/app/#/p/site-one/setup');
 assert.equal(await back('gmail',{return_to:'connections'}),'https://citebase.test/app/#/p/site-one/connections');
 assert.equal(await back('gmail',{}),'https://citebase.test/app/#/p/site-one/outreach');
});
