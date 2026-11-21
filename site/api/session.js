'use strict';
const {createCipheriv, createDecipheriv, createHash, randomBytes, timingSafeEqual} = require('node:crypto');

// The website build supplies its public OAuth identity. The encryption key comes only from the runtime.
const config = /* CITEBASE_OAUTH */ null;
const AUTHORIZE = 'https://console.apify.com/authorize/oauth';
const TOKEN = 'https://console-backend.apify.com/oauth/apps/token';
const ME = 'https://api.apify.com/v2/users/me';
const LIFETIME = 90 * 24 * 60 * 60;
const FLOW_LIFETIME = 10 * 60;
const now = () => Math.floor(Date.now() / 1000);
const nonce = size => randomBytes(size).toString('base64url');

function key() {
  const value = (process.env.CITEBASE_SESSION_KEY || '').trim();
  if (!/^[A-Za-z0-9+/]{43}=$/.test(value)) throw Error('Session configuration unavailable');
  return Buffer.from(value, 'base64');
}

function encrypted(kind, value) {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key(), iv);
  cipher.setAAD(Buffer.from(config.origin + '|' + config.clientId + '|' + kind));
  const body = Buffer.concat([cipher.update(JSON.stringify(value), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), body]).toString('base64url');
}

function opened(kind, raw) {
  if (!raw || raw.length > 3800 || !/^[\w-]+$/.test(raw)) return null;
  try {
    const bytes = Buffer.from(raw, 'base64url');
    const cipher = createDecipheriv('aes-256-gcm', key(), bytes.subarray(0, 12));
    cipher.setAuthTag(bytes.subarray(12, 28));
    cipher.setAAD(Buffer.from(config.origin + '|' + config.clientId + '|' + kind));
    const value = JSON.parse(Buffer.concat([cipher.update(bytes.subarray(28)), cipher.final()]).toString('utf8'));
    return value.until > now() ? value : null;
  } catch { return null; }
}

function cookieName(kind) {
  return (config.origin.startsWith('https://') ? '__Host-cb_' : 'cb_dev_') + kind;
}
function readCookie(req, kind) {
  const prefix = cookieName(kind) + '=';
  const matches = (req.headers.cookie || '').split(';').map(part => part.trim()).filter(part => part.startsWith(prefix));
  return matches.length === 1 ? matches[0].slice(prefix.length) : '';
}
function cookie(kind, value, seconds) {
  const secure = config.origin.startsWith('https://') ? '; Secure' : '';
  return cookieName(kind) + '=' + value + '; Path=/; HttpOnly; SameSite=Lax' + secure + '; Max-Age=' + Math.max(0, seconds);
}
function activeId(req) {
  const id = readCookie(req, 'login');
  return /^[A-Za-z0-9_-]{22}$/.test(id) ? id : null;
}
function rejectedCookie(session) { return 'rejected_' + session.id + '_' + session.version; }
function rejectGeneration(res, session) {
  // Another tab may already have rotated the same grant. Mark only the rejected generation.
  // Never delete a session or binding using an old response.
  res.setHeader('Set-Cookie', cookie(rejectedCookie(session), '1', session.until - now()));
  res.setHeader('X-Citebase-Session-Recheck', '1');
}
function clearSession(res, id, explicit = false, previous) {
  // Older tabs may still carry pre-upgrade credentials. They must not silently undo a sign-out.
  const cookies = [cookie('migrated', '1', LIFETIME)];
  if (id) cookies.push(cookie('session_' + id, '', 0));
  if (previous) cookies.push(cookie(rejectedCookie(previous), '', 0));
  if (explicit) cookies.push(cookie('login', '', 0), cookie('flow', '', 0));
  res.setHeader('Set-Cookie', cookies);
}
function json(res, status, data) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(data));
}
function redirect(res, destination) {
  res.statusCode = 302;
  res.setHeader('Location', destination);
  res.end();
}
function usable(value, max = 4096) {
  return typeof value === 'string' && value.length > 0 && value.length <= max && !/[\s\x00-\x1f\x7f]/.test(value);
}
function sameSecret(left, right, max) {
  if (!usable(right, max) || typeof left !== 'string') return false;
  const a = Buffer.from(left), b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}
function needsRefresh(session) {
  return session.expires !== null && session.expires <= now() + 5;
}
async function grant(parameters) {
  const response = await fetch(TOKEN, {method:'POST', redirect:'error', signal:AbortSignal.timeout(12000),
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({...parameters, client_id:config.clientId}).toString()});
  const data = await response.json();
  if ([400, 401].includes(response.status) && data.error === 'invalid_grant') return null;
  if (!response.ok || !usable(data.access_token) || (data.refresh_token && !usable(data.refresh_token))) {
    throw Error('Apify sign-in unavailable');
  }
  return data;
}
async function legacyGrant(body) {
  if (usable(body.legacyRefresh)) {
    const result = await grant({grant_type:'refresh_token', refresh_token:body.legacyRefresh});
    // Associate an access token only with the refresh grant that produced it.
    if (result) return {...result, refresh_token:result.refresh_token || body.legacyRefresh};
    // The prior access token can still be valid after its refresh grant was revoked.
    // Validate it independently and leave it access-only.
  }
  if (!usable(body.legacyAccess)) return null;
  const me = await fetch(ME, {headers:{Authorization:'Bearer ' + body.legacyAccess}, redirect:'error', signal:AbortSignal.timeout(12000)});
  if (me.status === 401 || me.status === 403) return null;
  if (!me.ok || !(await me.json()).data?.id) throw Error('Apify sign-in unavailable');
  return {access_token:body.legacyAccess};
}
function issue(res, tokens, previous, replaced) {
  const rawExpiry = Number(tokens.expires_in);
  const session = {id:previous ? previous.id : nonce(16), version:previous ? previous.version + 1 : 1,
    until:previous ? previous.until : now() + LIFETIME,
    access:tokens.access_token, refresh:tokens.refresh_token || previous?.refresh || '',
    expires:tokens.expires_in != null && Number.isFinite(rawExpiry) && rawExpiry >= 0 ? now() + rawExpiry : null};
  const blob = encrypted('session', session);
  if (blob.length > 3800) throw Error('Session exceeds browser cookie size');
  // Refresh responses can arrive after a sign-out or account switch. Only a new sign-in sets
  // the active browser ID. A late rotation can only update its own account-scoped cookie.
  const cookies = [cookie('session_' + session.id, blob, session.until - now())];
  if (!previous) cookies.push(cookie('login', session.id, LIFETIME), cookie('flow', '', 0), cookie('migrated', '1', LIFETIME));
  if (replaced) cookies.push(cookie('session_' + replaced.id, '', 0), cookie(rejectedCookie(replaced), '', 0));
  res.setHeader('Set-Cookie', cookies);
  return session;
}
function sessionReply(res, session, action, migrated = false) {
  if (!session) return json(res, 200, {signedIn:false});
  const info = action === 'status' ? {signedIn:true} :
    {signedIn:true, accessToken:session.access, sessionId:session.id, version:session.version,
      expiresAt:session.expires, sessionUntil:session.until, canRefresh:Boolean(session.refresh)};
  if (migrated) { info.migrated = true; info.sessionId = session.id; }
  return json(res, 200, info);
}
function start(req, res, session) {
  if (req.headers.host !== new URL(config.origin).host) return redirect(res, config.origin + '/api/session/?start');
  if (session && !needsRefresh(session)) return redirect(res, '/app/');
  if (session && session.refresh) return redirect(res, '/app/?signin=1');
  const flow = {verifier:nonce(48), state:nonce(24), until:now() + FLOW_LIFETIME};
  res.setHeader('Set-Cookie', cookie('flow', encrypted('flow', flow), FLOW_LIFETIME));
  const url = new URL(AUTHORIZE);
  url.search = new URLSearchParams({client_id:config.clientId, redirect_uri:config.redirectUri, response_type:'code',
    scope:'full_api_access', state:flow.state, code_challenge_method:'S256',
    code_challenge:createHash('sha256').update(flow.verifier).digest('base64url')});
  return redirect(res, url.href);
}

function sessionFor(req) {
  const id = activeId(req);
  const raw = id && readCookie(req, 'session_' + id);
  const prior = opened('session', raw);
  const active = prior && prior.id === id && !readCookie(req, rejectedCookie(prior)) ? prior : null;
  return {id, raw, prior, active};
}
function trustedPost(req) {
  return req.headers.origin === config.origin && req.headers['x-citebase-session'] === '1'
    && /^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] || '');
}

module.exports = async function sessionHandler(req, res) {
  res.setHeader('Cache-Control', 'private, no-store');
  res.setHeader('Vercel-CDN-Cache-Control', 'no-store');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('Vary', 'Cookie, Origin');
  try {
    key();
    const {id, raw, prior, active} = sessionFor(req);
    let session = active;
    if (req.method === 'GET' && new URL(req.url, config.origin).searchParams.has('start')) return start(req, res, session);
    if (req.method !== 'POST') { res.setHeader('Allow', 'GET, POST'); return json(res, 405, {error:'Method unavailable.'}); }
    if (!trustedPost(req)) {
      return json(res, 403, {error:'Use the Citebase website to sign in.'});
    }
    if (Number(req.headers['content-length'] || 0) > 14000) return json(res, 413, {error:'Request too large.'});
    let body;
    try { body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body; } catch {}
    if (!body || typeof body !== 'object' || Array.isArray(body)) return json(res, 400, {error:'Invalid sign-in request.'});
    const action = body.action;
    if (action === 'logout') {
      if (id && body.sessionId !== id) return json(res, 409, {error:'Account changed.'});
      clearSession(res, id, true, prior);
      return sessionReply(res, null);
    }
    if (action === 'exchange' || action === 'cancel') {
      const flow = opened('flow', readCookie(req, 'flow'));
      let verifier;
      if (flow && sameSecret(flow.state, body.state, 256)) verifier = flow.verifier;
      // An already-open authorization page from the previous release used a tab-scoped PKCE pair.
      else if (!flow && !readCookie(req, 'migrated') && usable(body.state, 256)
          && /^[A-Za-z0-9._~-]{43,128}$/.test(body.legacyVerifier || '')) verifier = body.legacyVerifier;
      if (!verifier) return json(res, 400, {error:'Sign-in request expired.'});
      res.setHeader('Set-Cookie', cookie('flow', '', 0));
      if (action === 'cancel') return json(res, 200, {cancelled:true});
      if (!usable(body.code, 2048)) return json(res, 400, {error:'Sign-in code missing.'});
      const tokens = await grant({grant_type:'authorization_code', code:body.code, code_verifier:verifier, redirect_uri:config.redirectUri});
      if (!tokens) return json(res, 400, {error:'Sign-in code expired.'});
      return sessionReply(res, issue(res, tokens, null, prior), action);
    }
    if (!['status', 'restore', 'verify', 'refresh'].includes(action)) return json(res, 400, {error:'Unknown sign-in request.'});
    if ((action === 'verify' || action === 'refresh') && session && session.id !== body.sessionId) {
      return json(res, 409, {error:'Account changed.'});
    }
    if (action === 'refresh' && !Number.isInteger(body.version)) return json(res, 400, {error:'Invalid session version.'});
    if (!session) {
      if (['status', 'restore'].includes(action) && !raw && !readCookie(req, 'migrated') && (body.legacyAccess || body.legacyRefresh)) {
        const tokens = await legacyGrant(body);
        if (tokens) return sessionReply(res, issue(res, tokens), action, true);
        clearSession(res, id);
      }
      return sessionReply(res, null);
    }
    if (needsRefresh(session) || (action === 'refresh' && body.version === session.version)) {
      const tokens = session.refresh ? await grant({grant_type:'refresh_token', refresh_token:session.refresh}) : null;
      if (!tokens) { rejectGeneration(res, session); return sessionReply(res, null); }
      session = issue(res, tokens, session);
    }
    return sessionReply(res, session, action);
  } catch {
    return json(res, 503, {error:'Sign-in is temporarily unavailable. Please try again.'});
  }
};

// Used only by the fixed upstream Actor function. This never refreshes, starts or migrates a session.
module.exports.trustedPost = trustedPost;
// Google redirects from a different origin. Its callback verifies one-time browser state
// and the Apify owner before exchanging a code. Only a live sealed session can finish it.
module.exports.googleCallbackCredential = function (req) {
  key();
  const {active} = sessionFor(req);
  return active && !needsRefresh(active) ? active.access : null;
};
module.exports.actorCredential = function (req) {
  key();
  const {active} = sessionFor(req);
  const supplied = /^Bearer ([^\s]+)$/i.exec(req.headers.authorization || '');
  return active && !needsRefresh(active) && supplied && sameSecret(active.access, supplied[1], 4096) ? active.access : null;
};
