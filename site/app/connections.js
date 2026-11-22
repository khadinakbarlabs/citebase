/* Citebase project Connections page: one card per data source with a plain status. Uses window.CB from core.js. */
(function () {
  'use strict';
  var CB = window.CB;

  /* ---------- status logic (pure; covered by tests/browser/connections.test.cjs) ---------- */
  var RECONNECT = ' If it keeps happening, choose Reconnect.';
  var CHECKING = { tone: 'checking', label: 'Checking…', detail: 'Checking this connection.' };
  function googleStatus(state) {
    if (!state) return CHECKING;
    if (state.configured === false) return { tone: 'off', label: 'Not available',
      detail: 'Google connections are not switched on for this Citebase website yet.' };
    if (state.error) return { tone: 'action', label: 'Needs action', detail: state.error + RECONNECT };
    if (!state.connected) return { tone: 'off', label: 'Not set up', detail: 'Connect to import a read-only report of the last 28 days.' };
    if (!state.property) return { tone: 'action', label: 'Needs action',
      detail: 'Signed in to Google. Choose property to pick the one that matches this website.' };
    var last = state.last_import;
    return { tone: 'good', label: 'Connected', account: state.property,
      sync: last ? 'Last import ' + CB.day(last.observed_at || last.end_date) + ' · covers ' + CB.day(last.start_date) + ' to ' + CB.day(last.end_date) +
          (typeof last.count === 'number' ? ' · ' + last.count + (last.count === 1 ? ' row' : ' rows') : '')
        : 'No import yet. Choose Import 28 days.' };
  }
  function gmailStatus(state) {
    if (!state) return CHECKING;
    if (state.configured === false) return { tone: 'off', label: 'Not available',
      detail: 'Gmail sending is not switched on for this Citebase website yet.' };
    if (state.error) return { tone: 'action', label: 'Needs action', detail: state.error + RECONNECT };
    if (!state.connected) return { tone: 'off', label: 'Not set up', detail: 'Connect Gmail to send outreach emails you approve, from your own address.' };
    return { tone: 'good', label: 'Connected', detail: 'Ready to send outreach emails you approve. Nothing is sent without your OK.' };
  }
  var HOW = {
    bots: 'Paste a few days of your website’s access log (server log) into a chat with Citebase and ask it to save the AI bot visits here.',
    traffic: 'Export visits by source from your analytics tool, paste the file into a chat with Citebase and ask it to save the AI visits here.'
  };
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function month(m) { var x = /^(\d{4})-(\d{2})/.exec(m || ''); return x ? MONTHS[+x[2] - 1] + ' ' + x[1] : ''; }
  // What a saved file covers: the log's days, or the export's first and last month.
  function coverage(kind, record) {
    var period = record.period || {}, months = (record.by_month || []).map(function (r) { return r.month; }).filter(Boolean);
    if (kind === 'bots' && period.from && period.to) return 'covers ' + CB.day(period.from) + ' to ' + CB.day(period.to);
    if (months.length) return 'covers ' + month(months[0]) + (months.length > 1 ? ' to ' + month(months[months.length - 1]) : '');
    return '';
  }
  function savedStatus(kind, record) {
    if (!record) return { tone: 'off', label: 'Not set up', detail: HOW[kind] };
    var covers = coverage(kind, record);
    var sync = record.date ? 'Last saved ' + CB.day(record.date) + (covers ? ' · ' + covers : '') : covers ? covers[0].toUpperCase() + covers.slice(1) : '';
    return { tone: 'good', label: 'Saved', sync: sync, detail: 'To update it, paste a newer file into a chat with Citebase.' };
  }
  function summary(tones) {
    var count = function (t) { return tones.filter(function (x) { return x === t; }).length; };
    var good = count('good'), action = count('action'), off = count('off'), checking = count('checking');
    if (!good && !action && !checking) return 'Nothing connected yet';
    var parts = good ? [good + ' ready'] : [];
    if (action) parts.push(action + (action === 1 ? ' needs action' : ' need action'));
    if (checking) parts.push('checking the rest…');
    else if (off) parts.push(off + ' not set up');
    return parts.join(' · ');
  }

  /* ---------- page ---------- */
  var SOON = [
    { key: 'bing', name: 'Bing Webmaster Tools', icon: 'search', text: 'Searches that show your site on Bing, which also feeds Copilot answers.' },
    { key: 'speed', name: 'Google page speed', icon: 'health', text: 'How fast real visitors see your pages load, from Google’s Chrome data.' },
    { key: 'cloudflare', name: 'Cloudflare AI bot stats', icon: 'site', text: 'Which AI bots visit your site, read straight from Cloudflare. No log file to paste.' }
  ];
  function route(slug) { return '#/p/' + encodeURIComponent(slug) + '/connections'; }

  function render(body, d, slug) {
    var h = CB.h, icon = CB.journey.icon, live = Boolean(CB.googleUI && CB.hasProjectWork && !CB.demo);
    var cards = [], total = h('p', { class: 'cn-summary', 'aria-live': 'polite' });
    function refreshSummary() { total.textContent = summary(cards.map(function (c) { return c.tone; })); }

    function card(opts) {
      var badge = h('span', { class: 'cn-badge' }), detail = h('p', { class: 'cn-detail' });
      var account = h('p', { class: 'cn-fact' }), sync = h('p', { class: 'cn-fact' });
      var node = h('article', { class: 'cn-card', 'data-connection': opts.key, 'aria-labelledby': 'cn-' + opts.key },
        h('header', { class: 'cn-head' }, h('span', { class: 'cn-mark', 'aria-hidden': 'true' }, icon(opts.icon, opts.logo ? 'g-logo' : 'jr-icon')),
          h('h3', { id: 'cn-' + opts.key, text: opts.name }), badge),
        h('p', { class: 'cn-what', text: opts.text }), h('div', { class: 'cn-status' }, account, sync, detail));
      var entry = { node: node, tone: 'checking', slot: null };
      entry.set = function (s) {
        entry.tone = s.tone; node.dataset.tone = s.tone;
        badge.textContent = s.label;
        account.hidden = !s.account; account.textContent = s.account ? (opts.accountLabel || 'Account') + ': ' + s.account : '';
        sync.hidden = !s.sync; sync.textContent = s.sync || '';
        detail.hidden = !s.detail; detail.textContent = s.detail || '';
        refreshSummary();
      };
      if (opts.manage) { entry.slot = h('div', { class: 'cn-manage' }); node.appendChild(entry.slot); }
      cards.push(entry);
      return entry;
    }
    function group(title, note, list) {
      return h('section', { class: 'cn-group', 'aria-label': title },
        h('div', { class: 'cn-group-head' }, h('h2', { text: title }), note ? h('p', { text: note }) : null),
        h('div', { class: 'cn-grid' }, list.map(function (c) { return c.node; })));
    }
    function offline(c, what) {
      c.set(CB.demo ? { tone: 'off', label: 'Not set up', detail: 'Sign in to connect your own ' + what + '.' }
        : { tone: 'off', label: 'Not available', detail: 'Connect ' + what + ' from the signed-in Citebase website.' });
    }

    // Google reporting: each card hosts the existing Google panel actions for one service.
    function googleCard(service, name, logo, text) {
      var c = card({ key: service, name: name, icon: logo, logo: true, text: text, manage: live, accountLabel: 'Property' });
      if (!live) { offline(c, 'Google account'); return c; }
      c.set(googleStatus(null));
      c.slot.appendChild(CB.googleUI.panel(slug, { only: service, returnTo: 'connections',
        onState: function (state) { c.set(googleStatus(state)); } }));
      return c;
    }
    var gsc = googleCard('gsc', 'Google Search Console', 'logo-gsc', 'The Google searches that show your site, with views, clicks and position.');
    var ga4 = googleCard('ga4', 'Google Analytics 4', 'logo-ga', 'Visits to your site, including people who click through from ChatGPT, Perplexity and other AI assistants.');

    var gmail = card({ key: 'gmail', name: 'Gmail sending', icon: 'logo-google', logo: true, manage: live,
      text: 'Sends the outreach emails you approve in Outreach, from your own Gmail address.' });
    if (live) gmailActions(gmail, slug); else offline(gmail, 'Gmail');

    var bots = card({ key: 'bots', name: 'AI bot visits', icon: 'activity', text: 'Which AI crawlers read your site and whether any are refused. From your server log.' });
    bots.set(savedStatus('bots', d && d.ai_bot_visits));
    var traffic = card({ key: 'traffic', name: 'Analytics export', icon: 'traffic', text: 'Monthly visits from AI assistants, from a file you export from your analytics tool.' });
    traffic.set(savedStatus('traffic', d && d.ai_traffic));

    var soon = SOON.map(function (s) {
      var c = card({ key: s.key, name: s.name, icon: s.icon, text: s.text });
      c.node.classList.add('is-soon'); c.node.setAttribute('aria-disabled', 'true');
      c.set({ tone: 'soon', label: 'Coming soon', detail: 'Not available yet. Nothing to set up for now.' });
      return c;
    });

    body.appendChild(h('div', { class: 'cn-page' },
      h('header', { class: 'cn-intro' }, h('h2', { class: 'cn-title', text: 'Connections' }),
        h('p', { class: 'cn-lede', text: 'Every place Citebase gets data for this project, and what each one needs.' }), total),
      group('Live connections', 'Read-only reports and sending you approve. You can disconnect any time.', [gsc, ga4, gmail]),
      group('Data you paste in a chat', 'No sign-in needed. Paste a file into a chat with Citebase and it is saved to this project.', [bots, traffic]),
      group('Coming soon', null, soon)));
    refreshSummary();
  }

  // Gmail sending: status, connect and disconnect through CB.googleUI.gmail.
  function gmailActions(card, slug) {
    var h = CB.h, mail = CB.googleUI.gmail, actions = h('div', { class: 'actions' });
    var active = function () { return actions.isConnected; };
    card.slot.appendChild(actions);
    card.set(gmailStatus(null));
    function button(text, run, ghost) {
      var b = h('button', { type: 'button', class: ghost ? 'btn ghost' : 'btn' }, CB.journey.icon('logo-google', 'g-logo sm'), h('span', { text: text }));
      b.addEventListener('click', async function () {
        actions.inert = true;
        try { await run(); } catch (e) { card.set(gmailStatus({ error: e.message })); } finally { actions.inert = false; }
      });
      actions.appendChild(b);
    }
    async function load() {
      var state;
      try { state = await mail.status(slug); } catch (e) { state = { error: e.message }; }
      if (!active()) return;
      card.set(gmailStatus(state)); actions.replaceChildren();
      if (state.configured === false) return;
      var connect = function () { return mail.connect(slug, active, 'connections'); };
      if (state.connected) button('Disconnect Gmail', async function () { await mail.disconnect(slug); await load(); }, true);
      else button(state.error ? 'Reconnect Gmail' : 'Connect Gmail', connect);
    }
    load();
  }

  CB.connectionsUI = { render: render, route: route,
    status: { google: googleStatus, gmail: gmailStatus, saved: savedStatus, summary: summary } };
})();
