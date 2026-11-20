'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createHash, randomBytes} = require('node:crypto');
const {mkdtempSync, readFileSync, rmSync} = require('node:fs');
const vm = require('node:vm');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

const origin = 'https://citebase.example';
const tokenUrl = 'https://console-backend.apify.com/oauth/apps/token';
const dir = mkdtempSync(path.join(os.tmpdir(), 'citebase-session-test-'));
const root = path.resolve(__dirname, '../..');
execFileSync(process.env.PYTHON || 'python3', ['scripts/build_site.py', '--site', origin, '--out', dir], {cwd: root});
const handle = require(path.join(dir, 'api/session.js'));
const relay = require(path.join(dir, 'api/actor.js'));
process.on('exit', () => rmSync(dir, {force: true, recursive: true}));
process.env.CITEBASE_SESSION_KEY = randomBytes(32).toString('base64');

function browser() {
  const cookies = new Map();
  return {cookies, async request(action, fields = {}, overrides = {}) {
    const headers = {host: new URL(origin).host, origin, cookie: [...cookies].map(([k, v]) => k + '=' + v).join('; '),
      'content-type': 'application/json', 'x-citebase-session': '1', ...overrides.headers};
    const req = {method: action === 'start' ? 'GET' : 'POST', url: '/api/session/' + (action === 'start' ? '?start' : ''),
      body: {action, ...fields}, ...overrides, headers};
    const res = {headers: {}, setHeader(k, v) { this.headers[k.toLowerCase()] = v; }, end(s) { this.text = s || ''; }};
    await (req.url === '/api/actor/' ? relay : handle)(req, res);
    let set = res.headers['set-cookie'] || [];
    if (!Array.isArray(set)) set = [set];
    for (const cookie of set) {
      const [,name,value] = /^([^=]+)=([^;]*)/.exec(cookie);
      if (cookie.includes('Max-Age=0')) cookies.delete(name); else cookies.set(name, value);
    }
    assert.match(res.headers['cache-control'], /no-store/);
    return {status: res.statusCode, headers:res.headers, cookies: set, location: res.headers.location, json: res.text ? JSON.parse(res.text) : {}};
  }};
}

test('the Google authorization callback can use only a valid current Citebase session', async () => {
  const tab=browser();
  const request = () => ({headers:{cookie:[...tab.cookies].map(([key,value]) => key+'='+value).join('; ')}});
  assert.equal(handle.googleCallbackCredential(request()),null);
  await login(tab);
  assert.equal(handle.googleCallbackCredential(request()),'access-one');
  const sessionId=(await tab.request('restore')).json.sessionId;
  await tab.request('logout',{sessionId});
  assert.equal(handle.googleCallbackCredential(request()),null);
});

function provider(impl) {
  global.fetch = async (url, init) => {
    assert.ok([tokenUrl, 'https://api.apify.com/v2/users/me'].includes(url), 'fixed Apify endpoint');
    assert.equal(init.redirect, 'error');
    const [status, data] = await impl(url, init);
    return new Response(JSON.stringify(data), {status});
  };
}

async function login(client, answer = {access_token:'access-one', refresh_token:'refresh-one', expires_in:3600}) {
  const start = await client.request('start');
  assert.equal(start.status, 302);
  const auth = new URL(start.location);
  assert.equal(auth.origin + auth.pathname, 'https://console.apify.com/authorize/oauth');
  assert.equal(auth.searchParams.get('redirect_uri'), origin + '/app/');
  assert.equal(auth.searchParams.get('client_id'), origin + '/oauth-client.json');
  assert.equal(auth.searchParams.get('code_challenge_method'), 'S256');
  const state = auth.searchParams.get('state');
  assert.ok(state.length >= 22);
  let exchanges = 0;
  provider((url, init) => {
    assert.equal(url, tokenUrl);
    const body = new URLSearchParams(init.body);
    assert.equal(body.get('grant_type'), 'authorization_code');
    assert.equal(body.get('redirect_uri'), origin + '/app/');
    assert.equal(createHash('sha256').update(body.get('code_verifier')).digest('base64url'), auth.searchParams.get('code_challenge'));
    assert.equal(body.get('code'), 'one-time-code');
    exchanges++;
    return [200, answer];
  });
  assert.equal((await client.request('exchange', {code:'one-time-code', state:'wrong-state'})).status, 400);
  assert.equal(exchanges, 0);
  const back = await client.request('exchange', {code:'one-time-code', state});
  assert.equal(exchanges, 1);
  assert.equal(back.status, 200);
  assert.equal(back.json.signedIn, true);
  assert.equal(back.json.accessToken, answer.access_token);
  for (const cookie of [...start.cookies, ...back.cookies]) {
    assert.match(cookie, /^__Host-/);
    for (const flag of ['Path=/', 'HttpOnly', 'Secure', 'SameSite=Lax']) assert.ok(cookie.includes(flag), flag);
    assert.doesNotMatch(cookie, /Domain=|access-one|refresh-one/);
  }
  assert.ok(back.cookies.some(cookie => /Max-Age=[1-9]\d{5,}/.test(cookie)));
  assert.equal(JSON.stringify(back.json).includes('refresh-one'), false);
  assert.equal((await client.request('exchange', {code:'one-time-code', state})).status, 400);
  return back.json;
}

test('one click opens Apify, a browser restart restores the session and sign-out removes it', async () => {
  const tab = browser();
  assert.deepEqual((await tab.request('status')).json, {signedIn:false});
  const first = await login(tab);
  const restarted = browser();
  for (const [name, value] of tab.cookies) restarted.cookies.set(name, value);
  provider(() => { throw Error('Restoring a current session should not contact Apify'); });
  assert.deepEqual((await restarted.request('status')).json, {signedIn:true});
  assert.deepEqual((await restarted.request('restore')).json, first);
  assert.equal((await restarted.request('start')).location, '/app/');
  assert.equal((await restarted.request('logout', {sessionId:first.sessionId})).status, 200);
  assert.deepEqual((await restarted.request('restore')).json, {signedIn:false});
  assert.deepEqual((await restarted.request('restore', {legacyAccess:'old-tab', legacyRefresh:'old-refresh'})).json, {signedIn:false});
});

test('the authenticated Actor relay pins its upstream and preserves meaningful results without replaying a write', async () => {
  const tab = browser(), session = await login(tab);
  const body = {tool:'save_results', arguments:{project:'example', create_only:true}};
  let calls = 0;
  const send = (overrides = {}) => tab.request('relay', {}, {
    method:'POST', url:'/api/actor/', body, ...overrides, headers:{authorization:'Bearer ' + session.accessToken,
      'x-apify-authorization':'untrusted', 'x-citebase-authorization':'another-account', ...overrides.headers}});
  global.fetch = async (url, init) => {
    calls++;
    assert.equal(url, 'https://khadinakbar--citebase.apify.actor/run');
    assert.equal(init.method,'POST'); assert.equal(init.redirect,'error');
    assert.equal(init.headers['X-Apify-Authorization'],'Bearer access-one');
    assert.equal(init.headers['X-Citebase-Authorization'],'Bearer access-one');
    assert.ok(!('Cookie' in init.headers) && !('Origin' in init.headers));
    assert.deepEqual(JSON.parse(init.body),body);
    return Response.json({ok:true,result:{created:true}}, {status:201, headers:{'Set-Cookie':'foreign=1'}});
  };
  const initial = await send();
  assert.deepEqual(initial.json,{ok:true,result:{created:true}}); assert.equal(initial.status,201);
  assert.deepEqual(initial.cookies,[]);
  for (const [headers,status] of [[{origin:'https://foreign.test'},403],[{'x-citebase-session':''},403],
    [{'content-type':'text/plain'},403],[{cookie:''},401],[{authorization:'Bearer different-user'},401],[{authorization:''},401]]) {
    const rejected = await send({headers});
    assert.equal(rejected.status,status); if (status === 401) assert.equal(rejected.headers['x-citebase-not-dispatched'],'1');
  }
  assert.equal((await send({method:'GET'})).status,405);
  assert.equal((await send({body:{...body,url:'https://foreign.test/run',headers:{Authorization:'foreign'}}})).status,400);
  assert.equal((await send({body:'['})).status,400);
  assert.equal((await send({body:{tool:'next_steps',arguments:{pad:'é'.repeat(1024*1024)}}})).status,413);
  assert.equal((await send({headers:{'content-length':String(2*1024*1024 + 1)}})).status,413);
  assert.equal(calls,1);
  for (const status of [400,401,402,429,503]) {
    global.fetch = async () => { calls++; return Response.json({error:{type:'fixture',message:'Actor reply'}},
      {status,headers:{'X-Citebase-Not-Dispatched':'1', 'Set-Cookie':'foreign=1'}}); };
    const out = await send();
    assert.equal(out.status,status); assert.deepEqual(out.json,{error:{type:'fixture',message:'Actor reply'}});
    assert.equal(out.headers['x-citebase-not-dispatched'],undefined); assert.deepEqual(out.cookies,[]);
  }
  global.fetch = async () => { calls++; throw Error('private fixture upstream detail'); };
  const interrupted = await send();
  assert.equal(interrupted.status,502);
  assert.doesNotMatch(JSON.stringify(interrupted.json), /private fixture upstream detail|access-one/);
  assert.match(JSON.stringify(interrupted.json), /review/i);
  assert.equal(calls,7);
});

test('the Actor relay bounds chunked input and output even with a misleading length, and preserves empty successes', async () => {
  const tab = browser(), session = await login(tab);
  const send = extra => tab.request('relay',{}, {method:'POST',url:'/api/actor/',body:{tool:'get_history',arguments:{}},
    headers:{authorization:'Bearer ' + session.accessToken}, ...extra});
  let calls = 0;
  global.fetch = async () => { calls++; return new Response(null,{status:204}); };
  const chunked = await send({readable:true, readableEnded:false,
    async *[Symbol.asyncIterator]() { yield Buffer.from('{"tool":"get_history"}'); yield Buffer.alloc(2 * 1024 * 1024, ' '); }});
  assert.equal(chunked.status,413); assert.equal(calls,0);
  assert.equal((await send()).status,204); assert.equal(calls,1);
  for (const length of [undefined, '256', '90000000']) {
    let cancelled = false, emitted = 0;
    global.fetch = async () => {
      calls++;
      const body = new ReadableStream({pull(controller) { if (++emitted <= 15) controller.enqueue(new Uint8Array(1024 * 1024)); else controller.close(); },
        cancel() { cancelled = true; }});
      return new Response(body,{status:200, headers:length ? {'Content-Length':length} : {}});
    };
    const tooLarge = await send();
    assert.equal(tooLarge.status,502); assert.match(tooLarge.json.error,/narrow/i); assert.match(tooLarge.json.error,/Activity/);
    assert.equal(cancelled,true); assert.ok(emitted < 15); assert.equal(tooLarge.headers['x-citebase-not-dispatched'],undefined);
  }
  assert.equal(calls,4);
});

test('a rotating refresh cannot be duplicated or mixed with another account', async () => {
  const tab = browser(), first = await login(tab);
  let count = 0;
  provider((url, init) => {
    const body = new URLSearchParams(init.body);
    assert.equal(url, tokenUrl); assert.equal(body.get('grant_type'), 'refresh_token');
    assert.equal(body.get('refresh_token'), 'refresh-one');
    count++;
    return [200, {access_token:'access-two', refresh_token:'refresh-two', expires_in:3600}];
  });
  assert.equal((await tab.request('refresh', {sessionId:'another-account', version:first.version})).status, 409);
  const fresh = (await tab.request('refresh', {sessionId:first.sessionId, version:first.version})).json;
  assert.equal(fresh.accessToken, 'access-two');
  assert.equal(fresh.sessionId, first.sessionId);
  assert.deepEqual((await tab.request('refresh', {sessionId:first.sessionId, version:first.version})).json, fresh);
  assert.equal(count, 1);
  assert.equal((await tab.request('logout', {sessionId:'stale-tab'})).status, 409);
  assert.equal((await tab.request('restore', {legacyAccess:'foreign', legacyRefresh:'foreign-refresh'})).json.accessToken, 'access-two');
});

test('interrupted renewal keeps the session and an expired grant clears it', async () => {
  const tab = browser(), first = await login(tab);
  const fields = {sessionId:first.sessionId, version:first.version};
  provider(() => [503, {error:'temporarily_unavailable'}]);
  const failure = await tab.request('refresh', fields);
  assert.equal(failure.status, 503); assert.deepEqual(failure.cookies, []);
  assert.equal((await tab.request('restore')).json.accessToken, 'access-one');
  provider(() => [400, {error:'invalid_grant'}]);
  assert.deepEqual((await tab.request('refresh', fields)).json, {signedIn:false});
  assert.deepEqual((await tab.request('status')).json, {signedIn:false});
});

test('only trusted same-origin requests can read tokens, migrate previous tabs or end sessions', async () => {
  const tab = browser(), first = await login(tab);
  for (const action of ['restore', 'refresh', 'logout', 'exchange']) {
    for (const headers of [{origin:'https://elsewhere.example'}, {'x-citebase-session':''}, {'content-type':'text/plain'}]) {
      const res = await tab.request(action, {sessionId:first.sessionId, version:first.version}, {headers});
      assert.equal(res.status, 403);
      assert.equal(res.json.accessToken, undefined);
      assert.deepEqual(res.cookies, []);
    }
  }
  const name = [...tab.cookies.keys()].find(key => key.includes('session'));
  const original = tab.cookies.get(name);
  tab.cookies.set(name, (original[0] === 'A' ? 'B' : 'A') + original.slice(1));
  assert.deepEqual((await tab.request('restore')).json, {signedIn:false});
});

test('migration validates previous credentials with Apify and never combines unrelated tokens', async () => {
  const tab = browser();
  let calls = [];
  provider((url, init) => {
    calls.push(url);
    assert.equal(new URLSearchParams(init.body).get('refresh_token'), 'legacy-owner');
    return [200, {access_token:'issued-to-owner', expires_in:3600}];
  });
  const res = await tab.request('restore', {legacyAccess:'unrelated-access', legacyRefresh:'legacy-owner'});
  assert.equal(res.json.accessToken, 'issued-to-owner');
  assert.deepEqual(calls, [tokenUrl]);
  const noRefresh = browser();
  provider((url, init) => {
    assert.equal(url, 'https://api.apify.com/v2/users/me');
    assert.equal(init.headers.Authorization, 'Bearer old-access');
    return [200, {data:{id:'test-owner'}}];
  });
  const accessOnly = await noRefresh.request('restore', {legacyAccess:'old-access'});
  assert.equal(accessOnly.json.accessToken, 'old-access');
  const expiredRefresh = browser();
  provider(url => url === tokenUrl ? [400,{error:'invalid_grant'}] : [200,{data:{id:'legacy-user'}}]);
  assert.equal((await expiredRefresh.request('restore', {legacyAccess:'still-active', legacyRefresh:'expired'})).json.accessToken, 'still-active');
  const active = (await expiredRefresh.request('restore')).json;
  provider(() => { throw Error('An independently verified access token must not acquire an unrelated refresh grant'); });
  assert.deepEqual((await expiredRefresh.request('refresh', {sessionId:active.sessionId, version:active.version})).json, {signedIn:false});
});

test('restore refreshes an expiring token, and the 90-day session lifetime is absolute', async () => {
  const current = Date.now, start = current();
  const tab = browser(), noRefresh = browser();
  try {
    await login(tab, {access_token:'access-one', refresh_token:'refresh-one', expires_in:60});
    await login(noRefresh, {access_token:'access-one', expires_in:60});
    Date.now = () => start + 65_000;
    provider(() => [200,{access_token:'access-two',refresh_token:'refresh-two',expires_in:3600}]);
    assert.deepEqual((await tab.request('status')).json, {signedIn:true});
    assert.equal((await tab.request('restore')).json.accessToken, 'access-two');
    assert.deepEqual((await noRefresh.request('status')).json, {signedIn:false});
    Date.now = () => start + 91 * 86400_000;
    provider(() => { throw Error('An expired browser session cannot restore or rotate'); });
    assert.deepEqual((await tab.request('restore')).json, {signedIn:false});
  } finally { Date.now = current; }
});

test('a delayed refresh arriving after sign-out or switching accounts cannot revive the old account', async () => {
  for (const switchAccount of [false,true]) {
    const tab = browser(), first = await login(tab);
    let resolve;
    provider(() => new Promise(yes => { resolve = yes; }));
    const pending = tab.request('refresh', {sessionId:first.sessionId, version:first.version});
    await tab.request('logout', {sessionId:first.sessionId});
    const second = switchAccount ? await login(tab, {access_token:'other', refresh_token:'other-refresh', expires_in:3600}) : null;
    resolve([200,{access_token:'late',refresh_token:'late-refresh',expires_in:3600}]);
    await pending;
    assert.deepEqual((await tab.request('restore')).json, second || {signedIn:false});
  }
});

test('a missing deployment key is retryable and rotating it makes old cookies unusable', async () => {
  const tab = browser(), saved = process.env.CITEBASE_SESSION_KEY;
  try {
    await login(tab);
    delete process.env.CITEBASE_SESSION_KEY;
    assert.equal((await tab.request('restore')).status, 503);
    process.env.CITEBASE_SESSION_KEY = randomBytes(32).toString('base64');
    assert.deepEqual((await tab.request('restore')).json, {signedIn:false});
  } finally { process.env.CITEBASE_SESSION_KEY = saved; }
});

test('a write or foreground check confirms the current cookie owner without migrating a previous tab', async () => {
  const tab = browser(), old = await login(tab);
  provider(() => { throw Error('A current cookie verification must not call Apify'); });
  assert.deepEqual((await tab.request('verify', {sessionId:old.sessionId})).json, old);
  await tab.request('logout', {sessionId:old.sessionId});
  assert.deepEqual((await tab.request('verify', {sessionId:old.sessionId,legacyAccess:'old-account'})).json, {signedIn:false});
  const current = await login(tab, {access_token:'different-user', expires_in:3600});
  const denied = await tab.request('verify', {sessionId:old.sessionId});
  assert.equal(denied.status, 409); assert.equal(denied.json.accessToken, undefined);
  assert.deepEqual((await tab.request('verify', {sessionId:current.sessionId})).json, current);
});

test('without Web Locks, a late rejected rotation adopts the newer successful browser cookie', async () => {
  const tab = browser(), first = await login(tab);
  const fields = {sessionId:first.sessionId, version:first.version};
  const notifications = [];
  function client() {
    const window = {addEventListener() {}};
    vm.runInNewContext(readFileSync(path.join(root,'site/app/session.js'),'utf8'), {
      window, navigator:{}, sessionStorage:{getItem(){return ''},removeItem(){}},
      localStorage:{setItem(k,v){ notifications.push([k,v]); },removeItem(){}},
      fetch:async (url, init) => {
        const {action,...input} = JSON.parse(init.body);
        const r = await tab.request(action, input);
        return {ok:r.status === 200, status:r.status, json:async () => r.json,
          headers:{get:name => r.headers[name.toLowerCase()]}};
      }
    });
    return window.CitebaseSession;
  }
  let calls = 0, finishLate;
  provider(() => ++calls === 1 ? new Promise(resolve => { finishLate = resolve; })
    : [200,{access_token:'winner',refresh_token:'rotated',expires_in:3600}]);
  const late = client().request('refresh', fields);
  const good = await client().request('refresh', fields);
  assert.equal(good.accessToken, 'winner');
  const beforeLate = notifications.length;
  finishLate([400,{error:'invalid_grant'}]);
  assert.equal((await late).accessToken, 'winner');
  assert.equal((await tab.request('restore')).json.accessToken, 'winner');
  assert.equal(calls, 2);
  assert.equal(notifications.length, beforeLate, 'a rejected old generation must not broadcast sign-out');
  // A genuine rejection of the current generation asks for consent again without retrying the revoked credential.
  let rejected = 0;
  provider(() => { rejected++; return [400,{error:'invalid_grant'}]; });
  assert.equal((await client().request('refresh', {sessionId:good.sessionId, version:good.version})).signedIn, false);
  assert.deepEqual((await tab.request('restore')).json, {signedIn:false});
  assert.match((await tab.request('start')).location, /^https:\/\/console\.apify\.com\/authorize\/oauth\?/);
  assert.equal(rejected, 1);
});
