'use strict';
const {randomUUID} = require('node:crypto');
const STORE = 'citebase-billing-balances';
const PREFIX = 'balance-v1-';
const MAX_CLOCK = 9999999999999;

function checkedInput(args, now) {
  const amount = args.amount_usd, end = args.period_end;
  const observed = args.observed_at ? Date.parse(args.observed_at) : now;
  const endTime = typeof end === 'string' && /^\d{4}-\d\d-\d\d$/.test(end) ? Date.parse(end+'T23:59:59.999Z') : NaN;
  const cents = Math.round(amount * 100);
  if (args.confirmed !== true || Object.keys(args).some(k=>!['amount_usd','period_end','observed_at','confirmed'].includes(k)) ||
      typeof amount !== 'number' || !Number.isSafeInteger(cents) || amount < 0 || amount > 1e9 || cents / 100 !== amount ||
      !Number.isFinite(endTime) || new Date(endTime).toISOString().slice(0,10) !== end || endTime < now ||
      endTime > now + 732 * 86400000 || !Number.isFinite(observed) || observed > now + 60000 || observed < now - 30 * 86400000) {
    throw Error('Enter a USD amount, the current billing period end date, and when you checked it in Apify Billing.');
  }
  return {amount_usd:amount, period_end:end, observed_at:new Date(observed).toISOString(),
    recorded_at:new Date(now).toISOString(), source:'manual_apify_billing'};
}
function owned(store, owner) {
  return store && store.userId===owner && typeof store.id==='string' && /^[a-zA-Z0-9]{5,80}$/.test(store.id);
}
function safeBalance(row) {
  if (!row || row.source!=='manual_apify_billing' || !Number.isFinite(row.amount_usd) || row.amount_usd<0 ||
      typeof row.period_end!=='string' || !/^\d{4}-\d\d-\d\d$/.test(row.period_end) ||
      !Number.isFinite(Date.parse(row.observed_at)) || !Number.isFinite(Date.parse(row.recorded_at))) throw Error('The saved balance could not be verified.');
  return {amount_usd:row.amount_usd,period_end:row.period_end,observed_at:row.observed_at,recorded_at:row.recorded_at,source:row.source};
}

async function accountBalance(tool,args,api) {
  const write = tool==='dashboard_balance_save';
  if (!args || (!write && (tool!=='dashboard_balance_read' || Object.keys(args).length))) throw Error('Invalid balance request.');
  const now = Date.now(), value = write ? checkedInput(args,now) : null;
  const me = await api('users/me');
  if (!me?.id || !/^[a-zA-Z0-9_.-]+$/.test(me.username || '')) throw Error('Could not verify the billing account.');
  const named = 'key-value-stores/'+me.username+'~'+STORE;
  let store = await api(named);
  if (!store && !write) return {balance:null};
  if (!store) {
    // Restrict a fresh container before its first private record. Preserve the owner's choices on all existing stores.
    const fresh=await api('key-value-stores',{method:'POST'});
    if (!owned(fresh,me.id) || fresh.name) throw Error('Could not prepare private billing storage.');
    try {await api('key-value-stores/'+fresh.id,{method:'PUT',body:{name:STORE,generalAccess:'RESTRICTED'}});}
    catch { /* A concurrent first save may already have claimed the name. Verify the winner below. */ }
    store=await api(named);
  }
  if (!owned(store,me.id) || store.name!==STORE || store.generalAccess!=='RESTRICTED') {
    throw Error('The Citebase billing store must be Restricted in this Apify account.');
  }
  const base='key-value-stores/'+store.id;
  if (write) {
    // Apify lists keys in lexical order. Independent writes retain both observations and the newest observation wins.
    const inverseTime=String(MAX_CLOCK-Date.parse(value.observed_at)).padStart(13,'0');
    const key=PREFIX+inverseTime+'-'+randomUUID();
    await api(base+'/records/'+key,{method:'PUT',body:value});
  }
  const listing=await api(base+'/keys?prefix='+PREFIX+'&limit=1');
  const first=listing?.items?.[0];
  if (!first && !write) return {balance:null};
  if (!first || !/^balance-v1-\d{13}-[a-f0-9-]{36}$/.test(first.key)) throw Error('Could not verify the saved billing balance.');
  return {balance:safeBalance(await api(base+'/records/'+first.key))};
}
module.exports={accountBalance};
