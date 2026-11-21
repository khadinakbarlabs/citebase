const assert = require('node:assert/strict');
const fs = require('node:fs');
const {createHash} = require('node:crypto');
const vm = require('node:vm');
const {test} = require('node:test');

class Node {
  constructor(tag, attrs, children) {
    Object.assign(this, attrs);
    this.tag = tag;
    this.children = children.flat(Infinity).filter(Boolean);
    this.isConnected = true;
    this.textContent = attrs.text || '';
    this.value = '';
  }
  appendChild(node) { this.children.push(node); return node; }
  addEventListener() {}

}
const find = (node, name) => node.textContent === name ? node :
  node.children.filter(child => child instanceof Node).map(child => find(child, name)).find(Boolean);
const actor = 'khadinakbar/dataforseo-keyword-research';
const serp = {actor:'khadinakbar/scrape-google-serp', purpose:'Measure organic rankings',
  input:{queries:['oak chairs'], maxResultsPages:1,countryCode:'US',languageCode:'en'}, maxTotalChargeUsd:0.1};
const traffic = {actor:'khadinakbar/similarweb-traffic-rank-scraper',purpose:'Estimate competitor traffic',
  input:{domains:['example.com'],countryName:'United States',languageCode:'en'},maxTotalChargeUsd:0.2};
const job = {actor, purpose:'Keyword demand', input:{seedKeywords:['office chairs']}, maxTotalChargeUsd:0.3};

function fixture(ambiguous = false, verify = async () => {}, jobs = [job,{...job, actor:'someone/anything'}], workHandlers = {}) {
  const values = new Map(), posts = [], imports = [];
  let account = 'account', session = 1;
  const CB = {
    h:(tag, attrs, ...children) => new Node(tag, attrs, children),
    clear:node => { node.children = []; return node; },
    sessionId:() => session,
    apify:async (method, path, input) => {
      if (path === 'users/me') return {id:account};
      if (method === 'POST') {
        posts.push({path,input});
        if (ambiguous) throw new Error('Connection lost');
        return {id:'abcdefghijklmnopq'};
      }
      return {id:'abcdefghijklmnopq', status:workHandlers.runStatus || 'SUCCEEDED'};
    },
    work:async (_, op, args) => {
      if (op === 'research_get') return workHandlers.read?.() || {revision:3};
      assert.equal(op, 'research_import');
      imports.push(args);
      return workHandlers.import?.(args) || {revision:4};
    },
    flows:{dialog:(_, body) => ({body, el:{open:true}, foot:new Node('div',{},[]),
      close() { this.el.open = false; }})},
    usage:{guard:() => ({node:new Node('div',{},[]), bind(button) { if (button) button.disabled = false; }, verify}),
      usd:n => '$'+n, errorDetails:()=>null}
  };
  const dialog = CB.flows.dialog;
  let lastDialog;
  CB.flows.dialog = (...args) => lastDialog = dialog(...args);
  const open = (options, planned = jobs) => {
    const context = {window:{CB,addEventListener(){}}, TextEncoder,
      crypto:{subtle:{digest:async (_, data) => createHash('sha256').update(data).digest()}}, localStorage:{getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value),
      removeItem:key=>values.delete(key)}, navigator:{locks:{request:(_,fn)=>fn()}}, setTimeout, clearTimeout};
    vm.runInNewContext(fs.readFileSync('site/app/session.js','utf8'),context);
    vm.runInNewContext(fs.readFileSync('site/app/research-collection.js','utf8'),context);
    return CB.researchCollection.panel('chairs',{jobs:planned},undefined,options);
  };
  return {open, posts, imports, values, setAccount(id) { account = id; session++; }, get dialog() { return lastDialog; }};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('allowed measurement starts only after review and imports its exact completed receipt', async () => {
  const f = fixture();
  const panel = f.open();
  await settle();
  await find(panel,'Review paid check').onclick();
  assert.equal(f.posts.length,0);
  const approve = find(f.dialog.foot,'Approve and start paid check');
  await Promise.all([approve.onclick(),approve.onclick()]);
  await find(panel,"Check now").onclick();
  await settle();
  assert.equal(f.posts.length,1);
  assert.match(f.posts[0].path,/dataforseo-keyword-research\/runs\?maxTotalChargeUsd=0.3$/);
  assert.equal(f.imports.length,1);
  assert.equal(f.imports[0].run_id,'abcdefghijklmnopq');
  assert.equal(f.imports[0].expected_revision,3);
  assert.ok(find(panel,'This measurement can be imported from an existing source.'));
});

test('an ambiguous start persists across reload and offers no duplicate paid start', async () => {
  const f = fixture(true);
  const panel = f.open();
  await settle();
  await find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  const restored = f.open();
  await settle();
  assert.equal(f.posts.length,1);
  assert.equal(f.imports.length,0);
  assert.equal(find(restored,'Review paid check'),undefined);
  assert.ok(find(restored,'Start could not be confirmed. Check Apify Activity and import the run ID below.'));
});

test('billing verification stops a paid start', async () => {
  const f = fixture(false, async () => { throw new Error('Review Apify billing.'); });
  const panel = f.open();
  await settle();
  await find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  assert.equal(f.posts.length,0);
  assert.ok(find(f.dialog.body,'Review Apify billing.'));
});

test('a confirmed receipt resumes after navigation without a second paid start', async () => {
  const f = fixture();
  const panel = f.open();
  await settle();
  await find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  panel.isConnected = false;
  const resumed = f.open();
  await settle();
  await find(resumed,'Check now').onclick();
  assert.equal(f.posts.length,1);
  assert.equal(f.imports.length,1);
  assert.equal(f.imports[0].run_id,'abcdefghijklmnopq');
});

test('discovery offers only the reviewed SERP check before rivals are verified', async () => {
  const f = fixture(false, undefined, [job, serp, traffic]);
  const panel = f.open({discovery:true});
  await settle();
  assert.ok(find(panel,'Measure organic rankings'));
  assert.equal(find(panel,'Keyword demand'),undefined);
  assert.equal(find(panel,'Estimate competitor traffic'),undefined);
  await find(panel,'Review paid check').onclick();
  assert.ok(find(f.dialog.body,'Search terms: oak chairs'));
  assert.ok(find(f.dialog.body,'Market: US'));
  assert.equal(f.posts.length,0);
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  await find(panel,'Check now').onclick();
  assert.equal(f.posts.length,1);
  assert.match(f.posts[0].path,/scrape-google-serp\/runs\?maxTotalChargeUsd=0.1$/);
  assert.equal(f.imports.length,1);
});

test('traffic review names the domains and market before starting', async () => {
  const f = fixture(false, undefined, [traffic]);
  const panel = f.open();
  await settle();
  await find(panel,'Review paid check').onclick();
  assert.ok(find(f.dialog.body,'Domains: example.com'));
  assert.ok(find(f.dialog.body,'Market: United States'));
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  await find(panel,'Check now').onclick();
  assert.match(f.posts[0].path,/similarweb-traffic-rank-scraper\/runs\?maxTotalChargeUsd=0.2$/);
  assert.equal(f.imports.length,1);
});

const aiActor = 'khadinakbar/ai-search-brand-monitor';
const aiJob = (engine, purpose) => ({actor:aiActor,purpose,source:purpose,maxTotalChargeUsd:0.4,
  input:{platforms:[engine],brandName:'Chairs',brandDomain:'chairs.com',competitors:['Other chairs'],
    customQueries:['What chair should I buy?'],querySelectionMode:'custom_only',maxQueriesPerPlatform:1}});
const keywordsActor = 'khadinakbar/ahrefs-alternative';
const rankedJob = (target, purpose) => ({actor:keywordsActor,purpose,maxTotalChargeUsd:0.25,
  input:{mode:'organic_keywords',target,locationName:'United States',languageCode:'en',maxResults:10}});

test('AI engine jobs sharing an Actor have separate approval receipts', async () => {
  const jobs = [aiJob('chatgpt','ChatGPT'),aiJob('claude','Claude'),aiJob('gemini','Gemini')];
  const f = fixture(false, undefined, jobs);
  const panel = f.open();
  await settle();
  for (const [index, job] of jobs.entries()) {
    await find(panel.children[0].children[index],'Review paid check').onclick();
    assert.ok(find(f.dialog.body,'Questions: What chair should I buy?'));
    assert.ok(find(f.dialog.body,'Brand: Chairs'));
    await find(f.dialog.foot,'Approve and start paid check').onclick();
    await find(panel.children[0].children[index],'Check now').onclick();
    assert.equal(f.posts[index].input.platforms[0],job.input.platforms[0]);
  }
  assert.equal(f.posts.length,3);
  assert.equal(f.imports.length,3);
});

test('ranked keywords require the reviewed organic mode and use independent competitor receipts', async () => {
  const jobs = [rankedJob('one.example','First competitor'),rankedJob('two.example','Second competitor'),
    {...rankedJob('evil.example','Wrong mode'),input:{...rankedJob('evil.example').input,mode:'backlinks'}}];
  const f = fixture(false, undefined, jobs);
  const panel = f.open();
  await settle();
  assert.equal(find(panel.children[0].children[2],'Review paid check'),undefined);
  for (const [index, job] of jobs.slice(0,2).entries()) {
    await find(panel.children[0].children[index],'Review paid check').onclick();
    assert.ok(find(f.dialog.body,'Domain: ' + job.input.target));
    await find(f.dialog.foot,'Approve and start paid check').onclick();
    await find(panel.children[0].children[index],'Check now').onclick();
    assert.equal(f.posts[index].input.target,job.input.target);
  }
  assert.equal(f.posts.length,2);
});

test('an existing run goes to authoritative import without a new Apify start', async () => {
  const f = fixture();
  const panel = f.open();
  await settle();
  find(panel,'Import an Apify run').onclick();
  const label = f.dialog.body.children.find(node => node.tag === 'label');
  label.children.find(node => node.tag === 'input').value = 'abcdefghijklmnopq';
  await find(f.dialog.foot,'Save measurements').onclick();
  assert.equal(f.posts.length,0);
  assert.equal(f.imports.length,1);
  assert.equal(f.imports[0].run_id,'abcdefghijklmnopq');
  assert.equal(f.imports[0].expected_revision,3);
});


test('a concurrent save retries the same completed run against the fresh revision once', async () => {
  let rev = 3;
  const f = fixture(false, undefined, [job], {
    read:() => ({revision:rev}),
    import:args => {
      if (args.expected_revision === 3) { rev = 4; throw new Error('Revision conflict'); }
      return {revision:5};
    }
  });
  const panel = f.open();
  await settle();
  find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  await find(panel,'Check now').onclick();
  assert.equal(f.posts.length,1);
  assert.deepEqual(f.imports.map(args => args.expected_revision),[3,4]);
  assert.ok(f.imports.every(args => args.run_id === 'abcdefghijklmnopq'));
});

test('a lost import reply is reconciled by verified run ID without another import', async () => {
  let existing = false;
  const f = fixture(false, undefined, [job], {
    read:() => existing ? {revision:4,keywords:[{run_id:'abcdefghijklmnopq',term:'office chairs',provenance:'verified_actor_run'}]} : {revision:3},
    import:() => { existing = true; throw new Error('Connection lost'); }
  });
  const panel = f.open();
  await settle();
  find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  await find(panel,'Check now').onclick();
  assert.equal(f.imports.length,1);
  assert.ok(find(panel,'Measurements saved from run abcdefghijklmnopq. See the report for evidence and gaps.'));
});

test('opaque receipts are isolated by account and expiry removes details without permitting a blind retry', async () => {
  const f = fixture(true);
  const panel = f.open();
  await settle();
  find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  const [key, record] = [...f.values.entries()][0];
  assert.match(key,/^cb\.research\.[a-f0-9]{64}$/);
  assert.equal(record.includes('office chairs'),false);
  f.values.set(key,JSON.stringify({...JSON.parse(record),expires:0}));
  const expired = f.open();
  await settle();
  assert.ok(find(expired,'The saved receipt expired. Review Apify Activity and import the run ID below.'));
  assert.deepEqual(JSON.parse(f.values.get(key)),{status:'expired'});
  assert.equal(find(expired,'Review paid check'),undefined);
  f.setAccount('another-account');
  const other = f.open();
  await settle();
  assert.ok(find(other,'Review paid check'));
  assert.equal(f.posts.length,1);
});


test('terminal AI receipts match full canonical input and allow a changed competitor roster', async () => {
  const item = aiJob('chatgpt','ChatGPT');
  const f = fixture(false,undefined,[item]);
  const panel = f.open();
  await settle();
  find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  await find(panel,'Check now').onclick();
  const reordered = {...item,input:Object.fromEntries(Object.entries(item.input).reverse())};
  const same = f.open(undefined,[reordered]);
  await settle();
  assert.equal(find(same,'Review paid check'),undefined);
  const changed = f.open(undefined,[{...item,input:{...item.input,competitors:['New competitor']}}]);
  await settle();
  assert.ok(find(changed,'Review paid check'));
  assert.equal(f.posts.length,1);
});

test('expiring a saved terminal receipt permits a new explicit review', async () => {
  const f = fixture();
  const panel = f.open();
  await settle();
  find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  await find(panel,'Check now').onclick();
  const [key, entry] = [...f.values.entries()][0];
  f.values.set(key,JSON.stringify({...JSON.parse(entry),expires:0}));
  const reopened = f.open();
  await settle();
  assert.ok(find(reopened,'Review paid check'));
  assert.equal(f.posts.length,1);
});


test('an expired failed run permits review without automatic spending', async () => {
  const f = fixture(false,undefined,[job],{runStatus:'FAILED'});
  const panel = f.open();
  await settle();
  find(panel,'Review paid check').onclick();
  await find(f.dialog.foot,'Approve and start paid check').onclick();
  await find(panel,'Check now').onclick();
  assert.equal(f.imports.length,0);
  assert.equal(find(panel,'Review paid check'),undefined);
  const [key, entry] = [...f.values.entries()][0];
  f.values.set(key,JSON.stringify({...JSON.parse(entry),expires:0}));
  const reopened = f.open();
  await settle();
  assert.ok(find(reopened,'Review paid check'));
  assert.equal(f.posts.length,1);
});

test('a signed-out dialog cannot start against a different account', async () => {
  const f = fixture();
  const panel = f.open();
  await settle();
  find(panel,'Review paid check').onclick();
  const approve = find(f.dialog.foot,'Approve and start paid check');
  f.setAccount('new-account');
  await approve.onclick();
  assert.equal(f.posts.length,0);
  assert.equal(f.values.size,0);
});
