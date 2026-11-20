/* Citebase dashboard pages built on Apify's API: Activity (runs), Schedules, Account, and the getting-started
   checklist. Billing figures are read directly from the signed-in Apify account. */
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
    var box = h('section', { class: 'onboard' });
    var select = h('select', { 'aria-label': 'Project to set up' }, projects.map(function (p) {
      return h('option', { value: p.project, text: (p.brand || p.project) + (p.brand ? ' · ' + p.project : '') });
    }));
    var steps = h('div', {});
    box.appendChild(h('div', { class: 'onboard-head' }, h('h2', { text: 'Get set up' }), projects.length > 1 ? select : null));
    box.appendChild(steps);
    var revision = 0;
    function render() {
      var request = ++revision;
      var project = projects.find(function (p) { return p.project === select.value; }) || projects[0];
      function tab(name) { return function () { location.hash = '#/p/' + encodeURIComponent(project.project) + '/' + name; }; }
      function show(schedule) {
        if (request !== revision) return;
        var items = [{ done: true, title: 'Sign in with Apify' },
          { done: !!project, title: project ? 'Project added · ' + project.project : 'Add a project', action: ['New project', openNew] },
          { done: project && project.last_site_check, title: 'Check the site', action: project && ['Open site check', tab('site')] },
          { done: project && project.rounds > 0, title: 'Save an AI check', action: project && ['Open answers', tab('answers')] },
          { done: schedule === true, title: 'Schedule project rechecks (optional)', text: schedule === null ? 'Schedule status unverified.' : '',
            action: project && ['Review project schedule', function () { F.schedule(project.project, render); }] },
          { done: false, title: 'Connect your assistant (optional)', text: 'Connection unverified.',
            action: ['Connection instructions', function () { location.hash = CB.guide.assistantRoute(project && project.project); }] }];
        var count = items.slice(0, 4).filter(function (s) { return s.done; }).length;
        CB.clear(steps).appendChild(h('p', { class: 'muted', text: count + ' of 4 setup steps complete' }));
        steps.appendChild(h('ol', { class: 'onboard-list' }, items.map(function (s) {
          return h('li', { class: s.done ? 'done' : '' }, h('span', { class: 'tick', 'aria-hidden': 'true', text: s.done ? '✓' : '' }),
            h('div', {}, h('b', { text: s.title }), s.text ? h('p', { text: s.text }) : null),
            !s.done && s.action ? h('button', { type: 'button', class: 'btn ghost small', text: s.action[0], onclick: s.action[1] }) : null);
        })));
      }
      show(null);
      if (project) {
        var enabled = CB.hasProjectWork
          ? CB.work(project.project, 'schedule_list', {}).then(function (r) { return (r.schedules || []).some(function (s) { return s.enabled === true; }); })
          : CB.historyUI.schedulesFor([project]).then(function (rows) { return rows.some(function (s) { return s.isEnabled; }); });
        enabled.then(show, function () { show(null); });
      }
    }
    select.addEventListener('change', render);
    render();
    return box;
  };

  P.importState = function (run, projects) {
    if (run.status !== 'SUCCEEDED' || !run.defaultDatasetId || IMPORTABLE.indexOf(run.actorName) < 0) {
      return { status: 'unrelated', projects: [] };
    }
    var imported = projects.filter(function (p) { return (p.imported_dataset_ids || []).indexOf(run.defaultDatasetId) >= 0; });
    var parent = (run.meta || {}).actorRunId;
    var assigned = projects.filter(function (p) { return parent && Object.hasOwn(p.attributed_runs || {}, parent); });
    if (assigned.length === 1) return { status: imported.includes(assigned[0]) ? 'imported' : 'awaiting_import', projects: [assigned[0].project] };
    if (imported.length) return { status: 'imported', projects: imported.map(function (p) { return p.project; }) };
    return { status: 'unassigned', projects: [] };
  };

  P.waiting = function (projects) {
    var box = h('div', {});
    if (!projects.length || CB.demo) return box;
    P.citebaseRuns(100).then(function (runs) {
      var states = runs.map(function (r) { return P.importState(r, projects); });
      var ready = states.filter(function (s) { return s.status === 'awaiting_import'; }).length;
      var unassigned = states.filter(function (s) { return s.status === 'unassigned'; }).length;
      if (ready || unassigned) box.appendChild(h('div', { class: 'livebox' }, h('div', {}, h('b', { text: 'Recent AI checks to review' }),
        h('span', { text: ready + ' linked to a project and awaiting import · ' + unassigned + ' without a recorded project match' })),
        h('a', { class: 'btn small', href: '#/activity', text: 'Review in Activity' })));
    }, function () { box.appendChild(h('p', { class: 'muted', text: 'Recent import status is unavailable.' })); });
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
        var selected = runs.filter(function (r) { return chosen[r.id]; });
        var assigned = selected.map(function (r) { return P.importState(r, projects); }).filter(function (s) { return s.status === 'awaiting_import'; });
        var choices = projects.filter(function (p) { return assigned.every(function (s) { return s.projects[0] === p.project; }); });
        if (!choices.length) { CB.toast('Import runs for one project at a time.', true); return; }
        F.importRuns(selected, choices, function (p) { location.hash = '#/p/' + encodeURIComponent(p) + '/answers'; });
      });
      function refreshBtn() {
        var n = Object.keys(chosen).filter(function (k) { return chosen[k]; }).length;
        importBtn.disabled = !n; importBtn.textContent = n ? 'Import ' + n + ' selected' : 'Import selected';
      }
      var tbl = CB.table([
        { key: 'pick', label: '', sortable: false, render: function (r) {
          var state = P.importState(r, projects);
          if (state.status === 'imported' || state.status === 'unrelated') return h('span', {});
          var c = h('input', { type: 'checkbox', 'aria-label': 'Select this run for import' });
          c.addEventListener('change', function () { chosen[r.id] = c.checked; refreshBtn(); });
          return c; } },
        { key: 'actorTitle', label: 'What ran' },
        { key: 'import', label: 'Project import', sortable: false, render: function (r) {
          var s = P.importState(r, projects);
          if (s.status === 'imported') return 'Imported · ' + s.projects.join(', ');
          if (s.status === 'awaiting_import') return 'Awaiting import · ' + s.projects[0];
          return s.status === 'unassigned' ? 'Unassigned' : '–';
        } },
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
  P.schedules = function (main, projects) {
    return CB.hasProjectWork ? CB.workUI.schedules(main, projects) : CB.historyUI.schedules(main, projects);
  };

  /* ---------- account and connection ---------- */
  P.account = function (main) {
    main.appendChild(head('Account', 'Your Apify account and how to connect your assistant.'));
    var top = h('div', { class: 'grid2 even' }, h('p', { class: 'muted', text: 'Loading…' }));
    main.appendChild(top);
    CB.usage.read().then(function (account) {
      CB.clear(top);
      if (CB.prepaid.available()) top.appendChild(CB.prepaid.card(account));
      top.appendChild(card('Apify account', null, h('div', {}, h('dl', { class: 'facts' },
        h('div', {}, h('dt', { text: 'Signed in as' }), h('dd', { text: account.username || 'Unavailable' })),
        h('div', {}, h('dt', { text: 'Plan' }), h('dd', { text: account.plan || 'Unavailable' })),
        h('div', {}, h('dt', { text: 'Data kept for' }), h('dd', { text: account.retention == null ? 'Unavailable' : account.retention + ' days' })),
        h('div', {}, h('dt', { text: 'Usage cycle' }), h('dd', { text: account.start && account.end ? CB.short(account.start) + ' – ' + CB.short(account.end) : 'Unavailable' }))))));
      top.appendChild(card('Apify usage and credits', 'Monthly figures from your Apify account, in USD.', CB.usage.summary(account)));
      top.appendChild(card('Where your projects live', null, h('div', {},
        h('p', { text: 'Citebase saves projects, private answers and shareable reports in your Apify account.' }),
        h('p', {}, h('a', { class: 'ext', href: 'https://console.apify.com/storage/key-value-stores',
          target: '_blank', rel: 'noopener noreferrer', text: 'Open storage in Apify Console ↗' })))));
    }, function (e) { failBox(top, e); });
    main.appendChild(card('Connect your assistant', 'Open a saved project from the AI assistant you already use.',
      h('a',{class:'btn ghost',href:CB.guide.assistantRoute(),text:'Connect an AI assistant'})));
  };
})();
