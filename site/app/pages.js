/* Citebase dashboard pages built on Apify's API: Activity (runs), Schedules, Account, and the getting-started
   checklist. Usage is shown as a share of the plan limit, never as an amount of money. */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h, F = CB.flows;
  var P = CB.pages = {};
  var OWNER = 'khadinakbar';
  var IMPORTABLE = ['ai-search-brand-monitor', 'google-ai-overviews-scraper', 'google-ai-mode-scraper', 'ai-search-visibility-tracker', 'ai-citations-tracker'];
  var actorCache = {};

  function card(title, sub, body, tools) {
    return h('section', { class: 'card' }, h('div', { class: 'card-top' }, h('div', {}, h('h3', { text: title }), sub ? h('p', { class: 'sub', text: sub }) : null),
      tools ? h('div', { class: 'tools' }, tools) : null), body);
  }
  function head(title, sub, tools) { return h('div', { class: 'head' }, h('div', {}, h('h1', { text: title }), sub ? h('p', { text: sub }) : null), tools ? h('div', { class: 'tools' }, tools) : null); }
  function stat(k, v, tone) { return h('div', { class: 'stat' + (tone ? ' ' + tone : '') }, h('div', { class: 'k', text: k }), h('div', { class: 'v', text: v })); }
  function failBox(body, e) { CB.clear(body).appendChild(h('div', { class: 'err' }, h('p', { text: e.message }))); }
  P.ago = function (iso) {
    if (!iso) return '–';
    var s = (Date.now() - new Date(iso).getTime()) / 1000, f = Math.abs(s);
    var t = f < 90 ? 'a minute' : f < 3600 ? Math.round(f / 60) + ' min' : f < 86400 ? Math.round(f / 3600) + ' h' : Math.round(f / 86400) + ' days';
    return s < 0 ? 'in ' + t : (f < 90 ? 'just now' : t + ' ago');
  };
  function dur(r) {
    if (!r.startedAt) return '–';
    var s = ((r.finishedAt ? new Date(r.finishedAt) : new Date()) - new Date(r.startedAt)) / 1000;
    return s < 60 ? Math.round(s) + ' s' : s < 3600 ? Math.round(s / 60) + ' min' : (s / 3600).toFixed(1) + ' h';
  }
  P.badge = function (status) {
    var tone = status === 'SUCCEEDED' ? 'good' : /RUNNING|READY/.test(status) ? 'run' : 'bad';
    var text = { SUCCEEDED: 'Done', RUNNING: 'Running', READY: 'Starting', FAILED: 'Failed', ABORTED: 'Stopped', 'TIMED-OUT': 'Timed out', ABORTING: 'Stopping', 'TIMING-OUT': 'Timing out' }[status] || status;
    return h('span', { class: 'badge-s ' + tone, text: text });
  };
  function actor(id) {
    if (actorCache[id]) return Promise.resolve(actorCache[id]);
    return CB.apify('GET', 'acts/' + encodeURIComponent(id)).then(function (a) { actorCache[id] = a; return a; },
      function () { actorCache[id] = { id: id, name: id, username: '' }; return actorCache[id]; });
  }
  P.citebaseRuns = function (limit) {
    return CB.apify('GET', 'actor-runs?desc=1&limit=' + (limit || 200)).then(function (page) {
      var runs = page.items || [];
      var ids = runs.map(function (r) { return r.actId; }).filter(function (x, i, all) { return all.indexOf(x) === i; }).slice(0, 40);
      return Promise.all(ids.map(actor)).then(function () {
        return runs.filter(function (r) { var a = actorCache[r.actId]; return a && a.username === OWNER; })
          .map(function (r) { var a = actorCache[r.actId]; return Object.assign({}, r, { actorName: a.name, actorTitle: a.title || a.name }); });
      });
    });
  };

  /* ---------- getting started ---------- */
  P.onboarding = function (projects, openNew) {
    var box = h('section', { class: 'onboard' }, h('p', { class: 'muted', text: 'Checking your setup…' }));
    function goto(p, tab) { return function () { location.hash = '#/p/' + encodeURIComponent(p) + '/' + tab; }; }
    Promise.all([
      CB.apify('GET', 'acts/' + OWNER + '~citebase/runs?limit=1&desc=1').then(function (p) { return (p.total || (p.items || []).length) > 0; }, function () { return false; }),
      CB.apify('GET', 'schedules?limit=100').then(function (p) { return (p.items || []).some(function (s) { return /^citebase-/.test(s.name || ''); }); }, function () { return false; })
    ]).then(function (res) {
      var first = projects[0] && projects[0].project;
      var steps = [
        { done: true, title: 'Sign in with Apify', text: 'Done. Your data stays in your own Apify account.' },
        { done: projects.length > 0, title: 'Add your first project', text: 'Your website, brand and competitors. Citebase checks the site straight away.', action: ['New project', openNew] },
        { done: projects.some(function (p) { return p.last_site_check; }), title: 'Check the site', text: 'Can AI crawlers read your pages? A score with a short fix list.', action: first ? ['Open project', goto(first, 'site')] : null },
        { done: projects.some(function (p) { return p.rounds > 0; }), title: 'Run your first AI check', text: 'Ask the AI engines your buying questions and see how often you are recommended.', action: first ? ['Open project', goto(first, 'answers')] : null },
        { done: res[1], title: 'Re-check on a schedule', text: 'A monthly check shows whether your work is paying off.', action: first ? ['Set a schedule', function () { F.schedule(first, function () { location.reload(); }); }] : null },
        { done: res[0], title: 'Connect your assistant (optional)', text: 'Ask Claude, ChatGPT or Cursor for checks in plain words. Same projects as here.', action: ['Show me how', function () { location.hash = '#/account'; }] }];
      var n = steps.filter(function (s) { return s.done; }).length;
      CB.clear(box);
      if (n === steps.length) { box.remove(); return; }
      var bar = h('span', { class: 'fill' });
      bar.style.width = Math.round(n / steps.length * 100) + '%';
      box.appendChild(h('div', { class: 'onboard-head' }, h('div', {}, h('h2', { text: 'Get set up' }), h('p', { text: n + ' of ' + steps.length + ' done' })), h('span', { class: 'track' }, bar)));
      var next = steps.filter(function (s) { return !s.done; })[0];
      box.appendChild(h('ol', { class: 'onboard-list' }, steps.map(function (s) {
        var act = !s.done && s.action ? h('button', { type: 'button', class: 'btn' + (s === next ? '' : ' ghost') + ' small', text: s.action[0], onclick: s.action[1] }) : null;
        return h('li', { class: (s.done ? 'done' : '') + (s === next ? ' next' : '') }, h('span', { class: 'tick', 'aria-hidden': 'true', text: s.done ? '✓' : '' }),
          h('div', {}, h('b', { text: s.title }), h('p', { text: s.text })), act);
      })));
    });
    return box;
  };

  /* ---------- activity ---------- */
  P.activity = function (main, projects) {
    main.appendChild(head('Activity', 'Runs of Citebase and its data checks in your Apify account.'));
    var body = h('div', {}, h('p', { class: 'muted', text: 'Loading your runs…' }));
    main.appendChild(body);
    P.citebaseRuns(200).then(function (runs) {
      CB.clear(body);
      if (!runs.length) { body.appendChild(card('No runs yet', null, h('p', { class: 'empty', text: 'Runs appear here when your assistant or this dashboard uses Citebase.' }))); return; }
      var running = runs.filter(function (r) { return /RUNNING|READY/.test(r.status); }).length;
      var failed = runs.filter(function (r) { return /FAILED|TIMED-OUT|ABORTED/.test(r.status); }).length;
      body.appendChild(h('div', { class: 'stats' }, stat('Runs shown', String(runs.length)), stat('Running now', String(running), running ? 'warn' : null),
        stat('Done', String(runs.length - running - failed), 'good'), stat('Failed or stopped', String(failed), failed ? 'bad' : null)));
      var days = [], counts = {};
      for (var i = 13; i >= 0; i--) { var dd = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10); days.push(dd); counts[dd] = 0; }
      runs.forEach(function (r) { var k = (r.startedAt || '').slice(0, 10); if (k in counts) counts[k]++; });
      body.appendChild(card('Runs per day', 'Last 14 days.', CB.lineChart({ labels: days.map(CB.short), height: 180, width: 820, aria: 'Runs per day',
        max: Math.max(4, Math.max.apply(null, days.map(function (x) { return counts[x]; }))), fmt: function (v) { return v == null ? '–' : String(Math.round(v)); },
        series: [{ name: 'Runs', cls: 'cb', vals: days.map(function (x) { return counts[x]; }) }], tipTitle: function (j) { return CB.day(days[j]); } })));
      var chosen = {};
      var importBtn = h('button', { type: 'button', class: 'btn tiny', text: 'Import selected', disabled: true });
      importBtn.addEventListener('click', function () {
        if (!projects.length) { CB.toast('Create a project first.', true); return; }
        F.importRuns(runs.filter(function (r) { return chosen[r.id]; }), projects, function (p) { location.hash = '#/p/' + encodeURIComponent(p) + '/answers'; });
      });
      function refreshBtn() {
        var n = Object.keys(chosen).filter(function (k) { return chosen[k]; }).length;
        importBtn.disabled = !n; importBtn.textContent = n ? 'Import ' + n + ' selected' : 'Import selected';
      }
      var tbl = CB.table([
        { key: 'pick', label: '', sortable: false, render: function (r) {
          if (r.status !== 'SUCCEEDED' || IMPORTABLE.indexOf(r.actorName) < 0) return h('span', {});
          var c = h('input', { type: 'checkbox', 'aria-label': 'Select this run for import' });
          c.addEventListener('change', function () { chosen[r.id] = c.checked; refreshBtn(); });
          return c; } },
        { key: 'actorTitle', label: 'What ran' },
        { key: 'status', label: 'Status', render: function (r) { return P.badge(r.status); } },
        { key: 'startedAt', label: 'Started', render: function (r) { return P.ago(r.startedAt); } },
        { key: 'dur', label: 'Took', num: true, sortValue: function (r) { return r.finishedAt ? new Date(r.finishedAt) - new Date(r.startedAt) : null; }, render: dur },
        { key: 'open', label: '', sortable: false, render: function (r) {
          return h('a', { class: 'ext', href: 'https://console.apify.com/view/runs/' + encodeURIComponent(r.id), target: '_blank', rel: 'noopener noreferrer', text: 'Open ↗' }); } }],
        runs, { sort: 'startedAt', dir: -1 });
      body.appendChild(card('Recent runs', 'Tick finished AI-answer runs to import them into a project.', tbl, importBtn));
    }, function (e) { failBox(body, e); });
  };

  /* ---------- schedules ---------- */
  function cronWords(c) {
    var p = String(c || '').split(/\s+/), days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    if (p.length !== 5) return c;
    var at = /^\d+$/.test(p[0]) && /^\d+$/.test(p[1]) ? ' at ' + p[1].padStart(2, '0') + ':' + p[0].padStart(2, '0') : '';
    if (p[2] === '*' && p[3] === '*' && /^\d$/.test(p[4])) return 'Every ' + days[+p[4] % 7] + at;
    if (/^\d+$/.test(p[2]) && p[3] === '*' && p[4] === '*') return 'Monthly on day ' + p[2] + at;
    if (p[2] === '*' && p[3] === '*' && p[4] === '*') return 'Every day' + at;
    return c;
  }
  P.schedules = function (main, projects) {
    var add = h('button', { type: 'button', class: 'btn', text: 'New schedule' });
    main.appendChild(head('Schedules', 'Automatic re-checks that run in your Apify account.', add));
    var body = h('div', {}, h('p', { class: 'muted', text: 'Loading your schedules…' }));
    main.appendChild(body);
    function rerender() { CB.clear(body).appendChild(h('p', { class: 'muted', text: 'Loading…' })); load(); }
    add.addEventListener('click', function () {
      if (!projects.length) { CB.toast('Create a project first.', true); return; }
      if (projects.length === 1) { F.schedule(projects[0].project, rerender); return; }
      var sel = h('select', {}, projects.map(function (p) { return h('option', { value: p.project, text: p.brand || p.project }); }));
      F.dialog('Which project?', h('label', { class: 'field' }, h('span', { text: 'Project' }), sel),
        [{ label: 'Cancel', ghost: true }, { label: 'Next', onclick: function (close) { close(); F.schedule(sel.value, rerender); } }]);
    });
    function load() {
      CB.apify('GET', 'schedules?limit=100&desc=1').then(function (page) {
        CB.clear(body);
        var list = page.items || [];
        if (!list.length) { body.appendChild(card('No schedules yet', null, h('p', { class: 'empty', text: 'A monthly re-check shows whether your work is paying off. Create one with "New schedule".' }))); return; }
        body.appendChild(h('div', { class: 'sched-list' }, list.map(function (s) {
          var sw = h('input', { type: 'checkbox', role: 'switch', checked: s.isEnabled, 'aria-label': 'Schedule on' });
          sw.addEventListener('change', function () {
            sw.disabled = true;
            F.toggleSchedule(s, sw.checked).then(function () { sw.disabled = false; CB.toast(sw.checked ? 'Schedule on' : 'Schedule off'); },
              function (e) { sw.disabled = false; sw.checked = !sw.checked; CB.toast(e.message, true); });
          });
          var del = h('button', { type: 'button', class: 'btn tiny', text: 'Delete' });
          del.addEventListener('click', function () { F.deleteSchedule(s, rerender); });
          var n = (s.actions || []).length;
          return h('article', { class: 'sched' + (/^citebase-/.test(s.name || '') ? ' mine' : '') },
            h('div', { class: 'sched-main' }, h('h3', { text: s.title || s.name }), h('p', { text: cronWords(s.cronExpression) + (s.timezone ? ' · ' + s.timezone : '') }),
              h('small', { text: n + (n === 1 ? ' run' : ' runs') + ' each time · next ' + (s.isEnabled ? P.ago(s.nextRunAt) : 'paused') + ' · last ' + P.ago(s.lastRunAt) })),
            h('label', { class: 'switch' }, sw, h('span', { 'aria-hidden': 'true' })),
            h('div', { class: 'sched-tools' }, h('a', { class: 'ext', href: 'https://console.apify.com/schedules/' + encodeURIComponent(s.id), target: '_blank', rel: 'noopener noreferrer', text: 'Open ↗' }), del));
        })));
      }, function (e) { failBox(body, e); });
    }
    load();
  };

  /* ---------- account and connection ---------- */
  P.account = function (main) {
    main.appendChild(head('Account', 'Your Apify account and how to connect your assistant.'));
    var top = h('div', { class: 'grid2 even' }, h('p', { class: 'muted', text: 'Loading…' }));
    main.appendChild(top);
    Promise.all([CB.apify('GET', 'users/me'), CB.apify('GET', 'users/me/limits').catch(function () { return null; })]).then(function (res) {
      var me = res[0], lim = res[1], plan = me.plan || {};
      CB.clear(top);
      var used = lim && lim.current && lim.limits && lim.limits.maxMonthlyUsageUsd ? lim.current.monthlyUsageUsd / lim.limits.maxMonthlyUsageUsd : null;
      var bar = h('span', { class: 'fill' });
      bar.style.width = Math.min(100, Math.round((used || 0) * 100)) + '%';
      top.appendChild(card('Apify account', null, h('div', {}, h('dl', { class: 'facts' },
        h('div', {}, h('dt', { text: 'Signed in as' }), h('dd', { text: me.username })),
        h('div', {}, h('dt', { text: 'Plan' }), h('dd', { text: String(plan.id || '–').toLowerCase().replace(/^\w/, function (c) { return c.toUpperCase(); }) })),
        h('div', {}, h('dt', { text: 'Data kept for' }), h('dd', { text: plan.dataRetentionDays ? plan.dataRetentionDays + ' days' : '–' })),
        h('div', {}, h('dt', { text: 'Billing month' }), h('dd', { text: lim ? CB.short(lim.monthlyUsageCycle.startAt) + ' – ' + CB.short(lim.monthlyUsageCycle.endAt) : '–' }))),
        used == null ? null : h('div', { class: 'usage' }, h('div', { class: 'usage-top' }, h('span', { text: 'Used this month' }), h('b', { text: Math.round(used * 100) + '% of your plan limit' })), h('span', { class: 'track' }, bar)),
        h('p', {}, h('a', { class: 'ext', href: 'https://console.apify.com/billing', target: '_blank', rel: 'noopener noreferrer', text: 'Billing in Apify Console ↗' })))));
      var store = h('div', {}, h('p', { class: 'muted', text: 'Looking for your project store…' }));
      top.appendChild(card('Where your projects live', null, store));
      CB.apify('GET', 'key-value-stores/' + encodeURIComponent(me.username) + '~citebase-projects').then(function (k) {
        CB.clear(store).appendChild(h('p', { text: 'Every project is saved in the store "citebase-projects" in your own account. Nothing is kept anywhere else.' }));
        store.appendChild(h('p', {}, h('a', { class: 'ext', href: 'https://console.apify.com/storage/key-value-stores/' + encodeURIComponent(k.id), target: '_blank', rel: 'noopener noreferrer', text: 'Open the store in Apify Console ↗' })));
      }, function () { CB.clear(store).appendChild(h('p', { text: 'No project store yet. It is created when you save your first project.' })); });
    }, function (e) { failBox(top, e); });
    var guides = [['Claude', ['Settings → Connectors → Add custom connector.', 'Name it Citebase and paste the setup address.', 'Press Connect and sign in with Apify.']],
      ['ChatGPT', ['Settings → Connectors → turn on Developer mode.', 'Create a connector, paste the setup address, choose OAuth.', 'Sign in with Apify.']],
      ['Claude Code', ['Run: claude mcp add --transport http citebase "<setup address>"', 'Type /mcp in Claude Code, pick citebase and sign in.']],
      ['Cursor', ['Open Cursor settings → MCP.', 'Add a server named citebase with the setup address as its url.', 'Sign in with Apify when asked.']]];
    var holder = h('div', {}), seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Assistant' });
    function show(i) {
      Array.prototype.forEach.call(seg.children, function (b, j) { b.setAttribute('aria-pressed', String(i === j)); });
      CB.clear(holder).appendChild(h('ol', { class: 'howto' }, guides[i][1].map(function (t) { return h('li', { text: t }); })));
    }
    guides.forEach(function (g, i) { seg.appendChild(h('button', { type: 'button', text: g[0], onclick: function () { show(i); } })); });
    show(0);
    main.appendChild(card('Connect your assistant', 'Ask for checks in plain words. Everything it saves shows up here.',
      h('div', {}, seg, holder, h('p', { class: 'muted', text: 'Setup address' }), F.copyBox(F.setupAddress))));
  };
})();
