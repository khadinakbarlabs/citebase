/* Citebase dashboard feedback: toasts, busy buttons, page loading, clear error pages,
   offline notice and a slim route progress bar. Loaded right after core.js.
   Text is always set with textContent. */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h, s = CB.s;
  var ICON = { ok: 'check', bad: 'alert', info: 'info', offline: 'wifi-off' };

  function icon(name, cls) {
    return s('svg', { class: cls || 'fb-icon', 'aria-hidden': 'true' }, s('use', { href: '../assets/icons.svg#' + name }));
  }
  CB.icon = icon;

  /* ---------- toasts: stacked, with tone, icon, optional action and dismiss ---------- */
  // Two live regions (polite and assertive) share one dock in the corner.
  var polite = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' });
  var urgent = h('div', { class: 'toasts urgent', role: 'alert', 'aria-live': 'assertive' });
  document.body.appendChild(h('div', { class: 'toast-dock' }, urgent, polite));
  var MAX_TOASTS = 3;

  // CB.toast(text, bad) stays compatible; a third form takes options:
  // CB.toast(text, { tone: 'ok'|'bad'|'info', action: { label, run }, ms })
  CB.toast = function (text, opt) {
    var o = opt && typeof opt === 'object' ? opt : { tone: opt ? 'bad' : 'ok' };
    var tone = o.tone || 'ok', host = tone === 'bad' ? urgent : polite;
    var ms = o.ms || (tone === 'bad' ? 7000 : o.action ? 6000 : 3400);
    var el = h('div', { class: 'toast2 ' + tone },
      icon(ICON[tone] || 'info'), h('span', { class: 'toast-text', text: String(text || '') }));
    var timer;
    function close() {
      clearTimeout(timer);
      if (!el.isConnected || el.classList.contains('out')) return;
      el.classList.add('out');
      setTimeout(function () { el.remove(); }, 220);
    }
    function arm() { clearTimeout(timer); timer = setTimeout(close, ms); }
    if (o.action) el.appendChild(h('button', { type: 'button', class: 'toast-act', text: o.action.label,
      onclick: function () { close(); o.action.run(); } }));
    el.appendChild(h('button', { type: 'button', class: 'toast-x', 'aria-label': 'Dismiss', onclick: close }, icon('x')));
    el.addEventListener('mouseenter', function () { clearTimeout(timer); });
    el.addEventListener('mouseleave', arm);
    el.addEventListener('focusin', function () { clearTimeout(timer); });
    host.appendChild(el);
    var all = document.querySelectorAll('.toast2:not(.out)');
    for (var i = 0; i < all.length - MAX_TOASTS; i++) all[i].remove();
    arm();
    return { close: close };
  };

  /* ---------- busy buttons ----------
     Any button that turns disabled while its label ends with "…" shows a spinner and
     aria-busy, so every existing "Saving…" / "Starting…" step gets the same feedback. */
  function syncBusy(btn) {
    var on = btn.disabled && /…\s*$/.test(btn.textContent || '');
    if (on) btn.setAttribute('aria-busy', 'true'); else btn.removeAttribute('aria-busy');
  }
  new MutationObserver(function (list) {
    list.forEach(function (m) {
      var t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
      var btn = t && t.closest && t.closest('button');
      if (btn) syncBusy(btn);
    });
  }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['disabled'], childList: true, characterData: true });

  // Brief confirmation on a button after a successful action.
  CB.done = function (btn, text) {
    if (!btn) return;
    var was = btn.textContent;
    btn.classList.add('is-done');
    btn.replaceChildren(icon('check', 'fb-icon sm'), h('span', { text: text || 'Done' }));
    setTimeout(function () { btn.classList.remove('is-done'); if (btn.isConnected) btn.textContent = was; }, 1600);
  };

  /* ---------- page loading: shaped like the page that is coming ---------- */
  function bones(shape) {
    var stats = h('div', { class: 'bone-stats' }, h('i'), h('i'), h('i'), h('i'));
    var rows = h('div', { class: 'bone-rows' }, h('i'), h('i'), h('i'), h('i'));
    if (shape === 'project') return h('div', { class: 'bones project', 'aria-hidden': 'true' },
      h('i', { class: 'bone-title' }), h('div', { class: 'bone-split' }, h('i', { class: 'bone-nav' }),
        h('div', {}, stats, h('i', { class: 'bone-panel' }))));
    return h('div', { class: 'bones', 'aria-hidden': 'true' }, h('i', { class: 'bone-title' }), stats, rows);
  }
  var SLOW_MS = 6000, VERY_SLOW_MS = 16000;
  CB.loadingView = function (host, text, shape) {
    var note = h('span', { class: 'load-note' });
    var box = h('div', { class: 'loading2', role: 'status', 'aria-live': 'polite' },
      h('p', { class: 'load-line' }, h('span', { class: 'spin', 'aria-hidden': 'true' }), h('span', { text: text }), note),
      bones(shape));
    host.appendChild(box);
    var t1 = setTimeout(function () {
      if (box.isConnected) note.textContent = 'Still working. Citebase is starting in your Apify account.';
    }, SLOW_MS);
    var t2 = setTimeout(function () {
      if (box.isConnected) note.textContent = 'This is taking longer than usual. Keep this tab open; it continues on its own.';
    }, VERY_SLOW_MS);
    return { el: box, stop: function () { clearTimeout(t1); clearTimeout(t2); } };
  };

  /* ---------- errors: say what happened and what to do ---------- */
  CB.explainError = function (err) {
    var msg = String((err && err.message) || err || ''), status = err && (err.status || err.statusCode);
    if (!navigator.onLine || /failed to fetch|networkerror|network request failed|load failed/i.test(msg))
      return { kind: 'offline', title: 'No connection to Citebase', hint: 'Check your internet connection, then try again.' };
    if (/timed? ?out|timeout/i.test(msg))
      return { kind: 'slow', title: 'Citebase took too long to answer', hint: 'Your Apify account may still be starting Citebase. Wait a moment and try again.' };
    if (status === 401 || status === 403 || /unauthori[sz]ed|forbidden/i.test(msg))
      return { kind: 'auth', title: 'Your sign-in needs a refresh', hint: 'Sign in with Apify again to continue. Your projects are safe.' };
    if (status === 429 || /rate limit|too many requests/i.test(msg))
      return { kind: 'busy', title: 'Too many requests at once', hint: 'Wait about a minute, then try again.' };
    if ((status >= 500 && status < 600) || /internal|server error|bad gateway|unavailable/i.test(msg))
      return { kind: 'server', title: 'Citebase could not finish that request', hint: 'This is usually temporary. Try again in a moment.' };
    return { kind: 'other', title: 'That did not work', hint: 'Try again. If it keeps happening, the details below explain why.' };
  };
  CB.errorView = function (err, retry) {
    var e = CB.explainError(err), msg = String((err && err.message) || err || '');
    var actions = h('div', { class: 'err-actions' });
    if (retry) actions.appendChild(h('button', { class: 'btn', type: 'button', onclick: retry }, icon('refresh', 'fb-icon sm'), h('span', { text: 'Try again' })));
    if (location.hash && location.hash !== '#/') actions.appendChild(h('a', { class: 'btn ghost', href: '#/', text: 'Back to projects' }));
    return h('section', { class: 'err2 is-' + e.kind },
      h('div', { class: 'err-mark' }, icon(e.kind === 'offline' ? 'wifi-off' : 'alert')),
      h('div', { class: 'err-body' }, h('h2', { text: e.title }), h('p', { text: e.hint }), actions,
        msg && msg !== e.title ? h('details', { class: 'err-more' }, h('summary', { text: 'Technical details' }), h('code', { text: msg })) : null));
  };

  /* ---------- offline notice ---------- */
  var offline = h('div', { class: 'offline', role: 'status', hidden: true },
    icon('wifi-off', 'fb-icon sm'), h('span', { text: 'You are offline. Changes will not save until the connection returns.' }));
  document.body.appendChild(offline);
  function net() {
    var was = !offline.hidden;
    offline.hidden = navigator.onLine;
    if (was && navigator.onLine) CB.toast('Back online');
  }
  addEventListener('online', net); addEventListener('offline', net); net();

  /* ---------- overview numbers count up once when they first appear ---------- */
  var COUNT_MS = 700;
  var still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function countUp(el) {
    el.dataset.counted = '1';
    var node = el.firstChild;
    if (still || !node || node.nodeType !== 3) return;
    var m = /^(\d{1,4})(%?)$/.exec(node.nodeValue.trim());
    if (!m) return;
    var end = Number(m[1]), suffix = m[2], t0 = performance.now();
    if (end < 2) return;
    (function tick(now) {
      var p = Math.min(1, (now - t0) / COUNT_MS), eased = 1 - Math.pow(1 - p, 3);
      node.nodeValue = Math.round(end * eased) + suffix;
      if (p < 1 && node.isConnected) requestAnimationFrame(tick); else node.nodeValue = end + suffix;
    })(t0);
  }
  // Only on arrival at a project, not when a metric is re-selected on the same page.
  var mainEl = document.getElementById('main'), countedFor = '';
  if (mainEl) new MutationObserver(function () {
    var fresh = mainEl.querySelectorAll('.metric-value:not([data-counted])');
    if (!fresh.length) return;
    var key = location.hash.split('/').slice(0, 3).join('/');
    var animate = key !== countedFor; countedFor = key;
    fresh.forEach(function (el) { if (animate) countUp(el); else el.dataset.counted = '1'; });
  }).observe(mainEl, { childList: true, subtree: true });

  /* ---------- summary bar: counts as one coloured strip with one-tap filter chips ----------
     parts: [{ key, label, count, tone }]; tone is a CSS colour variable name such as 'good'. */
  CB.summaryBar = function (parts, active, onPick, label) {
    var shown = parts.filter(function (p) { return p.count > 0; });
    var total = shown.reduce(function (n, p) { return n + p.count; }, 0);
    if (!total) return null;
    // Styles go through the CSSOM: the page's security policy blocks inline style attributes.
    function swatch(el, tone, grow) {
      el.style.background = 'var(--' + tone + ')';
      if (grow) el.style.flexGrow = String(grow);
      return el;
    }
    var strip = h('div', { class: 'sumbar-strip', 'aria-hidden': 'true' }, shown.map(function (p) {
      return swatch(h('i'), p.tone, p.count);
    }));
    var chips = h('div', { class: 'sumbar-chips', role: 'group', 'aria-label': label || 'Filter' },
      [{ key: 'all', label: 'All', count: total, tone: 'ink-2' }].concat(shown).map(function (p) {
        return h('button', { type: 'button', class: 'sumbar-chip', 'aria-pressed': String((active || 'all') === p.key),
          onclick: function () { onPick(p.key); } },
          swatch(h('i', { 'aria-hidden': 'true' }), p.tone), h('span', { text: p.label }), h('b', { text: String(p.count) }));
      }));
    return h('div', { class: 'sumbar' }, strip, chips);
  };

  /* ---------- slim progress bar for page changes ---------- */
  var bar = h('div', { class: 'route-bar', 'aria-hidden': 'true' });
  document.body.appendChild(bar);
  var pending = 0;
  CB.progress = {
    start: function () { pending++; bar.classList.remove('done'); bar.classList.add('on'); },
    done: function () {
      pending = Math.max(0, pending - 1);
      if (pending) return;
      bar.classList.add('done');
      setTimeout(function () { if (!pending) bar.classList.remove('on', 'done'); }, 380);
    }
  };
})();
