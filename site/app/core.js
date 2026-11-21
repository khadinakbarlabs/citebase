/* Citebase dashboard core: DOM helpers, charts, sign-in with Apify, and calls to Citebase.
   All text is set with textContent, never parsed as HTML, so saved data cannot inject markup.
   Hosted sign-in uses an encrypted HttpOnly cookie. Dashboard access tokens stay in memory. */
(function () {
  'use strict';
  var CFG = window.__CB || {}, OA = CFG.oauth || {}, API = (CFG.api || '').replace(/\/$/, '');
  var QS = new URLSearchParams(location.search);
  var CB = window.CB = { cfg: CFG, api: API, demo: QS.get('demo') === '1' || !API, qs: QS, token: '' };
  CB.hasProjectWork = CB.demo || CFG.projectWork !== false;
  var SVG = 'http://www.w3.org/2000/svg';

  /* ---------- DOM ---------- */
  function setAttrs(el, attrs) {
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    });
  }
  function add(el, kid) {
    if (kid == null || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { add(el, k); }); return; }
    el.appendChild(typeof kid === 'string' || typeof kid === 'number' ? document.createTextNode(String(kid)) : kid);
  }
  CB.h = function (tag, attrs) {
    var el = document.createElement(tag); setAttrs(el, attrs);
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  };
  CB.s = function (tag, attrs) {
    var el = document.createElementNS(SVG, tag); setAttrs(el, attrs);
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  };
  CB.clear = function (el) { while (el.firstChild) el.removeChild(el.firstChild); return el; };
  var h = CB.h, s = CB.s;

  /* ---------- formatting ---------- */
  CB.pct = function (x) { return x == null || isNaN(x) ? '–' : Math.round(x * 100) + '%'; };
  CB.num = function (x) { return x == null || isNaN(x) ? '–' : Math.round(Number(x)).toLocaleString('en-US'); };
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  CB.day = function (d) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || ''); return m ? MONTHS[+m[2] - 1] + ' ' + (+m[3]) + ', ' + m[1] : (d || '–'); };
  CB.short = function (d) { var m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(d || ''); return m ? MONTHS[+m[2] - 1] + (m[3] ? ' ' + (+m[3]) : " '" + m[1].slice(2)) : (d || ''); };
  CB.host = function (u) { try { return new URL(u).host.replace(/^www\./, ''); } catch (e) { return u || ''; } };
  CB.safeUrl = function (u) { try { var x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : null; } catch (e) { return null; } };
  // Engines keep one colour each everywhere (colour follows the engine, never its rank).
  CB.ENGINES = [['chatgpt', 'ChatGPT', 'e1'], ['google-aio', 'Google AI Overviews', 'e2'], ['perplexity', 'Perplexity', 'e3'],
    ['gemini', 'Gemini', 'e4'], ['claude', 'Claude', 'e5'], ['google-aimode', 'Google AI Mode', 'e6'],
    ['grok', 'Grok', 'e7'], ['deepseek', 'DeepSeek', 'e8']];
  function engineRow(k) { return CB.ENGINES.filter(function (x) { return x[0] === k; })[0]; }
  CB.engine = function (k) { var e = engineRow(k); return e ? e[1] : k; };
  CB.ecls = function (k) { var e = engineRow(k); return e ? e[2] : 'e7'; };
  CB.roundName = function (x) { return x.snapshot === 'baseline' ? 'Baseline' : x.snapshot; };
  CB.roundLabel = function (x) { return x.snapshot === 'baseline' ? 'Baseline' : CB.short(x.saved_on) || x.snapshot; };

  /* ---------- tooltip and toast ---------- */
  var tipEl = document.getElementById('tip');
  CB.tip = function (e, title, lines) {
    CB.clear(tipEl); tipEl.appendChild(h('b', { text: title }));
    lines.forEach(function (l) { tipEl.appendChild(h('div', { text: l })); });
    tipEl.hidden = false;
    var x = e.clientX + 14, y = e.clientY + 14, w = tipEl.offsetWidth, hh = tipEl.offsetHeight;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + hh > innerHeight - 8) y = e.clientY - hh - 14;
    tipEl.style.left = x + 'px'; tipEl.style.top = y + 'px';
  };
  CB.untip = function () { tipEl.hidden = true; };
  var toastEl = document.getElementById('toast'), toastTimer;
  CB.toast = function (text, bad) {
    toastEl.textContent = text; toastEl.className = 'toast show' + (bad ? ' bad' : '');
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { toastEl.className = 'toast'; }, 3200);
  };

  /* ---------- charts: inline SVG, hover tooltips, no libraries ---------- */
  // o: {labels, series:[{name, cls, vals}], band:{lo,hi}, max, fmt, width, height, aria, tipTitle(i), tipExtra(i), endLabels}
  CB.lineChart = function (o) {
    var W = o.width || 460, H = o.height || 230, L = 40, R = o.endLabels ? 104 : 18, T = 14, B = 30, n = o.labels.length;
    var max = o.max || 1, fmt = o.fmt || CB.pct;
    var x = function (i) { return n === 1 ? L + (W - L - R) / 2 : L + i * (W - L - R) / (n - 1); };
    var y = function (v) { return T + (1 - Math.max(0, Math.min(max, v)) / max) * (H - T - B); };
    var svg = s('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': o.aria });
    [0, .25, .5, .75, 1].forEach(function (f) {
      var t = f * max;
      svg.appendChild(s('line', { class: 'gl', x1: L, x2: W - R, y1: y(t), y2: y(t) }));
      svg.appendChild(s('text', { class: 'ax', x: L - 8, y: y(t) + 4, 'text-anchor': 'end', text: fmt(t) }));
    });
    var every = Math.ceil(n / 7);
    o.labels.forEach(function (lab, i) {
      if (i % every && i !== n - 1) return;
      var anchor = n === 1 ? 'middle' : i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle';
      svg.appendChild(s('text', { class: 'ax', x: x(i), y: H - 8, 'text-anchor': anchor, text: lab }));
    });
    if (o.band) {
      var top = [], bot = [];
      o.band.hi.forEach(function (v, i) { if (v != null) top.push(x(i) + ' ' + y(v)); });
      o.band.lo.forEach(function (v, i) { if (v != null) bot.unshift(x(i) + ' ' + y(v)); });
      if (n > 1 && top.length) svg.appendChild(s('path', { class: 'band', d: 'M' + top.concat(bot).join(' L') + ' Z' }));
      else if (top.length) svg.appendChild(s('rect', { class: 'band', x: x(0) - 14, width: 28, y: y(o.band.hi[0]), height: Math.max(2, y(o.band.lo[0]) - y(o.band.hi[0])), rx: 4 }));
    }
    var ends = [];
    o.series.forEach(function (se) {
      var d = '', pen = 'M', lastI = -1;
      se.vals.forEach(function (v, i) { if (v == null) { pen = 'M'; return; } d += pen + x(i) + ' ' + y(v) + ' '; pen = 'L'; lastI = i; });
      if (n > 1) svg.appendChild(s('path', { class: 'ln ' + se.cls, d: d }));
      se.vals.forEach(function (v, i) { if (v != null) svg.appendChild(s('circle', { class: 'pt ' + se.cls, cx: x(i), cy: y(v), r: i === n - 1 ? 5 : 4 })); });
      if (o.endLabels && lastI >= 0) ends.push({ y: y(se.vals[lastI]), x: x(lastI), text: se.name + ' ' + fmt(se.vals[lastI]) });
    });
    // direct labels at the line ends, nudged apart so they never overlap
    ends.sort(function (a, b) { return a.y - b.y; });
    for (var k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 14) ends[k].y = ends[k - 1].y + 14;
    ends.forEach(function (e) { svg.appendChild(s('text', { class: 'endlbl', x: e.x + 10, y: e.y + 4, text: e.text })); });
    var hair = s('line', { class: 'hair', y1: T, y2: H - B, x1: 0, x2: 0, visibility: 'hidden' });
    svg.appendChild(hair);
    var hit = s('rect', { class: 'hit', x: L - 10, y: 0, width: W - L - R + 20, height: H });
    hit.addEventListener('mousemove', function (e) {
      var r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
      var i = n === 1 ? 0 : Math.max(0, Math.min(n - 1, Math.round((px - L) / ((W - L - R) / (n - 1)))));
      hair.setAttribute('x1', x(i)); hair.setAttribute('x2', x(i)); hair.setAttribute('visibility', 'visible');
      CB.tip(e, o.tipTitle ? o.tipTitle(i) : o.labels[i], o.series.map(function (se) { return se.name + ': ' + fmt(se.vals[i]); })
        .concat(o.tipExtra ? o.tipExtra(i) : []));
    });
    hit.addEventListener('mouseleave', function () { CB.untip(); hair.setAttribute('visibility', 'hidden'); });
    svg.appendChild(hit);
    return svg;
  };
  // Horizontal bars. o: {items:[{label, value, cls, tip, onclick}], max, fmt, width, labelWidth, aria}
  CB.barChart = function (o) {
    var items = o.items, W = o.width || 460, row = 30, L = o.labelWidth || 150, R = 56, H = items.length * row + 6;
    var max = Math.max.apply(null, items.map(function (it) { return it.value; }).concat([o.max || 0, 1e-9]));
    var fmt = o.fmt || CB.num;
    var svg = s('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': o.aria });
    items.forEach(function (it, i) {
      var y = i * row + 4, w = Math.max(3, (W - L - R) * it.value / max), cut = Math.floor(L / 7.2);
      var lbl = it.label.length > cut ? it.label.slice(0, cut - 1) + '…' : it.label;
      svg.appendChild(s('text', { class: 'lbl', x: L - 10, y: y + 15, 'text-anchor': 'end', text: lbl }));
      svg.appendChild(s('rect', { class: 'track', x: L, y: y + 4, width: W - L - R, height: row - 12, rx: 4 }));
      svg.appendChild(s('rect', { class: 'bar ' + (it.cls || ''), x: L, y: y + 4, width: w, height: row - 12, rx: 4 }));
      svg.appendChild(s('text', { class: 'val', x: L + w + 8, y: y + 15, text: fmt(it.value) }));
      var hit = s('rect', { class: 'hit' + (it.onclick ? ' click' : ''), x: 0, y: y, width: W, height: row });
      hit.addEventListener('mousemove', function (e) { CB.tip(e, it.label, it.tip || [fmt(it.value)]); });
      hit.addEventListener('mouseleave', CB.untip);
      if (it.onclick) hit.addEventListener('click', it.onclick);
      svg.appendChild(hit);
    });
    return svg;
  };
  // Tiny trend line for stat tiles.
  CB.spark = function (vals, max) {
    var pts = vals.filter(function (v) { return v != null; });
    if (pts.length < 2) return null;
    var W = 120, H = 34, top = max || Math.max.apply(null, pts.concat([1e-9])), lo = max ? 0 : Math.min.apply(null, pts.concat([0]));
    var x = function (i) { return 2 + i * (W - 4) / (pts.length - 1); };
    var y = function (v) { return H - 3 - (v - lo) / ((top - lo) || 1) * (H - 6); };
    var d = pts.map(function (v, i) { return (i ? 'L' : 'M') + x(i) + ' ' + y(v); }).join(' ');
    return s('svg', { class: 'spark', viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
      s('path', { class: 'sparkarea', d: d + ' L' + x(pts.length - 1) + ' ' + H + ' L' + x(0) + ' ' + H + ' Z' }),
      s('path', { class: 'sparkline', d: d }), s('circle', { class: 'sparkdot', cx: x(pts.length - 1), cy: y(pts[pts.length - 1]), r: 3 }));
  };
  // Sortable table. cols: [{key, label, num, render(row), sortValue(row), sortable}]
  CB.table = function (cols, rows, opts) {
    opts = opts || {};
    var sortKey = opts.sort || null, dir = opts.dir || -1;
    var wrap = h('div', { class: 'scroll' }), tbl = h('table', {}), body = h('tbody', {}), headRow = h('tr', {});
    cols.forEach(function (c) {
      var th = h('th', { class: c.num ? 'n' : null, scope: 'col' });
      if (c.sortable === false || opts.plain) th.textContent = c.label;
      else th.appendChild(h('button', { class: 'sorter', type: 'button', text: c.label, onclick: function () {
        dir = sortKey === c.key ? -dir : (c.num ? -1 : 1); sortKey = c.key; draw(); } }));
      headRow.appendChild(th);
    });
    function val(r, c) { return c.sortValue ? c.sortValue(r) : r[c.key]; }
    function draw() {
      CB.clear(body);
      var list = rows.slice();
      if (sortKey) {
        var col = cols.filter(function (c) { return c.key === sortKey; })[0];
        list.sort(function (a, b) {
          var x = val(a, col), y = val(b, col);
          if (x == null) return 1;
          if (y == null) return -1;
          return (x > y ? 1 : x < y ? -1 : 0) * dir;
        });
      }
      Array.prototype.forEach.call(headRow.children, function (th, i) {
        th.setAttribute('aria-sort', cols[i].key === sortKey ? (dir > 0 ? 'ascending' : 'descending') : 'none');
      });
      if (!list.length) body.appendChild(h('tr', {}, h('td', { colspan: cols.length, class: 'none', text: opts.empty || 'Nothing to show.' })));
      list.forEach(function (r) {
        body.appendChild(h('tr', {}, cols.map(function (c) {
          var v = c.render ? c.render(r) : r[c.key];
          return h('td', { class: c.num ? 'n' : null }, v == null || v === '' ? '–' : v);
        })));
      });
    }
    tbl.appendChild(h('thead', {}, headRow)); tbl.appendChild(body); wrap.appendChild(tbl); draw();
    wrap.redraw = function (newRows) { rows = newRows; draw(); };
    return wrap;
  };
  CB.csv = function (name, head, rows) {
    var esc = function (v) { v = v == null ? '' : String(v); if (/^[=+\-@]/.test(v)) v = "'" + v; return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var text = [head].concat(rows).map(function (r) { return r.map(esc).join(','); }).join('\n');
    var url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
    var a = h('a', { href: url, download: name }); document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  };

  /* ---------- sign-in with Apify (OAuth, PKCE) ---------- */
  var projectReads = new Map(), readFreshMs = 30000;
  var localHost = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  var session = 0, renewal = null, hosted = !(localHost && OA.session === false), broker = window.CitebaseSession;
  var remoteId = '', tokenVersion = 0, renewAfter = 0, canRefresh = false, verification = null, authReady = false;
  function store(k, v) { try { if (v == null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch (e) {} }
  function stored(k) { try { return sessionStorage.getItem(k) || ''; } catch (e) { return ''; } }
  function resetSession() { session++; renewal = null; verification = null; projectReads.clear(); }
  function requireSession(id) { if (id !== session) throw new Error('signed out'); }
  CB.sessionId = function () { return session; };
  CB.onSignedOut = function () {};
  function q(o) { return Object.keys(o).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(o[k]); }).join('&'); }
  function b64u(buf) { var t = '', a = new Uint8Array(buf); for (var i = 0; i < a.length; i++) t += String.fromCharCode(a[i]); return btoa(t).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
  function rnd(n) { var a = new Uint8Array(n); crypto.getRandomValues(a); return b64u(a); }
  function redirectUri() { return OA.redirectUri || (location.origin + location.pathname); }
  CB.signIn = function () {
    if (hosted) {
      if (location.hash.startsWith('#/') && location.hash.length <= 2048) store('cb.after', location.hash);
      location.assign('/api/session/?start');
      return;
    }
    // Loopback static development can use a registered public client without a session function.
    var verifier = rnd(48), st = rnd(16); store('cb.v', verifier); store('cb.s', st);
    crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)).then(function (d) {
      location.assign(OA.authorize + '?' + q({ response_type: 'code', client_id: OA.clientId, redirect_uri: redirectUri(),
        scope: OA.scope || 'full_api_access', state: st, code_challenge: b64u(d), code_challenge_method: 'S256' }));
    });
  };
  async function tokenCall(params, id) {
    params.client_id = OA.clientId;
    var response, tokens;
    try {
      response = await fetch(OA.token, { method: 'POST', redirect: 'error',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: q(params) });
      tokens = await response.json();
    } catch (_) { /* An interrupted response does not establish that the refresh credential expired. */ }
    requireSession(id);
    if (response && (response.status === 400 || response.status === 401) && tokens && tokens.error === 'invalid_grant') return false;
    if (!response || !response.ok || !tokens || typeof tokens.access_token !== 'string' || !tokens.access_token) {
      throw new Error('Could not renew your Apify sign-in. Check your connection and try again.');
    }
    CB.token = tokens.access_token;
    store('cb.t', CB.token);
    if (tokens.refresh_token) store('cb.r', tokens.refresh_token);
    return true;
  }
  async function renew(id, attemptedToken) {
    requireSession(id);
    if (CB.token !== attemptedToken) return; // Another request already renewed this session.
    var credential = hosted ? null : stored('cb.r');
    if (hosted || credential) {
      if (!renewal) {
        var rotate = hosted ? broker.request('refresh', {sessionId:remoteId, version:tokenVersion}).then(function (result) {
          requireSession(id);
          if (!result.signedIn || result.sessionId !== remoteId) return false;
          setHostedSession(result);
          return true;
        }) : tokenCall({ grant_type: 'refresh_token', refresh_token: credential }, id);
        var pending = rotate
          .finally(function () { if (renewal === pending) renewal = null; });
        renewal = pending;
      }
      if (await renewal) return;
    }
    requireSession(id);
    CB.onSignedOut('Please sign in again.');
    throw new Error('signed out');
  }
  CB.forget = function () {
    resetSession();
    CB.token = ''; remoteId = ''; tokenVersion = 0; renewAfter = 0; canRefresh = false;
    ['cb.t', 'cb.r', 'cb.v', 'cb.s', 'cb.sid', 'cb.after', 'cb.pending'].forEach(function (k) { store(k, null); });
  };
  // A deliberate sign-out keeps this tab on the Citebase sign-in screen instead of
  // sending the visitor straight back to Apify.
  CB.markSignedOut = function (on) { store('cb.out', on ? '1' : null); };
  CB.wasSignedOut = function () { return stored('cb.out') === '1'; };
  CB.signOut = async function () {
    CB.markSignedOut(true);
    var id = session;
    var result = hosted ? await broker.request('logout', {sessionId:remoteId}) : {};
    if (id === session) {
      CB.onSignedOut(result.changed ? 'The account in this browser changed.' : 'You are signed out.');
      if (result.changed) location.replace(location.pathname);
    }
  };
  function setHostedSession(result) {
    if (typeof result.accessToken !== 'string' || !result.accessToken || !result.sessionId) throw new Error('Sign-in unavailable.');
    if (stored('cb.sid') !== result.sessionId) store('cb.pending', null);
    if (remoteId !== result.sessionId) resetSession();
    remoteId = result.sessionId; tokenVersion = result.version; CB.token = result.accessToken;
    renewAfter = 1000 * Math.min(result.sessionUntil, result.expiresAt || result.sessionUntil);
    canRefresh = result.canRefresh === true;
    store('cb.sid', remoteId);
  }
  function verifyAccount(id) {
    requireSession(id);
    if (verification) return verification;
    var current = broker.request('verify', {sessionId:remoteId}).then(function (result) {
      requireSession(id);
      if (!result.signedIn || result.sessionId !== remoteId) {
        CB.onSignedOut(result.changed ? 'The account in this browser changed.' : 'Please sign in again.');
        if (result.changed) location.replace(location.pathname);
        throw new Error('signed out');
      }
      setHostedSession(result);
    }).finally(function () { if (verification === current) verification = null; });
    verification = current;
    return current;
  }
  async function hostedAuth() {
    if (!broker) return 'unavailable';
    var code = QS.get('code'), reason = QS.get('error'), state = QS.get('state');
    var fromSignIn = QS.get('signin') === '1';
    if (code || reason || fromSignIn) history.replaceState(null, '', location.pathname + location.hash);
    var result;
    if (code || reason) {
      var fields = {code:code, state:state};
      if (state && state === stored('cb.s')) fields.legacyVerifier = stored('cb.v');
      store('cb.v', null); store('cb.s', null);
      try { result = await broker.request(reason ? 'cancel' : 'exchange', fields); }
      catch (_) { return 'failed'; }
      if (reason) return 'cancelled';
    } else {
      try { result = await broker.request('restore'); } catch (_) { return 'unavailable'; }
    }
    if (result.signedIn) {
      setHostedSession(result);
      CB.justSignedIn = Boolean(code);
      var target = stored('cb.after');
      store('cb.after', null);
      if (code && target.startsWith('#/') && target.length <= 2048) history.replaceState(null, '', location.pathname + target);
      return 'in';
    }
    if (fromSignIn) { CB.signIn(); return 'redirecting'; }
    return 'out';
  }
  if (hosted && broker) {
    var wakeTimer;
    function reconcile() {
      if (CB.demo || !authReady) return;
      clearTimeout(wakeTimer);
      wakeTimer = setTimeout(function () {
        if (remoteId) verifyAccount(session).catch(function () { /* Offline: verify again before any write. */ });
        else broker.request('status').then(function (result) {
          if (result.signedIn && !remoteId) location.reload();
        }).catch(function () {});
      }, 40);
    }
    broker.onChange(function (event) {
      if (CB.demo) return;
      if (event.kind === 'check') { reconcile(); return; }
      if (!remoteId) { if (event.kind === 'in') location.reload(); return; }
      if (event.kind === 'out' && event.sessionId === remoteId) CB.onSignedOut('You are signed out.');
      if (event.kind === 'in' && event.sessionId !== remoteId) {
        CB.onSignedOut('The account in this browser changed. Open the dashboard to continue.');
        location.reload();
      }
    });
    window.addEventListener('focus', reconcile);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) reconcile(); });
    window.addEventListener('pageshow', function (event) { if (event.persisted && !CB.demo) location.reload(); });
  }
  CB.startAuth = async function () {
    if (CB.demo) return 'demo';
    if (hosted) { var state = await hostedAuth(); authReady = true; return state; }
    var savedToken = stored('cb.t');
    if (savedToken !== CB.token) {
      if (CB.token) store('cb.pending', null);
      resetSession();
      CB.token = savedToken;
    }
    if (QS.get('code')) {
      var ok = QS.get('state') && QS.get('state') === stored('cb.s'), ver = stored('cb.v'), code = QS.get('code');
      store('cb.v', null); store('cb.s', null);
      history.replaceState(null, '', location.pathname + location.hash);
      if (!ok || !ver) return 'failed';
      CB.forget();
      try {
        return await tokenCall({ grant_type: 'authorization_code', code: code, redirect_uri: redirectUri(), code_verifier: ver }, session) ? 'in' : 'failed';
      } catch (_) { return 'failed'; }
    }
    if (QS.get('error')) { history.replaceState(null, '', location.pathname + location.hash); return 'cancelled'; }
    if (!CB.token && QS.get('signin') === '1') {
      history.replaceState(null, '', location.pathname + location.hash);
      CB.signIn();
      return 'redirecting';
    }
    return CB.token ? 'in' : 'out';
  };
  CB.whoami = function () {
    if (CB.demo) return Promise.resolve(null);
    return apify('GET', 'users/me').then(function (user) { return (user && user.username) || null; })
      .catch(function () { return null; });
  };

  /* ---------- Citebase calls ---------- */
  var readTools = new Set(['get_history', 'quote_cost', 'next_steps', 'get_playbook', 'measure_recommendation_share',
    'check_ai_content', 'check_outreach_draft', 'dashboard_storage_review', 'dashboard_balance_read']);
  // Some list/get operations also create records or pause an expired schedule. Only replay known reads.
  var readWork = new Set(['project_focus', 'brief_get', 'opportunities_list', 'changes_list', 'runs_list', 'prospects_list',
    'onboarding_get', 'research_get', 'research_plan', 'outreach_prepare', 'outreach_status']);
  var workWrites = new Set(['onboarding_suggest', 'onboarding_save', 'research_import', 'citation_prospect_save', 'outreach_claim',
    'brief_save', 'action_save', 'action_recheck', 'schedule_apply', 'schedule_pause',
    'schedule_resume', 'prospect_save', 'draft_save', 'draft_approve', 'digest_save', 'offer_dismiss', 'offer_measure_record']);
  function safeRead(tool, args) {
    return readTools.has(tool) || (tool === 'project_work' && readWork.has(args.operation))
      || (tool === 'save_results' && args.check_only === true);
  }
  function changesProject(tool, args) {
    return args.project && ((tool === 'save_results' && args.check_only !== true) || tool === 'audit_site' || tool === 'scheduled_check'
      || (tool === 'import_ai_results' && args.save === true) || (tool === 'project_work' && workWrites.has(args.operation)));
  }
  function requestError(service, status, detail) {
    const message = typeof detail === 'string' ? detail : detail && detail.message;
    const error = new Error(typeof message === 'string' && message ? message : service + ' answered with an error (' + status + ').');
    error.status = status;
    if (detail && typeof detail.type === 'string') error.type = detail.type;
    return error;
  }
  var canonicalActorRun = 'https://khadinakbar--citebase.apify.actor/run';
  function trustedActorRun(url) {
    if (url === canonicalActorRun) return true;
    var origin = location.origin;
    return /^https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(origin) && url === origin + '/run';
  }
  async function authenticatedJson(service, url, init, readOnly) {
    var actor = service === 'Citebase';
    if (actor && !trustedActorRun(url)) throw new Error('The Citebase service address is not recognized.');
    var relay = actor && hosted && CB.hasProjectWork && url === canonicalActorRun;
    if (relay) {
      // The Standby gateway does not allow a browser preflight with the project's caller header.
      url = '/api/actor/';
      init.mode = 'same-origin';
      init.credentials = 'same-origin';
      init.cache = 'no-store';
      init.headers['X-Citebase-Session'] = '1';
    }
    var id = session;
    if (hosted && !readOnly) await verifyAccount(id);
    else if (hosted && renewAfter && Date.now() + 5000 >= renewAfter) await renew(id, CB.token);
    var advice = readOnly ? 'Check your connection and try again.' : 'Review the project or Activity to see whether the change went through.';
    for (var attempt = 0; attempt < 2; attempt++) {
      requireSession(id);
      var token = CB.token;
      init.headers.Authorization = 'Bearer ' + token;
      if (actor && !relay && token && CB.hasProjectWork) {
        // An explicitly configured local Actor can authenticate the browser directly.
        init.headers['X-Apify-Authorization'] = init.headers.Authorization;
        init.headers['X-Citebase-Authorization'] = init.headers.Authorization;
      }
      let response;
      try { response = await fetch(url, init); }
      catch (_) {
        requireSession(id);
        // An opaque gateway 401 and a lost response both look like a network failure.
        if (attempt || !readOnly || !(hosted ? canRefresh : stored('cb.r'))) throw new Error('Could not reach ' + service + '. ' + advice);
      }
      requireSession(id);
      if (relay && !readOnly && response && response.status === 401 &&
          (!response.headers || response.headers.get('X-Citebase-Not-Dispatched') !== '1')) {
        // Only the relay can confirm that a rejected write never reached the Actor.
        throw requestError(service, 401, 'Citebase could not confirm this change. ' + advice);
      }
      if (!response || (response.status === 401 && !attempt)) {
        await renew(id, token);
        continue;
      }
      if (response.status === 204) return {response: response, json: null};
      var json = await response.json().catch(function () { return null; });
      requireSession(id);
      if (!response.ok) throw requestError(service, response.status, json && json.error);
      if (json === null) throw new Error(service + ' sent a reply this page could not read. ' + advice);
      return {response: response, json: json};
    }
  }
  async function call(tool, args = {}) {
    if (CB.demo) return window.CB_DEMO.call(tool, args);
    var id = session;
    var changedProject = changesProject(tool, args) ? args.project : null;
    try {
      var reply = await authenticatedJson('Citebase', API + '/run', { method: 'POST', redirect: 'error',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool: tool, arguments: args }) }, safeRead(tool, args));
      var json = reply.json;
      if (!json || !json.ok) throw new Error((json && json.error) || 'Citebase could not answer.');
      return json.result;
    } finally {
      // A saved change can reach the server even if its confirmation never reaches this tab.
      if (id === session && changedProject) {
        projectReads.delete(changedProject);
        projectReads.delete('');
      }
    }
  }
  CB.tool = function (tool, args) { return call(tool, args || {}); };
  function cachedRead(project, key, fresh, load) {
    var entries = projectReads.get(project);
    if (!entries) { entries = new Map(); projectReads.set(project, entries); }
    var entry = entries.get(key);
    if (entry && (entry.pending || (!fresh && Date.now() < entry.expires))) return entry.promise;
    var id = session;
    entry = {pending: true};
    entries.set(key, entry);
    entry.promise = load().then(function (result) {
      requireSession(id);
      // Invalidation detaches these entries, so a late response cannot replace a newer read.
      entry.pending = false;
      entry.expires = Date.now() + readFreshMs;
      return result;
    }, function (error) {
      if (entries.get(key) === entry) entries.delete(key);
      throw error;
    });
    return entry.promise;
  }
  function focusKey(data) {
    if (typeof data !== 'object' || Array.isArray(data)) return null;
    var fields = Object.keys(data);
    if (!fields.every(function (key) {
      return (key === 'limit' || key === 'priority') && (typeof data[key] === 'string' || typeof data[key] === 'number');
    })) return null;
    return 'focus:' + JSON.stringify(data, fields.sort());
  }
  CB.work = function (project, operation, data, fresh) {
    data = data || {};
    if (CB.demo) return Promise.resolve().then(function () { return CB.demoWork(project, operation, data); });
    if (!CB.hasProjectWork) return Promise.reject(new Error('Explore this workflow in the sample project.'));
    function load() {
      return call('project_work', { project: project, operation: operation, data: data })
        .then(function (reply) { return reply.result; });
    }
    var key = operation === 'project_focus' ? focusKey(data) : null;
    return key === null ? load() : cachedRead(project, key, fresh, load);
  };
  async function apify(method, path, body) {
    if (CB.demo) return window.CB_DEMO.apify(method, path, body);
    var init = { method: method, headers: {}, redirect: 'error' };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    var reply = await authenticatedJson('Apify', 'https://api.apify.com/v2/' + path, init, method === 'GET' || method === 'HEAD');
    var json = reply.json;
    return json && json.data !== undefined ? json.data : json;
  }
  CB.apify = apify;
  CB.history = function (project, fresh) {
    return cachedRead(project || '', 'history', fresh, function () {
      return call('get_history', project ? { project: project } : {});
    });
  };
  CB.saveTodo = function (project, items) {
    return call('save_results', { project: project, todo: items });
  };
  CB.refresh = function () { projectReads.clear(); };
})();
