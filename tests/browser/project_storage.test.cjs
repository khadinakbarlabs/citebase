'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {projectStorage} = require('../../site/api/actor');
const id = 'Abcd1234abcdefghX';
const owner = 'Ownr1234abcdefghX';
const project = 'qa-first-project';
function fixture({foreign = false, duplicate = false, access = 'FOLLOW_USER_SETTING'} = {}) {
  const writes = [];
  const classic = 'citebase-projects', fallback = 'citebase-projects-v2-me1rsyfkhb634kvyr';
  const api = async (path, options) => {
    if (path === 'users/me') return {id:owner,username:'fixture'};
    const base = {id, userId:foreign ? 'OtherOwner' : owner, generalAccess:access, name:classic};
    if (path === 'key-value-stores/fixture~' + classic) return base;
    if (path === 'key-value-stores/fixture~' + fallback) return duplicate ? {...base,id:'Other1234abcdefgh',name:fallback} : null;
    if (path.endsWith('/records/p.' + project + '.meta')) return {project};
    if (path === 'key-value-stores/'+id) {
      if (options?.method === 'PUT') {writes.push(options.body); access='RESTRICTED';}
      return {...base,generalAccess:access};
    }
    throw Error('Unexpected provider route');
  };
  return {api,writes};
}
test('review identifies the one owned Citebase store with this project and performs no write', async () => {
  const {api,writes}=fixture();
  const row=await projectStorage('dashboard_storage_review',{project},api);
  assert.deepEqual(row,{id,name:'citebase-projects',access:'FOLLOW_USER_SETTING'});
  assert.deepEqual(writes,[]);
});
test('tightening inherited access requires the reviewed store and express confirmation and is idempotent', async () => {
  const {api,writes}=fixture();
  const args={project,store_id:id,confirmed:true};
  for (const bad of [{...args,confirmed:false},{...args,store_id:'Wrong1234abcdefgh'},{...args,access:'PUBLIC'}]) {
    await assert.rejects(projectStorage('dashboard_restrict_storage',bad,api));
  }
  assert.equal(writes.length,0);
  assert.equal((await projectStorage('dashboard_restrict_storage',args,api)).access,'RESTRICTED');
  assert.equal((await projectStorage('dashboard_restrict_storage',args,api)).access,'RESTRICTED');
  assert.deepEqual(writes,[{generalAccess:'RESTRICTED'}]);
});
test('foreign, deliberately shared or ambiguous stores cannot be silently changed',async()=>{
  for(const opt of [{foreign:true},{duplicate:true},{access:'ANYONE_WITH_ID_CAN_READ'}]){
    const {api,writes}=fixture(opt);
    await assert.rejects(projectStorage('dashboard_restrict_storage',{project,store_id:id,confirmed:true},api));
    assert.equal(writes.length,0);
  }
});

test('prepaid balances stay in the signed-in owner’s Restricted store and never auto-authorize spending', async()=>{
  const {accountBalance}=require('../../site/api/_lib/balance');
  let existing=null;
  const records=new Map(), calls=[];
  const name='citebase-billing-balances';
  async function api(path,opts={}) {
    calls.push([path,opts.method || 'GET']);
    if(path==='users/me')return {id:owner,username:'fixture'};
    if(path==='key-value-stores/fixture~'+name)return existing;
    if(path==='key-value-stores' && opts.method==='POST')return {id,userId:owner};
    if(path==='key-value-stores/'+id && opts.method==='PUT') {
      assert.deepEqual(opts.body,{name,generalAccess:'RESTRICTED'});
      return existing={id,userId:owner,...opts.body};
    }
    if(path==='key-value-stores/'+id)return existing;
    if(path.startsWith('key-value-stores/'+id+'/keys?'))return {items:[...records.keys()].sort().slice(0,1).map(key=>({key})),isTruncated:false};
    const k=path.split('/records/')[1];
    if(k && opts.method==='PUT'){records.set(k,opts.body);return null;}
    if(k)return records.get(k);
    throw Error(path);
  }
  assert.deepEqual(await accountBalance('dashboard_balance_read',{},api),{balance:null});
  assert(calls.every(c=>c[1]==='GET'));
  for (const invalid of [-1,Infinity,'10',0.123]) await assert.rejects(accountBalance('dashboard_balance_save',
    {amount_usd:invalid,period_end:'2027-03-27',confirmed:true},api));
  const end=new Date(Date.now()+86400000*30).toISOString().slice(0,10);
  const input={amount_usd:12.34,period_end:end,confirmed:true};
  const result=await accountBalance('dashboard_balance_save',input,api);
  assert.equal(result.balance.amount_usd,12.34);
  assert.equal(result.balance.period_end,end);
  assert.equal(result.balance.source,'manual_apify_billing');
  assert.deepEqual(await accountBalance('dashboard_balance_read',{},api),result);
  await new Promise(resolve=>setTimeout(resolve,2));
  await accountBalance('dashboard_balance_save',{...input,amount_usd:0},api);
  assert.equal((await accountBalance('dashboard_balance_read',{},api)).balance.amount_usd,0);
  existing={...existing,generalAccess:'FOLLOW_USER_SETTING'};
  await assert.rejects(accountBalance('dashboard_balance_read',{},api));
  existing={...existing,generalAccess:'RESTRICTED',userId:'another'};
  await assert.rejects(accountBalance('dashboard_balance_save',input,api));
});
