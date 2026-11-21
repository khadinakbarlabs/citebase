'use strict';
const {actorCredential, trustedPost} = require('./session.js');
const {accountBalance} = require('./_lib/balance.js');

const ACTOR = 'https://khadinakbar--citebase.apify.actor/run';
const MAX_BODY = 2 * 1024 * 1024;  // Same wire-size limit as connector/server.py.
const MAX_REPLY = 4 * 1024 * 1024;  // Below Vercel's 4.5 MB buffered response limit.
const UPSTREAM_TIMEOUT = 290_000;  // Leave time to return a useful response within the 300-second function.

function reply(res, status, data) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(data));
}
function fail(res, status, message) { return reply(res, status, {ok:false, error:message}); }

async function boundedBytes(stream, limit) {
  const chunks = [];
  let size = 0;
  for await (const part of stream) {
    size += typeof part === 'string' ? Buffer.byteLength(part) : part.byteLength;
    if (size > limit) return null;
    chunks.push(Buffer.isBuffer(part) ? part : Buffer.from(part));
  }
  return Buffer.concat(chunks, size);
}

async function requestBody(req) {
  const length = req.headers['content-length'];
  if (length != null && (!/^\d+$/.test(length) || Number(length) > MAX_BODY)) return {tooLarge:true};
  let body;
  if (!req.readableEnded && req.readable !== false && typeof req[Symbol.asyncIterator] === 'function') {
    // Keep the client socket open long enough to return a useful 413 for a chunked upload.
    const stream = typeof req.iterator === 'function' ? req.iterator({destroyOnReturn:false}) : req;
    body = await boundedBytes(stream, MAX_BODY);
    if (!body) { req.resume?.(); return {tooLarge:true}; }
  } else if (req.readableEnded && typeof req.read === 'function') {
    body = req.read(); // Vercel's Node helpers replay the original, buffered body through read().
  }
  if (body == null) body = req.body;
  if (Buffer.isBuffer(body)) {
    if (body.length > MAX_BODY) return {tooLarge:true};
    body = body.toString('utf8');
  }
  const raw = typeof body === 'string' ? body : JSON.stringify(body);
  if (!raw) return {};
  if (Buffer.byteLength(raw) > MAX_BODY) return {tooLarge:true};
  const data = typeof body === 'string' ? JSON.parse(body) : body;
  if (!data || typeof data !== 'object' || Array.isArray(data) || typeof data.tool !== 'string'
      || !/^[a-z][a-z0-9_]{0,79}$/.test(data.tool) || Object.keys(data).some(k => k !== 'tool' && k !== 'arguments')
      || (data.arguments !== undefined && (!data.arguments || typeof data.arguments !== 'object' || Array.isArray(data.arguments)))) return {};
  return {raw, data};
}

class StorageReviewError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const storageUnavailable = () => new StorageReviewError(409, 'Citebase could not identify one project store. Open Apify Storage to review its sharing.');
async function projectStorage(tool, args, api) {
  const change = tool === 'dashboard_restrict_storage';
  const allowed = change ? ['project', 'store_id', 'confirmed'] : ['project'];
  if ((!change && tool !== 'dashboard_storage_review') || !args || typeof args.project !== 'string' ||
      !/^[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]$/.test(args.project) ||
      Object.keys(args).some(key => !allowed.includes(key)) || (change && (args.confirmed !== true ||
      typeof args.store_id !== 'string' || !/^[a-zA-Z0-9]{5,80}$/.test(args.store_id)))) {
    throw new StorageReviewError(400, 'Review the saved project and confirm the exact store to change.');
  }
  const me = await api('users/me');
  if (!me?.id || typeof me.username !== 'string' || !/^[a-zA-Z0-9_.-]+$/.test(me.username)) throw storageUnavailable();
  const names = ['citebase-projects', 'citebase-projects-v2-me1rsyfkhb634kvyr'];
  const stores = await Promise.all(names.map(async name => {
    const store = await api('key-value-stores/' + me.username + '~' + name);
    if (!store) return null;
    if (store.userId !== me.id || store.name !== name || !/^[a-zA-Z0-9]{5,80}$/.test(store.id)) throw storageUnavailable();
    const meta = await api('key-value-stores/' + store.id + '/records/p.' + args.project + '.meta');
    return meta?.project === args.project ? store : null;
  }));
  const matches = stores.filter(Boolean);
  if (matches.length !== 1) throw storageUnavailable();
  const store = matches[0];
  const view = access => ({id:store.id, name:store.name, access});
  if (!change) return view(store.generalAccess);
  if (store.id !== args.store_id) throw storageUnavailable();
  if (store.generalAccess === 'RESTRICTED') return view('RESTRICTED');
  if (store.generalAccess !== 'FOLLOW_USER_SETTING') {
    throw new StorageReviewError(409, 'This store has an explicit sharing policy. Review it in Apify Console.');
  }
  const path = 'key-value-stores/' + store.id;
  await api(path, {method:'PUT', body:{generalAccess:'RESTRICTED'}});
  const saved = await api(path);
  if (saved?.id !== store.id || saved.userId !== me.id || saved.name !== store.name || saved.generalAccess !== 'RESTRICTED') {
    throw new StorageReviewError(409, 'Review the current store access in Apify before trying again.');
  }
  return view(saved.generalAccess);
}

async function apifyStorage(access, path, options = {}) {
  const response = await fetch('https://api.apify.com/v2/' + path, {
    method:options.method || 'GET', redirect:'error', cache:'no-store', signal:AbortSignal.timeout(12000),
    headers:{Authorization:'Bearer ' + access, 'Content-Type':'application/json', Accept:'application/json'},
    body:options.body ? JSON.stringify(options.body) : undefined
  });
  if (response.status === 404 && !options.method) return null;
  if (!response.ok) throw new StorageReviewError(response.status === 403 ? 403 : 502,
    'Citebase could not verify this store in your Apify account. Review its access in Apify Storage.');
  if (response.status === 204 || (options.method === 'PUT' && path.includes('/records/'))) return null;
  const value = await response.json();
  return path.includes('/records/') ? value : value.data;
}

module.exports = async function actorHandler(req, res) {
  res.setHeader('Cache-Control','private, no-store');
  res.setHeader('Vercel-CDN-Cache-Control','no-store');
  res.setHeader('Vary','Cookie, Origin, Authorization');
  res.setHeader('X-Content-Type-Options','nosniff');
  if (req.method !== 'POST') { res.setHeader('Allow','POST'); return fail(res, 405, 'Use POST to call Citebase.'); }
  if (!trustedPost(req)) return fail(res, 403, 'Open the Citebase dashboard to continue.');
  let access;
  try { access = actorCredential(req); }
  catch { return fail(res, 503, 'Citebase sign-in is temporarily unavailable.'); }
  if (!access) {
    res.setHeader('X-Citebase-Not-Dispatched','1');
    return fail(res, 401, 'Check your current Citebase sign-in and try again.');
  }
  let body;
  try { body = await requestBody(req); } catch { body = {}; }
  if (body.tooLarge) return fail(res, 413, 'Request is too large (limit 2 MB). Send less data.');
  if (!body.raw) return fail(res, 400, 'Send a Citebase tool and its arguments as JSON.');
  const balanceAction = ['dashboard_balance_read','dashboard_balance_save'].includes(body.data.tool);
  if (balanceAction || ['dashboard_storage_review', 'dashboard_restrict_storage'].includes(body.data.tool)) {
    try {
      const operation = balanceAction ? accountBalance : projectStorage;
      const result = await operation(body.data.tool, body.data.arguments, (path, options) => apifyStorage(access, path, options));
      return reply(res, 200, {ok:true, result});
    } catch (error) {
      if (error instanceof StorageReviewError) return fail(res, error.status, error.message);
      if (balanceAction) return fail(res, 400, 'Could not verify the billing balance. Check the amount, billing dates and private storage in your Apify account.');
      return fail(res, 502, 'Could not verify project storage. Review its current sharing in Apify before retrying.');
    }
  }
  const credential = 'Bearer ' + access;
  try {
    const upstream = await fetch(ACTOR, {method:'POST', redirect:'error', cache:'no-store',
      signal:AbortSignal.timeout(UPSTREAM_TIMEOUT), headers:{'Content-Type':'application/json', Accept:'application/json',
        'X-Apify-Authorization':credential, 'X-Citebase-Authorization':credential}, body:body.raw});
    if (upstream.status >= 300 && upstream.status < 400) throw Error('Unexpected redirect');
    if (upstream.status === 204) { res.statusCode = 204; return res.end(); }
    let bytes;
    if (Number(upstream.headers.get('content-length')) > MAX_REPLY) await upstream.body?.cancel();
    else bytes = upstream.body ? await boundedBytes(upstream.body, MAX_REPLY) : Buffer.alloc(0);
    const errorStatus = upstream.ok ? 502 : upstream.status;
    if (!bytes) return fail(res, errorStatus, 'The reply is too large to display. Narrow the project or date range. Review Activity before repeating a change.');
    try { JSON.parse(bytes.toString('utf8')); }
    catch { return fail(res, errorStatus, 'Citebase returned an unreadable response. Review Activity before repeating a change.'); }
    res.statusCode = upstream.status;
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    return res.end(bytes);
  } catch (error) {
    return fail(res, error?.name === 'TimeoutError' ? 504 : 502, 'Could not confirm the Citebase response. Review Activity before repeating a change.');
  }
};
module.exports.projectStorage = projectStorage;
module.exports.apifyStorage = apifyStorage;
