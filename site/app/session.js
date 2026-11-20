/* Shared by the landing page and dashboard. Only the dashboard requests a short-lived access token. */
(function () {
  'use strict';
  const endpoint = '/api/session/';
  const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('citebase-account') : null;
  const listeners = new Set();
  if (channel) channel.onmessage = event => listeners.forEach(listen => listen(event.data || {}));
  else window.addEventListener('storage', event => {
    if (event.key === 'cb.session-event' && event.newValue) listeners.forEach(listen => listen({kind:'check'}));
  });

  function stored(key) { try { return sessionStorage.getItem(key) || ''; } catch { return ''; } }
  function store(key, value) {
    try { if (value == null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value); } catch {}
  }
  function notify(kind, sessionId) {
    if (channel) { channel.postMessage({kind, sessionId}); return; }
    // A one-bit wakeup for browsers without BroadcastChannel. No identity or credential is written.
    try { localStorage.setItem('cb.session-event', '1'); localStorage.removeItem('cb.session-event'); } catch {}
  }
  async function post(body) {
    const response = await fetch(endpoint, {method:'POST', credentials:'same-origin', cache:'no-store', redirect:'error',
      headers:{'Content-Type':'application/json', 'X-Citebase-Session':'1'}, body:JSON.stringify(body)});
    const result = await response.json();
    if (response.status === 409) return {result:{signedIn:false, changed:true}};
    if (!response.ok) throw Error(result.error || 'Could not check your sign-in. Please try again.');
    return {result, recheck:response.headers.get('X-Citebase-Session-Recheck') === '1'};
  }
  async function request(action, fields) {
    async function send() {
      const body = {action, ...fields};
      if (action === 'status' || action === 'restore') {
        const access = stored('cb.t'), refresh = stored('cb.r');
        if (access) body.legacyAccess = access;
        if (refresh) body.legacyRefresh = refresh;
      }
      let reply = await post(body);
      if (reply.recheck) {
        // The browser might have accepted a newer refresh response while this request was in flight.
        // Read back once. A genuinely revoked generation is marked server-side and cannot rotate again.
        reply = await post(action === 'refresh' ? {action:'verify', sessionId:fields.sessionId} : {action, ...fields});
      }
      const result = reply.result;
      if (result.changed) return result;
      if (['status', 'restore', 'exchange', 'logout'].includes(action)) {
        if (result.migrated) store('cb.sid', result.sessionId);
        store('cb.t', null); store('cb.r', null);
      }
      if (action === 'exchange' && result.signedIn) notify('in', result.sessionId);
      if (action === 'logout' || (action === 'refresh' && !result.signedIn)) notify('out', fields.sessionId);
      return result;
    }
    // Rotating refresh tokens are shared by windows. Dispatch only after the previous Set-Cookie is applied.
    return navigator.locks ? navigator.locks.request('citebase-account', send) : send();
  }
  const receiptTtl = 30 * 24 * 60 * 60 * 1000;
  const receiptStates = new Set(['starting', 'uncertain', 'READY', 'RUNNING', 'SUCCEEDED',
    'ABORTING', 'ABORTED', 'TIMING-OUT', 'TIMED-OUT', 'FAILED']);
  async function digest(value) {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)));
    return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
  }
  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object')
      return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
    return value;
  }
  async function researchReceipt(account, project, actor, slot, scope, signedIn) {
    if (!account || !project || !actor || !signedIn()) throw new Error('Sign in to access a run receipt.');
    const [binding, signature] = await Promise.all([digest([account, project, actor, slot]), digest([actor, canonical(scope)])]);
    const key = 'cb.research.' + binding;
    function verify() {
      if (!signedIn()) throw new Error('Sign in to access a run receipt.');
    }
    const read = name => JSON.parse(localStorage.getItem(name) || 'null');
    const terminalKey = job => key + '.' + job;
    function expired(entry) {
      if (!Number.isSafeInteger(entry.expires)) throw new Error('Invalid run receipt.');
      return Date.now() >= entry.expires;
    }
    return {
      key, signature,
      read() {
        verify();
        const pending = read(key);
        if (pending) {
          if (pending.status === 'expired' || !expired(pending)) return pending;
          // Forget the old run details, but retain an opaque marker to prevent a blind paid retry.
          const marker = {status:'expired'};
          localStorage.setItem(key, JSON.stringify(marker));
          return marker;
        }
        const name = terminalKey(signature);
        const done = read(name);
        if (!done || !expired(done)) return done;
        localStorage.removeItem(name);
        return null;
      },
      write(entry) {
        verify();
        if (!receiptStates.has(entry.status)) throw new Error('Invalid run status.');
        if (entry.id != null && !/^[A-Za-z0-9]{17}$/.test(entry.id)) throw new Error('Invalid Apify run ID.');
        const existing = read(key);
        const job = existing?.signature || signature;
        const expires = existing?.expires || Date.now() + receiptTtl;
        const done = entry.saved === true || ['ABORTED', 'TIMED-OUT', 'FAILED'].includes(entry.status);
        const data = {status:entry.status, id:entry.id, signature:job, saved:entry.saved === true, expires};
        localStorage.setItem(done ? terminalKey(job) : key, JSON.stringify(data));
        // Keep the pending guard if the terminal receipt could not be saved.
        if (done) localStorage.removeItem(key);
      },
      clearDeclined() {
        verify();
        if (read(key)?.status === 'starting') localStorage.removeItem(key);
      }
    };
  }

  window.CitebaseSession = {
    request, start: endpoint + '?start', stored, store, researchReceipt,
    onChange(listen) { listeners.add(listen); }
  };
})();
