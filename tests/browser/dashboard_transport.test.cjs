'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

const source = name => fs.readFileSync(path.join(__dirname, '../../site/app', name), 'utf8');
const tokenUrl = 'https://signin.example.test/token';
const actorOrigin = 'https://khadinakbar--citebase.apify.actor';
const runUrl = actorOrigin + '/run';
const relayUrl = '/api/actor/';
const turn = () => new Promise(resolve => setImmediate(resolve));
const response = (body, status = 200) => ({status, ok: status >= 200 && status < 300, json: async () => body});
const toolReply = result => response({ok: true, result});
const newTokens = () => response({access_token: 'access-2', refresh_token: 'refresh-2'});
const offline = () => { throw new TypeError('Connection interrupted'); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

async function tab(reply, options = {}) {
  const values = new Map(Object.entries({'cb.t': 'access-1', 'cb.r': 'refresh-1', ...options.values}));
  const clock = {now: Date.now()};
  const requests = [];
  const origin = options.origin || (options.hosted ? 'https://dashboard.example' : 'http://127.0.0.1:19870');
  const location = {origin, hostname:new URL(origin).hostname, pathname: '/app/', hash: '', search: options.search || '',
    assign(url) { this.redirect = url; }};
  const brokerCalls = [];
  let version = 1;
  const window = {addEventListener() {}, __CB: {api: options.api || actorOrigin, projectWork: options.projectWork,
    oauth: {session:options.hosted === true, token: tokenUrl, clientId: 'public-client', authorize: 'https://signin.example.test/authorize'}}};
  if (options.hosted) window.CitebaseSession = {
    onChange() {},
    async request(action, fields) {
      brokerCalls.push({action, fields});
      if (action === 'refresh') version++;
      return {signedIn:true, sessionId:'fixture-session', version, accessToken:'access-' + version,
        canRefresh:true, sessionUntil:Math.floor(clock.now / 1000) + 3600};
    }
  };
  const context = vm.createContext({window, location, URL, URLSearchParams, TextEncoder, Uint8Array, btoa,
    crypto: webcrypto, history: {replaceState() {}}, document: {getElementById: () => ({}), addEventListener() {}},
    Date: class extends Date { static now() { return clock.now; } },
    sessionStorage: {setItem: (k,v) => values.set(k,String(v)), getItem: k => values.get(k) ?? null,
      removeItem: k => values.delete(k)},
    fetch: async (url, init) => {
      const actor = url === runUrl || url === relayUrl || url === origin + '/run';
      const request = {url, init:{...init, headers:{...init.headers}}, body:actor ? JSON.parse(init.body) : null,
        bearer:init.headers.Authorization};
      requests.push(request);
      return reply(request, requests);
    }});
  vm.runInContext(source('core.js'), context);
  const cb = window.CB;
  const signedOut = [];
  cb.onSignedOut = message => { signedOut.push(message); cb.forget(); };
  const auth = options.start === false ? null : await cb.startAuth();
  return {cb, values, requests, clock, context, location, signedOut, auth, brokerCalls};
}

test('a history-only release uses the published account API and keeps sample work offline', async () => {
  const env = await tab(() => toolReply({projects: []}), {projectWork: false});
  assert.equal(env.cb.hasProjectWork, false);
  await env.cb.history();
  assert.equal(env.requests[0].body.tool, 'get_history');
  assert.equal(env.requests[0].bearer, 'Bearer access-1');
  assert.equal(env.requests[0].init.headers['X-Apify-Authorization'], undefined);
  assert.equal(env.requests[0].init.headers['X-Citebase-Authorization'], undefined);
  await assert.rejects(env.cb.work('coffee', 'brief_get'), /sample/i);
  assert.equal(env.requests.length, 1);
  const sample = await tab(offline, {projectWork: false, search: '?demo=1'});
  sample.cb.demoWork = () => ({source: 'sample'});
  assert.equal(sample.cb.hasProjectWork, true);
  assert.equal((await sample.cb.work('coffee', 'brief_get')).source, 'sample');
  assert.equal(sample.requests.length, 0);
});

test('only enhanced requests to the Citebase Actor or its same-origin loopback fixture carry the forwarded caller credential', async () => {
  for (const api of [actorOrigin, 'http://127.0.0.1:19870']) {
    const env = await tab(() => toolReply({projects: []}), {api});
    await env.cb.history();
    const actor = env.requests[0];
    assert.equal(actor.url, api + '/run');
    for (const key of ['Authorization', 'X-Apify-Authorization', 'X-Citebase-Authorization']) {
      assert.equal(actor.init.headers[key], 'Bearer access-1');
    }
    assert.equal(actor.init.redirect, 'error');
    await env.cb.apify('GET', 'users/me');
    const provider = env.requests[1];
    assert.equal(provider.url, 'https://api.apify.com/v2/users/me');
    assert.equal(provider.init.headers.Authorization, 'Bearer access-1');
    assert.equal(provider.init.headers['X-Citebase-Authorization'], undefined);
    assert.equal(provider.init.headers['X-Apify-Authorization'], undefined);
  }
});

test('an unexpected Actor origin or path receives no account header or network request', async () => {
  for (const api of ['https://api.apify.com', 'https://elsewhere.example', 'https://other--citebase.apify.actor',
    'https://khadinakbar--citebase.apify.actor.example', actorOrigin + '/other', actorOrigin + '?app=',
    'http://khadinakbar--citebase.apify.actor', 'http://127.0.0.1:20222']) {
    const env = await tab(offline, {api});
    await assert.rejects(env.cb.history(), /Citebase service address/);
    assert.equal(env.requests.length, 0, api);
  }
});

test('hosted projects use the signed-in same-origin Actor relay and Apify account reads stay direct', async () => {
  const env = await tab(({url}) => url === relayUrl ? toolReply({projects:[]}) : response({data:{username:'owner'}}), {hosted:true});
  assert.equal(env.auth, 'in');
  assert.deepEqual((await env.cb.history()).projects, []);
  const [actor] = env.requests;
  assert.equal(actor.url, relayUrl);
  assert.deepEqual(actor.body, {tool:'get_history', arguments:{}});
  assert.equal(actor.init.credentials, 'same-origin');
  assert.equal(actor.init.mode, 'same-origin');
  assert.equal(actor.init.redirect, 'error');
  assert.equal(actor.init.cache, 'no-store');
  assert.deepEqual(actor.init.headers, {
    'Content-Type':'application/json', Authorization:'Bearer access-1', 'X-Citebase-Session':'1'
  });
  assert.equal((await env.cb.apify('GET', 'users/me')).username, 'owner');
  assert.equal(env.requests[1].url, 'https://api.apify.com/v2/users/me');
  assert.deepEqual(env.requests[1].init.headers, {Authorization:'Bearer access-1'});
  const historyOnly = await tab(() => toolReply({projects:[]}), {hosted:true, projectWork:false});
  await historyOnly.cb.history();
  assert.equal(historyOnly.requests[0].url, runUrl);
  assert.deepEqual(historyOnly.requests[0].init.headers, {'Content-Type':'application/json', Authorization:'Bearer access-1'});
  for (const api of ['https://elsewhere.example', actorOrigin + '/other', 'https://dashboard.example/api/actor']) {
    const untrusted = await tab(offline, {hosted:true, api});
    await assert.rejects(untrusted.cb.history(), /service address/);
    assert.equal(untrusted.requests.length, 0);
  }
});

test('persistent loopback sign-in preserves a configured local Actor and relays the canonical Actor', async () => {
  const origin = 'http://127.0.0.1:19870';
  const local = await tab(() => toolReply({saved:true}), {hosted:true, origin, api:origin});
  assert.equal((await local.cb.tool('save_results', {project:'coffee'})).saved, true);
  const [request] = local.requests;
  assert.equal(request.url, origin + '/run');
  assert.equal(request.init.redirect, 'error');
  assert.deepEqual(request.init.headers, {
    'Content-Type':'application/json', Authorization:'Bearer access-1',
    'X-Apify-Authorization':'Bearer access-1', 'X-Citebase-Authorization':'Bearer access-1'
  });
  assert.equal(local.brokerCalls.filter(call => call.action === 'verify').length, 1);
  const canonical = await tab(() => toolReply({projects:[]}), {hosted:true, origin, api:actorOrigin});
  await canonical.cb.history();
  assert.equal(canonical.requests[0].url, relayUrl);
  assert.equal(canonical.requests[0].init.headers['X-Citebase-Session'], '1');
  const otherPort = await tab(offline, {hosted:true, origin, api:'http://127.0.0.1:19871'});
  await assert.rejects(otherPort.cb.history(), /service address/);
  assert.equal(otherPort.requests.length, 0);
});

test('hosted relay retries a write only when the server confirms it never dispatched the previous attempt', async () => {
  for (const refusal of ['local', 'upstream', 'interrupted']) {
    const env = await tab(({url, bearer}) => {
      assert.equal(url, relayUrl);
      if (bearer === 'Bearer access-2') return toolReply({result:{saved:true}});
      if (refusal === 'interrupted') return offline();
      const denied = response({error:'Account verification failed.'}, 401);
      denied.headers = {get:key => key === 'X-Citebase-Not-Dispatched' && refusal === 'local' ? '1' : null};
      return denied;
    }, {hosted:true});
    const submit = env.cb.work('coffee', 'brief_save', {goal:'More enquiries'});
    if (refusal === 'local') {
      assert.equal((await submit).saved, true);
      assert.deepEqual(env.requests.map(req => req.bearer), ['Bearer access-1','Bearer access-2']);
      const rotation = env.brokerCalls.find(call => call.action === 'refresh');
      assert.equal(rotation.fields.sessionId, 'fixture-session');
      assert.equal(rotation.fields.version, 1);
    } else {
      await assert.rejects(submit);
      assert.equal(env.requests.length, 1);
      assert.equal(env.brokerCalls.filter(call => call.action === 'refresh').length, 0);
    }
    assert.equal(env.brokerCalls.filter(call => call.action === 'verify').length, 1);
  }
});

test('a hosted read can recover from an upstream 401 while an old browser session cannot restore project data', async () => {
  const delayed = deferred();
  const env = await tab(({url, bearer, body}) => {
    assert.equal(url, relayUrl);
    if (body.arguments.project === 'stale') return delayed.promise;
    return bearer === 'Bearer access-1' ? response({}, 401) : toolReply({projects:[]});
  }, {hosted:true});
  assert.deepEqual((await env.cb.history()).projects, []);
  assert.deepEqual(env.requests.map(req => req.bearer), ['Bearer access-1','Bearer access-2']);
  const previous = env.cb.history('stale');
  env.cb.forget();
  await env.cb.startAuth();
  delayed.resolve(toolReply({project:'private stale result'}));
  await assert.rejects(previous, /signed out/);
  assert.deepEqual((await env.cb.history()).projects, []);
});

test('project and picker reads share overlapping calls, reuse recent results and expire', async () => {
  const gate = deferred();
  const env = await tab(async ({body}, requests) => {
    const n = requests.length;
    await gate.promise;
    return toolReply({slug: body.arguments.project || '', n});
  });
  const a = env.cb.history('coffee');
  const b = env.cb.history('coffee');
  const c = env.cb.history('coffee', true);
  const picker = env.cb.history();
  const other = env.cb.history('constructor');
  assert.equal(env.requests.length, 3);
  gate.resolve();
  const first = await a;
  assert.equal(await b, first);
  assert.equal(await c, first);
  assert.equal((await picker).slug, '');
  assert.equal((await other).slug, 'constructor');
  assert.equal(await env.cb.history('coffee'), first);
  const reloaded = await env.cb.history('coffee', true);
  assert.notEqual(reloaded.n, first.n);
  assert.equal((await env.cb.history('coffee')).n, reloaded.n);
  env.clock.now += 30_001;
  assert.notEqual((await env.cb.history('coffee')).n, reloaded.n);
  assert.equal(env.requests.length, 5);
});

test('an invalidated history request cannot overwrite a newer result or evict it on a late failure', async () => {
  for (const failLate of [false, true]) {
    const gate = deferred();
    const env = await tab((_, requests) => requests.length === 1 ? gate.promise : toolReply({n: requests.length}));
    const previous = env.cb.history('coffee');
    env.cb.refresh();
    const updated = await env.cb.history('coffee');
    if (failLate) gate.resolve(response({ok:false, error:'Earlier request failed'}, 503));
    else gate.resolve(toolReply({n:1}));
    await previous.catch(() => {});
    assert.equal(updated.n, 2);
    assert.equal(await env.cb.history('coffee'), updated);
    assert.equal(env.requests.length, 2);
  }
});

test('Overview reuses the exact focus queue across mounts; project, limit and priority stay distinct', async () => {
  const first = deferred();
  const env = await tab(({body}, requests) => {
    if ('unexpected' in body.arguments.data) return response({ok:false, error:'Unsupported field'},400);
    return requests.length === 1 ? first.promise : toolReply({result:{sequence:requests.length}});
  });
  const queue = (project, data, fresh) => env.cb.work(project, 'project_focus', data, fresh);
  const a = queue('clinic', {limit:20, priority:'open'}), b = queue('clinic', {priority:'open', limit:20});
  assert.equal(env.requests.length, 1);
  first.resolve(toolReply({result:{sequence:1}}));
  const result = await a;
  assert.equal(await b, result);
  assert.equal(await queue('clinic', {limit:20, priority:'open'}), result);
  assert.equal((await queue('clinic', {limit:20})).sequence, 2);
  assert.equal((await queue('clinic', {priority:'open', limit:5})).sequence, 3);
  assert.equal((await queue('other', {priority:'open', limit:20})).sequence, 4);
  await assert.rejects(queue('clinic', {limit:20, unexpected:true}), /Unsupported field/);
  assert.equal((await queue('clinic', {limit:20}, true)).sequence, 6);
  env.clock.now += 30_001;
  assert.equal((await queue('clinic', {priority:'open',limit:20})).sequence, 7);
  await env.cb.work('clinic','changes_list',{});
  await env.cb.work('clinic','changes_list',{});
  assert.equal(env.requests.length, 9);
});

test('mutations invalidate every focus filter for the changed project even if the confirmation is lost', async () => {
  let revision = 0, focusReads = 0;
  const old = deferred();
  const env = await tab(({body}) => {
    if (body.arguments.operation === 'project_focus') {
      focusReads++;
      return focusReads === 1 ? old.promise : toolReply({result:{revision}});
    }
    revision++;
    return body.arguments.operation === 'action_recheck' ? offline() : toolReply({result:{}});
  });
  const queue = (project, priority) => env.cb.work(project,'project_focus', priority ? {priority} : {});
  const oldRead = queue('clinic');
  await queue('clinic','open');
  const other = await queue('other');
  const mutations = [() => env.cb.work('clinic','action_save',{}), () => env.cb.work('clinic','action_recheck',{}),
    () => env.cb.tool('save_results',{project:'clinic'}), () => env.cb.tool('import_ai_results',{project:'clinic',save:true})];
  for (const mutate of mutations) {
    await mutate().catch(error => assert.match(error.message, /review/i));
    assert.equal((await queue('clinic')).revision, revision);
    assert.equal((await queue('clinic','open')).revision, revision);
    assert.equal(await queue('other'), other);
  }
  old.resolve(toolReply({result:{revision:0}}));
  await oldRead;
  assert.equal((await queue('clinic')).revision, 4);
  assert.equal(focusReads, 11);
});

test('focus retry is fresh after an error, explicit reload, and account replacement', async () => {
  const env = await tab(({bearer}, requests) => requests.length === 1 ? toolReply(null)
    : toolReply({result:{bearer, sequence:requests.length}}));
  const queue = () => env.cb.work('clinic','project_focus',{});
  await assert.rejects(queue());
  assert.equal((await queue()).sequence, 2);
  env.cb.refresh();
  assert.equal((await queue()).sequence, 3);
  env.cb.forget();
  env.values.set('cb.t','new-account');
  await env.cb.startAuth();
  const latest = await queue();
  assert.equal(latest.sequence, 4);
  assert.equal(latest.bearer, 'Bearer new-account');
});

test('failed history can be retried; writes invalidate only the affected project and picker', async () => {
  let fail = true, version = 0;
  const env = await tab(({body}) => {
    if (body.tool === 'get_history') {
      if (fail) {fail = false; return response({ok:false, error:'Temporary error'}, 503);}
      return toolReply({version});
    }
    if (!body.arguments.check_only) version++;
    return toolReply({result: {}});
  });
  await assert.rejects(env.cb.history('coffee'), /Temporary error/);
  const other = await env.cb.history('other');
  await env.cb.history();
  await env.cb.history('coffee');
  await env.cb.tool('save_results', {project:'coffee', check_only:true});
  const afterPreview = env.requests.length;
  await env.cb.history('coffee');
  assert.equal(env.requests.length, afterPreview);
  const saves = [() => env.cb.saveTodo('coffee', []), () => env.cb.tool('save_results', {project:'coffee'}),
    () => env.cb.tool('import_ai_results', {project:'coffee', save:true}), () => env.cb.work('coffee', 'action_save', {})];
  for (const save of saves) {
    await save();
    assert.equal((await env.cb.history('coffee')).version, version);
    assert.equal((await env.cb.history()).version, version);
    assert.equal(await env.cb.history('other'), other);
  }
});

test('overlapping and delayed 401s use just one rotating refresh credential', async () => {
  const refresh = deferred(), delayed = deferred();
  const env = await tab(({url, bearer, body}) => {
    if (url === tokenUrl) return refresh.promise;
    if (bearer === 'Bearer access-1') return body?.arguments.project === 'slow' ? delayed.promise : response({}, 401);
    assert.equal(bearer, 'Bearer access-2');
    return url === runUrl ? toolReply({project:body.arguments.project}) : response({data:{id:'fixture'}});
  });
  const reads = [env.cb.history('coffee'), env.cb.apify('GET', 'users/me'), env.cb.history('slow')];
  await turn();
  assert.equal(env.requests.filter(q => q.url === tokenUrl).length, 1);
  refresh.resolve(newTokens());
  await Promise.all(reads.slice(0,2));
  delayed.resolve(response({}, 401));
  await Promise.all(reads);
  assert.equal(env.requests.filter(q => q.url === tokenUrl).length, 1);
  assert.equal(env.values.get('cb.r'), 'refresh-2');
  assert.equal(env.signedOut.length, 0);
});

test('opaque read failures can recover while transient token errors preserve the session for retry', async () => {
  for (const tokenFailure of [offline, () => response({error:'temporarily_unavailable'}, 503)]) {
    let attempts = 0;
    const env = await tab(({url, bearer}) => {
      if (url === tokenUrl) return ++attempts === 1 ? tokenFailure() : newTokens();
      if (bearer === 'Bearer access-1') return offline();
      return toolReply({recovered:true});
    });
    env.values.set('cb.pending', 'existing-receipt');
    await assert.rejects(env.cb.history('coffee'));
    assert.equal(env.signedOut.length, 0);
    assert.equal(env.values.get('cb.r'), 'refresh-1');
    assert.equal(env.values.get('cb.pending'), 'existing-receipt');
    assert.equal((await env.cb.history('coffee')).recovered, true);
    assert.equal(attempts, 2);
  }
});

test('a mutation with an unknown outcome is issued once, including a paid Apify run', async () => {
  const cases = [cb => cb.work('coffee','schedule_apply',{confirmed:true}), cb => cb.work('coffee','action_save',{}),
    cb => cb.tool('save_results', {project:'coffee'}), cb => cb.tool('unknown_future_write', {project:'coffee'}),
    cb => cb.apify('POST','acts/owner~fixture/runs',{fixture:true})];
  for (const send of cases) {
    const env = await tab(({url}) => url === tokenUrl ? newTokens() : offline());
    await assert.rejects(send(env.cb), /check|review/i);
    assert.equal(env.requests.length, 1);
    assert.equal(env.signedOut.length, 0);
  }
});

test('losing the confirmation of an applied change invalidates pre-change history', async () => {
  let revision = 1;
  const old = deferred();
  const env = await tab(({body}, requests) => {
    if (body.tool === 'save_results') { revision++; return offline(); }
    return requests.length === 1 ? old.promise : toolReply({revision});
  });
  const oldRead = env.cb.history('coffee');
  await env.cb.history();
  await assert.rejects(env.cb.saveTodo('coffee', [{step:'Call on Tuesday'}]), /review/i);
  const current = await env.cb.history('coffee');
  assert.equal(current.revision, 2);
  assert.equal((await env.cb.history()).revision, 2);
  old.resolve(toolReply({revision:1}));
  await oldRead;
  assert.equal(await env.cb.history('coffee'), current);
  assert.equal(env.requests.filter(q => q.body.tool === 'save_results').length, 1);
});

test('a readable 401 can recover an unauthorized mutation; invalid_grant ends an expired session', async () => {
  let valid = true;
  const env = await tab(({url, bearer}) => {
    if (url === tokenUrl) return valid ? newTokens() : response({error:'invalid_grant'}, 400);
    return bearer === 'Bearer access-2' && valid ? toolReply({saved:true}) : response({}, 401);
  });
  assert.equal((await env.cb.saveTodo('coffee', [])).saved, true);
  valid = false;
  await assert.rejects(env.cb.history('coffee'), /signed out/i);
  assert.equal(env.signedOut.length, 1);
  assert.ok(!env.values.has('cb.t'));
});

test('responses from a signed-out account cannot refill history or revive its tokens', async () => {
  for (const stage of ['history','refresh']) {
    const late = deferred();
    const env = await tab(({url, bearer}) => {
      if (url === tokenUrl) return late.promise;
      if (bearer === 'Bearer access-1') return stage === 'history' ? late.promise : response({},401);
      return toolReply({account:'second'});
    });
    const first = env.cb.history('coffee');
    await turn();
    env.cb.forget();
    env.values.set('cb.t', 'another-account');
    env.values.set('cb.r', 'another-refresh');
    await env.cb.startAuth();
    const second = await env.cb.history('coffee');
    late.resolve(stage === 'history' ? toolReply({account:'first'}) : newTokens());
    await assert.rejects(first, /signed out|session/i);
    assert.equal(env.signedOut.length, 0);
    assert.equal(env.values.get('cb.t'), 'another-account');
    assert.equal(env.values.get('cb.r'), 'another-refresh');
    assert.equal(second.account, 'second');
    assert.equal(await env.cb.history('coffee'), second);
  }
});

test('PKCE still checks state and sends the verifier only in the code exchange', async () => {
  const env = await tab(() => { throw new Error('Unexpected network call'); });
  env.cb.signIn();
  while (!env.location.redirect) await turn();
  const auth = new URL(env.location.redirect).searchParams;
  assert.equal(auth.get('code_challenge_method'), 'S256');
  const verifier = env.values.get('cb.v'), state = env.values.get('cb.s');
  const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  assert.equal(auth.get('code_challenge'), Buffer.from(digest).toString('base64url'));
  assert.equal(auth.get('state'), state);
  assert.equal(auth.has('code_verifier'), false);
  for (const supplied of ['incorrect-state', state]) {
    const back = await tab(({url,init}) => {
      assert.equal(url, tokenUrl);
      assert.equal(new URLSearchParams(init.body).get('code_verifier'), verifier);
      return response({access_token:'first-login'});
    }, {values:{'cb.s':state,'cb.v':verifier}, search:'?code=fixture&state='+supplied});
    assert.equal(back.auth, supplied === state ? 'in' : 'failed');
    assert.equal(back.requests.length, supplied === state ? 1 : 0);
    if (supplied === state) assert.ok(!back.values.has('cb.r'));
  }
});

test('a confirmed paid check keeps all accepted run IDs across a valid session refresh', async () => {
  let started = 0;
  const env = await tab(({url,body,bearer}) => {
    if (url === tokenUrl) return newTokens();
    if (body) return toolReply({ready_runs:[{name:'Fixture',actor:'owner/fixture',times:2,max_cost_per_run_usd:1,input:{}}]});
    if (url.includes('/users/me')) return usageReply(url, 2, 10, 30);
    if (bearer === 'Bearer access-1') return response({},401);
    return response({data:{id:'run-'+ ++started}});
  });
  const {buttons} = billingDialog(env);
  const session = env.cb.sessionId();
  env.cb.flows.aiCheck('coffee', {snapshots:[]});
  await turn();
  await buttons.get('Yes, start the paid check').click();
  assert.equal(env.cb.sessionId(), session);
  const pending = JSON.parse(env.values.get('cb.pending'));
  assert.deepEqual(pending[0].runs, ['run-1','run-2']);
  assert.equal(pending[0].startState, undefined);
  env.cb.forget();
  assert.notEqual(env.cb.sessionId(), session);
});

const receipt = id => ({project:'coffee', round:'baseline', at:'fixture-'+id, runs:[id]});
function runFixtures(env) {
  vm.runInContext(source('flows.js'), env.context);
  env.values.set('cb.pending', JSON.stringify([receipt('child-1')]));
  return env.cb.flows;
}
const finished = dataset => response({data:{status:'SUCCEEDED', defaultDatasetId:dataset}});

test('overlapping project views checking a finished run submit one import', async () => {
  const status = deferred(), imported = deferred();
  const env = await tab(({url}) => url === runUrl ? imported.promise : status.promise);
  const flows = runFixtures(env);
  const watches = [flows.watch('coffee'), flows.watch('coffee')];
  assert.equal(env.requests.length, 1);
  status.resolve(finished('dataset-1'));
  await turn();
  watches.push(flows.watch('coffee'));
  assert.equal(env.requests.filter(q => q.body?.tool === 'import_ai_results').length, 1);
  imported.resolve(toolReply({saved:true}));
  for (const result of await Promise.all(watches)) assert.equal(result.imported.saved, true);
  assert.equal(await flows.watch('coffee'), null);
  assert.deepEqual(JSON.parse(env.values.get('cb.pending')), []);
});

test('an unfinished import from another sign-in cannot poll, submit or clear the new account’s receipt', async () => {
  for (const stage of ['status', 'import']) {
    const late = deferred(), second = deferred();
    const env = await tab(({url, bearer}) => {
      if (bearer === 'Bearer other') return url === runUrl ? toolReply({saved:true}) : second.promise;
      if (stage === 'status' || url === runUrl) return late.promise;
      return finished('dataset-1');
    });
    const flows = runFixtures(env);
    const first = flows.watch('coffee').catch(() => null);
    await turn();
    env.cb.forget();
    env.values.set('cb.t','other');
    env.values.set('cb.r','other-refresh');
    await env.cb.startAuth();
    env.values.set('cb.pending', JSON.stringify([receipt('child-2')]));
    const current = flows.watch('coffee');
    await turn();
    assert.equal(env.requests.filter(q => q.url.endsWith('/actor-runs/child-2')).length, 1);
    late.resolve(stage === 'status' ? finished('dataset-1') : toolReply({saved:true}));
    await first;
    assert.deepEqual(JSON.parse(env.values.get('cb.pending'))[0], receipt('child-2'));
    second.resolve(finished('dataset-2'));
    assert.equal((await current).imported.saved, true);
    const newImports = env.requests.filter(q => q.bearer === 'Bearer other' && q.body?.tool === 'import_ai_results');
    assert.equal(newImports.length, 1);
    assert.deepEqual(newImports[0].body.arguments.dataset_ids, ['dataset-2']);
  }
});

test('an interrupted import is retained for manual review and never resubmitted after reload', async () => {
  const confirmation = deferred();
  const env = await tab(({url}) => url === runUrl ? confirmation.promise : finished('dataset-1'));
  const flows = runFixtures(env);
  const first = flows.watch('coffee');
  await turn();
  const reopened = await tab(() => { throw new Error('An unconfirmed import was automatically repeated'); },
    {values:Object.fromEntries(env.values)});
  vm.runInContext(source('flows.js'), reopened.context);
  const recovered = await reopened.cb.flows.watch('coffee');
  assert.match(recovered.error, /review/i);
  assert.equal(reopened.requests.length, 0);
  confirmation.reject(new TypeError('Response lost'));
  assert.match((await first).error, /review/i);
  assert.match((await flows.watch('coffee')).error, /review/i);
  assert.equal(JSON.parse(env.values.get('cb.pending'))[0].runs[0], 'child-1');
  assert.equal(env.requests.filter(q => q.body?.tool === 'import_ai_results').length, 1);
});

const usagePeriod = {startAt:'2026-11-01T00:00:00.000Z',endAt:'2026-11-30T23:59:59.999Z'};
function usageReply(url, spent, included, limit) {
  const path = new URL(url).pathname;
  if (path.endsWith('/usage/monthly')) return response({data:{usageCycle:usagePeriod,
    totalUsageCreditsUsdAfterVolumeDiscount:spent, totalUsageCreditsUsdBeforeVolumeDiscount:spent + 15}});
  if (path.endsWith('/limits')) return response({data:{monthlyUsageCycle:usagePeriod,limits:{maxMonthlyUsageUsd:limit},current:{monthlyUsageUsd:spent}}});
  if (path.endsWith('/users/me')) return response({data:{username:'fixture',proxy:{password:'fixture-private'},plan:{id:'STARTER',
    maxMonthlyUsageUsd:9999, monthlyUsageCreditsUsd:included},email:'fixture@example.invalid'}});
  throw new Error('Unexpected fixture path');
}
function billingDialog(env) {
  const buttons = new Map(), inputs = [];
  env.cb.h = (tag, attrs = {}, ...children) => {
    const el = {tag, textContent:attrs.text || '', children:children.flat(Infinity).filter(Boolean), disabled:!!attrs.disabled, checked:false,
      append(...nodes) { this.children.push(...nodes); }, appendChild(node) { this.children.push(node); return node; },
      addEventListener(type, handler) { this[type] = handler; }, setAttribute() {}, focus() {}};
    if (attrs.onclick) el.click = attrs.onclick;
    if (tag === 'button') buttons.set(attrs.text, el);
    if (tag === 'input') inputs.push(el);
    return el;
  };
  env.cb.clear = el => { el.children = []; el.textContent = ''; return el; };
  env.cb.toast = () => {};
  vm.runInContext(source('usage.js'), env.context);
  vm.runInContext(source('flows.js'), env.context);
  env.cb.flows.dialog = () => ({foot:env.cb.h('div'),el:{open:true},close() {}});
  return {buttons, inputs};
}

test('account usage separates monthly allowance and hard-limit room and drops private profile fields', async () => {
  const env = await tab(({url}) => usageReply(url, 12, 10, 30));
  vm.runInContext(source('usage.js'), env.context);
  const [a,b] = await Promise.all([env.cb.usage.read(), env.cb.usage.read()]);
  assert.equal(a,b); assert.equal(env.requests.length, 2);
  assert.ok(!env.requests.some(r => r.url.endsWith('/usage/monthly')), 'The daily billing breakdown is unnecessary when limits returns current spending');
  assert.equal(a.used,12); assert.equal(a.included,10); assert.equal(a.includedLeft,0);
  assert.equal(a.limit,30); assert.equal(a.room,18);
  assert.doesNotMatch(JSON.stringify(a), /fixture-private|example\.invalid|9999|password/);
  assert.equal(env.cb.usage.decision(a,0.55).kind, 'overage');
  assert.equal(env.cb.usage.decision(a,19).kind,'blocked');
  assert.equal(env.cb.usage.decision({...a,room:0},0.55).kind,'blocked');
  assert.equal(env.cb.usage.decision({...a,includedLeft:1},0.5).kind,'covered');
  assert.equal(env.cb.usage.decision({...a,includedLeft:1},1.01).kind,'overage');
  vm.runInContext(source('prepaid.js'), env.context);
  const prepaid = {amount_usd:0,period_end:'2099-12-31'};
  assert.equal(env.cb.usage.decision({...a,includedLeft:5,prepaid},0.5).kind,'overage');
  assert.equal(env.cb.usage.decision({...a,includedLeft:5,prepaid:{...prepaid,period_end:'2001-01-01'}},0.5).kind,'covered');
  assert.equal(env.cb.usage.decision({...a,prepaid:{...prepaid,amount_usd:20}},0.5).kind,'overage');
  assert.match(env.cb.usage.compact({...a,room:2,includedLeft:10}), /\$2\.00 before hard limit/);
});

test('an inaccessible limit is unknown and plan maximums or undiscounted usage cannot substitute for it', async () => {
  const env = await tab(({url}) => url.endsWith('/limits') ? response({error:{type:'insufficient-permissions'}},403) : usageReply(url,6,15,30));
  vm.runInContext(source('usage.js'), env.context);
  const a = await env.cb.usage.read();
  assert.equal(a.used,6); assert.equal(a.limit,null); assert.equal(a.room,null); assert.equal(a.includedLeft,9);
  assert.equal(a.restricted,true);
  assert.equal(env.cb.usage.decision(a,1).kind,'unknown');
  await assert.rejects(env.cb.apify('GET','users/me/limits'), error => error.status===403 && error.type==='insufficient-permissions' && !env.cb.usage.refusal(error));
});

test('annual allowances, null totals and zero hard limits keep distinguishable meanings', async () => {
  const env = await tab(({url}) => {
    if (url.endsWith('/users/me')) return response({data:{plan:{id:'YEARLY',monthlyUsageCreditsUsd:15,forceBillingInterval:'ANNUAL'}}});
    if (url.endsWith('/limits')) return response({data:{current:{monthlyUsageUsd:0},limits:{maxMonthlyUsageUsd:0}}});
    return response({data:{totalUsageCreditsUsdAfterVolumeDiscount:null,totalUsageCreditsUsdBeforeVolumeDiscount:55}});
  });
  vm.runInContext(source('usage.js'), env.context);
  const a=await env.cb.usage.read();
  assert.equal(a.included,15); assert.equal(a.includedLeft,null); assert.equal(a.used,0); assert.equal(a.room,0);
  assert.equal(env.cb.usage.decision(a,1).kind,'blocked');
});

test('a late billing read cannot display the previous account figures after sign-out', async () => {
  const first = deferred();
  const env=await tab(({url,bearer})=>bearer==='Bearer access-1' && url.endsWith('/limits') ? first.promise :
    usageReply(url,bearer==='Bearer access-1'?30:1,10,50));
  vm.runInContext(source('usage.js'),env.context);
  const old=env.cb.usage.read();
  env.cb.forget(); env.values.set('cb.t','other'); await env.cb.startAuth();
  const current=await env.cb.usage.read();
  first.resolve(usageReply('https://api.apify.com/v2/users/me/limits',30,10,50));
  await assert.rejects(old,/signed out/);
  assert.equal(current.used,1); assert.equal((await env.cb.usage.read()).used,1);
});

test('hard-limit changes between quote and confirmation prevent every paid launch', async () => {
  let spent=1, starts=0;
  const env=await tab(({url,body})=>{
    if (body) return toolReply({ready_runs:[{actor:'fixture/actor',name:'Fixture',times:1,max_cost_per_run_usd:1,input:{}}]});
    if (url.includes('/users/me')) return usageReply(url,spent,10,10);
    starts++; return response({data:{id:'unexpected'}});
  });
  const {buttons}=billingDialog(env);
  env.cb.flows.aiCheck('coffee',{}); await turn(); spent=10;
  await buttons.get('Yes, start the paid check').click();
  assert.equal(starts,0); assert.equal(env.values.has('cb.pending'),false);
});

test('overage requires acknowledgement, and a confirmed billing refusal leaves no phantom run', async () => {
  let starts=0;
  const env=await tab(({url,body})=>{
    if (body) return toolReply({ready_runs:[{actor:'fixture/actor',name:'Fixture',times:1,max_cost_per_run_usd:1,input:{}}]});
    if (url.includes('/users/me')) return usageReply(url,11,10,30);
    starts++; return response({error:{type:'not-enough-usage-to-run-paid-actor',message:'Usage refused'}},403);
  });
  const {buttons,inputs}=billingDialog(env);
  env.cb.flows.aiCheck('coffee',{}); await turn();
  const go=buttons.get('Yes, start the paid check');
  await go.click(); assert.equal(starts,0);
  inputs[0].checked=true; if(inputs[0].change) inputs[0].change();
  await go.click(); assert.equal(starts,1);
  assert.equal(JSON.parse(env.values.get('cb.pending') || '[]').length,0);
});

test('a billing refusal after one child preserves the confirmed run for review with no retry', async () => {
  let starts=0;
  const env=await tab(({url,body})=>{
    if(body) return toolReply({ready_runs:[{actor:'fixture/actor',name:'Fixture',times:3,max_cost_per_run_usd:1,input:{}}]});
    if(url.includes('/users/me')) return usageReply(url,1,10,40);
    return ++starts===1?response({data:{id:'child1'}}):response({error:{type:'not-enough-usage-to-run-paid-actor',message:'Shortfall'}},403);
  });
  const {buttons}=billingDialog(env);env.cb.flows.aiCheck('coffee',{});await turn();
  await buttons.get('Yes, start the paid check').click();
  const saved=JSON.parse(env.values.get('cb.pending'));
  assert.equal(starts,2);assert.deepEqual(saved[0].runs,['child1']);assert.equal(saved[0].startState,'partial');
});

test('a Standby payment refusal yields a billing action while normal quota failures keep their own meaning', async () => {
  const env=await tab(({body})=>body?response({error:{type:'platform-feature-disabled',message:'Monthly usage hard limit exceeded.'}},403):
    response({error:{type:'concurrent-runs-limit-exceeded',message:'Concurrent job limit reached.'}},403));
  vm.runInContext(source('usage.js'),env.context);
  await assert.rejects(env.cb.history(),e=>e.status===403 && /monthly usage|billing/i.test(env.cb.usage.refusal(e)));
  await assert.rejects(env.cb.apify('POST', 'acts/foo/runs',{}),e=>!env.cb.usage.refusal(e));
});

test('a provider billing rejection shows fresh direct account figures even if the Actor cannot load', async () => {
  const env = await tab(({url,body}) => body ? response({},402) : usageReply(url,5,5,5));
  billingDialog(env);
  const error = await env.cb.history().then(() => assert.fail('Expected billing refusal'), e=>e);
  const box = env.cb.usage.errorDetails(error);
  await turn();
  const contents = JSON.stringify(box);
  assert.match(contents,/\$5\.00 used/);
  assert.match(contents,/\$0\.00/);
  assert.match(contents,/Open Apify Billing/);
});

test('a reached platform spending limit is recognized without mistaking compute or concurrency constraints for money', async () => {
  const env = await tab(offline);
  vm.runInContext(source('usage.js'),env.context);
  assert.match(env.cb.usage.refusal({status:403,type:'platform-feature-disabled',
    message:'Your account has reached the hard limit for platform usage for this billing cycle.'}), /billing/i);
  assert.equal(env.cb.usage.refusal({status:403,type:'platform-feature-disabled',
    message:'The maximum monthly Actor compute units limit was reached.'}), null);
});

test('a paid schedule needs explicit future overage consent even with enough credit today', async () => {
  const env = await tab(({url}) => usageReply(url, 1, 20, 40));
  const {inputs} = billingDialog(env);
  const guard = env.cb.usage.guard(0.81,{monthlyAllowance:12,checksPerOccurrence:3});
  const confirm = {};
  guard.bind(confirm); await turn();
  assert.equal(confirm.disabled,true);
  const copy = JSON.stringify(guard.node);
  assert.match(copy,/12 checks per month/);
  assert.match(copy,/3 checks each time/);
  assert.match(copy,/\$0\.81/);
  assert.match(copy,/recurring paid checks/);
  assert.match(copy,/future overage/);
  assert.match(copy,/compute/);
  await assert.rejects(guard.verify(),/approve/i);
  inputs[0].checked = true; inputs[0].change();
  assert.equal(confirm.disabled,false);
  await guard.verify();
});

test('a legacy paid schedule states its calendar frequency and explains its lack of a project allowance', async () => {
  const env = await tab(({url}) => usageReply(url, 1, 20, 40));
  billingDialog(env);
  const guard = env.cb.usage.guard(0.1,{frequency:'weekly',paidRuns:2});
  await turn();
  const copy=JSON.stringify(guard.node);
  assert.match(copy,/4–5 times per calendar month/);
  assert.match(copy,/2 paid Actor runs each time/);
  assert.match(copy,/no project monthly allowance/i);
});

test('a known zero limit or a quote above the entire limit blocks even when spending cannot be read', async () => {
  let limit=0;
  const env=await tab(({url})=>{
    if (url.endsWith('/limits')) return response({data:{limits:{maxMonthlyUsageUsd:limit}}});
    if (url.endsWith('/usage/monthly')) return response({error:{type:'insufficient-permissions'}},403);
    return usageReply(url,0,15,limit);
  });
  vm.runInContext(source('usage.js'),env.context);
  const zero=await env.cb.usage.read();
  assert.equal(zero.used,null); assert.equal(zero.room,0);
  assert.equal(env.cb.usage.decision(zero,0.01).kind,'blocked');
  assert.doesNotMatch(env.cb.usage.compact(zero), /Unavailable used/);
  limit=1;
  const small=await env.cb.usage.read(true);
  assert.equal(small.room,null); assert.equal(env.cb.usage.decision(small,2).kind,'blocked');
  assert.equal(env.cb.usage.decision(small,0.5).kind,'unknown');
});
