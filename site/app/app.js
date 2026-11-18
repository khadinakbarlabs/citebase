/* Citebase dashboard screens: project list, and per project the tabs Overview, AI answers, Questions, Site,
   Traffic and To-do. Uses window.CB from core.js. */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h, pct = CB.pct, num = CB.num, day = CB.day, short = CB.short;
  var main = document.getElementById('main'), crumbs = document.getElementById('crumbs'), who = document.getElementById('who');
  var TABS = [['overview', 'Overview'], ['answers', 'AI answers'], ['questions', 'Questions'], ['site', 'Site'], ['traffic', 'Traffic'], ['todo', 'To-do']];
  var METRICS = [['recommendation_share', 'Recommended'], ['mentioned_rate', 'Mentioned'], ['cited_rate', 'Cited']];
  var view = { metric: 'recommendation_share', engines: null, qFilter: 'all', qTopic: '', qSearch: '', todoFilter: 'open' };
  var projectsCache = null, currentTab = 'overview';

  function page() { CB.untip(); CB.clear(main); main.classList.remove('enter'); void main.offsetWidth; main.classList.add('enter'); }
  function card(title, sub, body, tools, cls) {
    return h('section', { class: 'card' + (cls ? ' ' + cls : '') },
      h('div', { class: 'card-top' }, h('div', {}, h('h3', { text: title }), sub ? h('p', { class: 'sub', text: sub }) : null), tools ? h('div', { class: 'tools' }, tools) : null),
      body);
  }
  function empty(title, text) { return card(title, null, h('div', { class: 'empty' }, h('p', { text: text }))); }
  function seg(options, value, onpick, label) {
    return h('div', { class: 'seg', role: 'group', 'aria-label': label }, options.map(function (o) {
      return h('button', { type: 'button', 'aria-pressed': String(o[0] === value), text: o[1], onclick: function () { onpick(o[0]); } });
    }));
  }
  function legend(items) { return h('div', { class: 'legend' }, items.map(function (it) { return h('span', {}, h('i', { class: it[1] }), it[0]); })); }
  function arrow(dlt, unit) {
    if (dlt == null || !Math.round(dlt)) return h('span', { class: 'flat', text: '= same' });
    return h('span', { class: 'delta ' + (dlt > 0 ? 'up' : 'down'), text: (dlt > 0 ? '▲ ' : '▼ ') + Math.abs(Math.round(dlt)) + (unit || '') });
  }
  function tableToggle(chart, table) {
    var holder = h('div', {}, chart), on = false;
    var btn = h('button', { class: 'btn tiny', type: 'button', 'aria-pressed': 'false', text: 'Table' });
    btn.addEventListener('click', function () { on = !on; btn.setAttribute('aria-pressed', String(on)); CB.clear(holder).appendChild(on ? table : chart); });
    return { body: holder, button: btn };
  }
  function stat(k, v, tone) { return h('div', { class: 'stat' + (tone ? ' ' + tone : '') }, h('div', { class: 'k', text: k }), h('div', { class: 'v', text: v })); }

  /* ---------- top bar ---------- */
  var NAV = [['#/', 'Projects'], ['#/activity', 'Activity'], ['#/schedules', 'Schedules'], ['#/account', 'Account']];
  function topbar(current, section) {
    CB.clear(crumbs);
    section = section || 'projects';
    NAV.forEach(function (n) {
      crumbs.appendChild(h('a', { href: n[0], class: 'navlink', 'aria-current': n[1].toLowerCase() === section ? 'page' : null, text: n[1] }));
    });
    if (!current) return;
    crumbs.appendChild(h('span', { 'aria-hidden': 'true', text: '/' }));
    if (projectsCache && projectsCache.length > 1) {
      var sel = h('select', { class: 'switch', 'aria-label': 'Switch project' }, projectsCache.map(function (p) {
        return h('option', { value: p.project, selected: p.project === current, text: p.brand || p.project }); }));
      sel.addEventListener('change', function () { location.hash = '#/p/' + encodeURIComponent(sel.value) + '/' + currentTab; });
      crumbs.appendChild(sel);
    } else crumbs.appendChild(h('span', { text: current }));
  }
  function accountBar() {
    CB.clear(who);
    who.appendChild(h('button', { class: 'btn icon', type: 'button', title: 'Reload from Apify', 'aria-label': 'Reload from Apify', text: '↻',
      onclick: function () { CB.refresh(); projectsCache = null; route(); CB.toast('Reloaded'); } }));
    if (CB.demo) {
      who.appendChild(h('span', { class: 'pill', text: 'Sample data' }));
      if (CB.api) who.appendChild(h('a', { class: 'btn link', href: './', text: 'Use my data' }));
      return;
    }
    var signOut = h('button', { class: 'btn link', type: 'button', text: 'Sign out', onclick: function () { signedOut('You are signed out.'); } });
    who.appendChild(signOut);
    CB.whoami().then(function (name) { if (name) who.insertBefore(h('span', { class: 'me', text: name }), signOut); });
  }

  /* ---------- signed out ---------- */
  function signedOut(msg) {
    CB.forget(); page(); CB.clear(crumbs); CB.clear(who);
    main.appendChild(h('div', { class: 'signin' },
      h('div', { class: 'signin-art', 'aria-hidden': 'true' }, h('span'), h('span'), h('span'), h('span'), h('span')),
      h('span', { class: 'eyebrow', text: 'Your dashboard' }),
      h('h1', { text: 'See how AI search treats your brand' }),
      h('p', { class: 'lead', text: msg || 'Sign in with Apify to open every project your assistant saved with Citebase: where AI recommends you, which questions you win, the sites cited instead of you, and what to do next.' }),
      h('div', { class: 'row' }, h('button', { class: 'btn big apify', type: 'button', onclick: CB.signIn }, h('span', { class: 'apify-mark', 'aria-hidden': 'true' }), 'Sign in with Apify')),
      h('p', { class: 'small-note', text: 'No Apify account yet? The sign-in page lets you create one.' }),
      h('ol', { class: 'journey' },
        h('li', {}, h('b', { text: 'Sign in' }), h('span', { text: 'Apify asks you to allow this page.' })),
        h('li', {}, h('b', { text: 'Add a project' }), h('span', { text: 'Your site, brand and competitors.' })),
        h('li', {}, h('b', { text: 'See where you stand' }), h('span', { text: 'Site score, AI answers, next steps.' }))),
      h('ul', { class: 'trust' }, h('li', { text: 'Data stays in your Apify account' }), h('li', { text: 'Nothing stored on our side' }), h('li', { text: 'Sign out any time' })),
      h('details', { class: 'more' }, h('summary', { text: 'What does signing in allow?' }),
        h('p', { text: 'Apify asks you to let this page use your account. The page then reads the store "citebase-projects" in your own account through Citebase, and saves your to-do changes back there. The permission is kept in this browser tab only and ends when you close it or sign out.' }),
        h('p', { text: 'Opening a project starts Citebase in your Apify account for a few seconds, which uses a little of your Apify platform usage. The dashboard never runs paid data checks.' }))));
  }
  CB.onSignedOut = signedOut;
  function loading(text) {
    page();
    main.appendChild(h('div', { class: 'loading' }, h('p', {}, h('span', { class: 'spin', 'aria-hidden': 'true' }), text),
      h('div', { class: 'skeleton', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('i'))));
  }
  function failed(err, retry) {
    if (err.message === 'signed out') return;
    page(); main.appendChild(h('div', { class: 'err' }, h('h3', { text: 'Something went wrong' }), h('p', { text: err.message || String(err) }),
      h('button', { class: 'btn', type: 'button', text: 'Try again', onclick: retry })));
  }
  function banner() {
    if (CB.demo) main.appendChild(h('div', { class: 'banner' }, h('b', { text: 'Sample data. ' }), 'Filters, charts and to-dos all work here. Sign in with Apify to see your own projects.'));
  }

  /* ---------- project list ---------- */
  function overview() {
    topbar(null);
    loading('Opening Citebase in your Apify account… the first look can take a few seconds.');
    CB.history().then(function (r) {
      page(); banner();
      var list = projectsCache = r.projects || [];
      var newBtn = h('button', { type: 'button', class: 'btn', text: '+ New project', onclick: openNew });
      main.appendChild(h('div', { class: 'head' }, h('div', {}, h('h1', { text: 'Your projects' }),
        h('p', { text: list.length ? 'Saved in the "citebase-projects" store in your Apify account.' : 'Nothing saved yet.' })), h('div', { class: 'tools' }, newBtn)));
      if (!CB.demo) main.appendChild(CB.pages.onboarding(list, openNew));
      main.appendChild(CB.pages.waiting(list));
      if (!list.length) {
        main.appendChild(h('section', { class: 'card hero-empty' }, h('h3', { text: 'Start with your website' }),
          h('p', { text: 'Add a project and Citebase checks your site straight away. Then ask the AI engines your buying questions.' }),
          h('button', { type: 'button', class: 'btn big', text: '+ New project', onclick: openNew })));
        return;
      }
      var due = list.reduce(function (n, p) { return n + (p.due || []).length; }, 0), todos = list.reduce(function (n, p) { return n + (p.open_todos || 0); }, 0);
      main.appendChild(h('div', { class: 'stats' }, stat('Projects', String(list.length)), stat('Checks due', String(due), due ? 'warn' : 'good'),
        stat('Open to-dos', String(todos)), stat('AI rounds saved', String(list.reduce(function (n, p) { return n + (p.rounds || 0); }, 0)))));
      var search = h('input', { class: 'search', type: 'search', placeholder: 'Find a project', 'aria-label': 'Find a project' });
      var grid = h('div', { class: 'projects' });
      function draw() {
        CB.clear(grid);
        var t = search.value.trim().toLowerCase();
        list.filter(function (p) { return !t || (p.project + ' ' + (p.brand || '') + ' ' + (p.site || '')).toLowerCase().indexOf(t) >= 0; })
          .sort(function (a, b) { return (b.due || []).length - (a.due || []).length || String(b.updated).localeCompare(String(a.updated)); })
          .forEach(function (p) { grid.appendChild(projectCard(p)); });
        if (!grid.children.length) grid.appendChild(h('p', { class: 'empty', text: 'No project matches.' }));
      }
      search.addEventListener('input', draw);
      if (list.length > 3) main.appendChild(search);
      main.appendChild(grid); draw();
    }, function (e) { failed(e, overview); });
  }
  function openNew() { CB.flows.newProject(function (p) { projectsCache = null; location.hash = '#/p/' + encodeURIComponent(p) + '/overview'; }); }
  function ring(score) {
    var r = 22, c = 2 * Math.PI * r, v = score == null ? 0 : score;
    var tone = score == null ? 'none' : v >= 80 ? 'good' : v >= 60 ? 'warn' : 'bad';
    return h('div', { class: 'ring ' + tone, title: 'Site health ' + (score == null ? 'not checked' : v + ' of 100') },
      CB.s('svg', { viewBox: '0 0 56 56', 'aria-hidden': 'true' }, CB.s('circle', { class: 'rt', cx: 28, cy: 28, r: r }),
        CB.s('circle', { class: 'rv', cx: 28, cy: 28, r: r, 'stroke-dasharray': (c * v / 100) + ' ' + c, transform: 'rotate(-90 28 28)' })),
      h('span', { text: score == null ? '–' : String(v) }));
  }
  function projectCard(p) {
    return h('a', { class: 'pcard', href: '#/p/' + encodeURIComponent(p.project) + '/overview' },
      h('div', { class: 'pc-top' }, h('div', {}, h('h2', { text: p.brand || p.project }), h('p', { class: 'site', text: p.site ? CB.host(p.site) : p.project })), ring(p.health_score)),
      h('dl', {}, h('div', {}, h('dt', { text: 'AI rounds' }), h('dd', { text: String(p.rounds || 0) })),
        h('div', {}, h('dt', { text: 'Open to-dos' }), h('dd', { text: String(p.open_todos || 0) })),
        h('div', {}, h('dt', { text: 'Last round' }), h('dd', { class: 'small', text: p.last_round_saved ? short(p.last_round_saved) : 'none' }))),
      (p.due && p.due.length) ? h('div', { class: 'due' }, h('b', { text: p.due.length === 1 ? '1 check due' : p.due.length + ' checks due' }), h('span', { text: p.due[0] }))
        : h('p', { class: 'ok', text: 'Nothing due · updated ' + day(p.updated) }),
      h('span', { class: 'go', 'aria-hidden': 'true', text: 'Open →' }));
  }

  /* ---------- one project ---------- */
  function project(slug, tab) {
    currentTab = tab;
    topbar(slug);
    loading('Loading ' + slug + '…');
    var need = projectsCache ? Promise.resolve() : CB.history().then(function (r) { projectsCache = r.projects || []; }, function () {});
    Promise.all([CB.history(slug), need]).then(function (res) {
      topbar(slug); page(); banner(); drawProject(slug, res[0], tab);
    }, function (e) { failed(e, function () { project(slug, tab); }); });
  }
  function drawProject(slug, d, tab) {
    var brand = d.brand || {}, snaps = d.snapshots || [], audits = d.audits || [];
    var site = CB.safeUrl(brand.site || (brand.domain ? 'https://' + brand.domain : ''));
    main.appendChild(h('div', { class: 'head' }, h('div', {},
      h('h1', { text: brand.name || slug }),
      h('p', {}, site ? h('a', { href: site, rel: 'noopener noreferrer', target: '_blank', text: CB.host(site) + ' ↗' }) : slug,
        ' · ' + (d.panel_prompts || 0) + ' test questions · ' + snaps.length + (snaps.length === 1 ? ' AI round' : ' AI rounds') + ' · ' + audits.length + (audits.length === 1 ? ' site check' : ' site checks')))));
    var F = CB.flows, reload = function () { CB.refresh(); projectsCache = null; route(); };
    var act = function (label, fn, primary) { return h('button', { type: 'button', class: 'btn' + (primary ? '' : ' ghost') + ' small', text: label, onclick: fn }); };
    main.appendChild(h('div', { class: 'actions' },
      act('Run AI check', function () { F.aiCheck(slug, d, reload); }, true),
      act('Check site', function () { F.checkSite(slug, site, reload); }),
      act('Next steps', function () { F.nextSteps(slug, reload); }),
      act('Schedule', function () { F.schedule(slug, function () { CB.toast('See it under Schedules'); }); }),
      act('Share report', function () { F.report(slug); }),
      act('Export', function () { exportProject(slug, d); })));
    var live = h('div', { class: 'live' });
    main.appendChild(live);
    watchRuns(slug, live);
    var openTodos = (d.todo || []).filter(function (t) { return t.status === 'open'; }).length;
    main.appendChild(h('nav', { class: 'tabs', 'aria-label': 'Project sections' }, TABS.map(function (t) {
      return h('a', { href: '#/p/' + encodeURIComponent(slug) + '/' + t[0], 'aria-current': t[0] === tab ? 'page' : null }, t[1],
        t[0] === 'todo' && openTodos ? h('span', { class: 'badge', text: String(openTodos) }) : null);
    })));
    var body = h('div', { class: 'tabbody' });
    main.appendChild(body);
    var draw = { overview: tabOverview, answers: tabAnswers, questions: tabQuestions, site: tabSite, traffic: tabTraffic, todo: tabTodo }[tab] || tabOverview;
    draw(body, d, slug);
  }

  var watchTimer = null;
  function watchRuns(slug, live) {
    clearTimeout(watchTimer);
    if (!CB.flows.pending().some(function (x) { return x.project === slug; })) return;
    CB.flows.watch(slug).then(function (st) {
      if (!st || !document.body.contains(live)) return;
      CB.clear(live);
      if (st.imported || st.error) {
        live.appendChild(h('div', { class: 'livebox ' + (st.error ? 'bad' : 'good') }, h('b', { text: st.error ? 'AI check finished with a problem' : 'AI check finished' }),
          h('span', { text: st.error || 'Saved as round "' + st.job.round + '". The charts below are up to date.' })));
        if (st.imported) setTimeout(route, 1200);
        return;
      }
      var bar = h('span', { class: 'fill' }); bar.style.width = Math.round(st.done / st.total * 100) + '%';
      live.appendChild(h('div', { class: 'livebox' }, h('span', { class: 'spin', 'aria-hidden': 'true' }),
        h('div', {}, h('b', { text: 'AI check running: ' + st.done + ' of ' + st.total + ' runs finished' }), h('span', { text: 'Results are saved here automatically when all runs finish. You can leave this page.' })),
        h('span', { class: 'track' }, bar)));
      watchTimer = setTimeout(function () { watchRuns(slug, live); }, 15000);
    }, function (e) { CB.clear(live).appendChild(h('div', { class: 'livebox bad' }, h('b', { text: 'Could not check the runs' }), h('span', { text: e.message }))); });
  }

  function exportProject(slug, d) {
    var file = new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(file), a = h('a', { href: url, download: slug + '-citebase.json' });
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    CB.csv(slug + '-rounds.csv', ['Round', 'Saved', 'Questions', 'Recommended', 'Low', 'High', 'Mentioned', 'Cited'],
      (d.snapshots || []).map(function (x) { return [x.snapshot, x.saved_on, x.prompts, x.recommendation_share, x.rs_low, x.rs_high, x.mentioned_rate, x.cited_rate]; }));
    CB.toast('Downloaded the project (JSON) and its rounds (CSV)');
  }

  /* ---------- plain-words summary ---------- */
  function story(d) {
    var snaps = d.snapshots || [], audits = d.audits || [], out = [], name = (d.brand || {}).name || 'you';
    var last = snaps[snaps.length - 1], base = snaps.filter(function (x) { return !x.older_metric; })[0];
    if (last) {
      var line = 'AI recommends ' + name + ' in ' + pct(last.recommendation_share) + ' of buying questions (likely ' + pct(last.rs_low) + '–' + pct(last.rs_high) + ').', tone = 'info';
      if (base && base !== last) {
        var change = Math.round((last.recommendation_share - base.recommendation_share) * 100);
        if (last.rs_low > base.rs_high) { line += ' A clear rise from ' + pct(base.recommendation_share) + ' at the start.'; tone = 'good'; }
        else if (last.rs_high < base.rs_low) { line += ' A clear drop from ' + pct(base.recommendation_share) + ' at the start.'; tone = 'bad'; }
        else line += ' ' + (change >= 0 ? '+' : '') + change + ' points since the start, still inside the normal swing.';
      }
      out.push([tone, line]);
      var be = last.by_engine || {}, keys = Object.keys(be).sort(function (a, b) { return be[b].recommendation_share - be[a].recommendation_share; });
      if (keys.length > 1) out.push(['info', CB.engine(keys[0]) + ' recommends you most (' + pct(be[keys[0]].recommendation_share) + '); ' +
        CB.engine(keys[keys.length - 1]) + ' least (' + pct(be[keys[keys.length - 1]].recommendation_share) + ').']);
    } else out.push(['info', 'No AI recommendation round yet. Ask your assistant for one; it will say it is a paid check and wait for your yes.']);
    var qs = d.questions || [];
    if (qs.length) {
      var won = qs.filter(function (q) { return q.recommended > 0; }).length;
      var gained = qs.filter(function (q) { return q.before && q.before.recommended === 0 && q.recommended > 0; }).length;
      var lost = qs.filter(function (q) { return q.before && q.before.recommended > 0 && q.recommended === 0; }).length;
      out.push([won ? 'info' : 'bad', 'Recommended at least once on ' + won + ' of ' + qs.length + ' questions' + (gained ? ', ' + gained + ' new this round' : '') + (lost ? '; lost ' + lost : '') + '.']);
    }
    var rv = d.rivals;
    if (rv && rv.brands && rv.brands.length > 1) {
      var lead = rv.brands.filter(function (b) { return !b.you; })[0], mine = rv.brands.filter(function (b) { return b.you; })[0];
      if (lead && mine) out.push([lead.share > mine.share ? 'warn' : 'good', lead.share > mine.share
        ? lead.name + ' is named in ' + pct(lead.share) + ' of buying answers; you in ' + pct(mine.share) + '.'
        : 'You lead your rivals: named in ' + pct(mine.share) + ' of buying answers, ' + lead.name + ' in ' + pct(lead.share) + '.']);
      var sm = rv.sentiment || {};
      if (sm.negative) out.push(['bad', sm.negative + ' answers spoke about you negatively. Open AI answers to see where.']);
    }
    var gap = d.citation_gap;
    if (gap && gap.sites && gap.sites.length) out.push(['warn', gap.sites[0].site + ' was cited for rivals ' + gap.sites[0].answers_for_rivals_without_you + ' times without naming you. A fair mention there is the most direct way in.']);
    var a = audits[audits.length - 1];
    if (a) {
      var sub = a.subscores || {}, weak = Object.keys(sub).sort(function (x, y) { return sub[x] - sub[y]; })[0];
      var moved = audits.length > 1 ? a.health_score - audits[0].health_score : null;
      out.push([a.health_score >= 80 ? 'good' : 'warn', 'Site health is ' + a.health_score + ' of 100' + (moved != null ? ' (' + (moved >= 0 ? '+' : '') + moved + ' since the first check)' : '') +
        (weak ? '. Weakest area: ' + weak.replace(/-/g, ' ') + ' (' + sub[weak] + ').' : '.')]);
    }
    var bots = d.ai_bot_visits;
    if (bots && bots.bots) {
      var refused = bots.bots.filter(function (b) { return b.kind === 'answer' && b.requests >= 5 && b.blocked / b.requests >= .5; });
      if (refused.length) out.push(['bad', refused.map(function (b) { return b.bot; }).join(', ') + ' cannot read your site, so that assistant cannot use your pages.']);
    }
    (d.due || []).forEach(function (x) { out.push(['warn', x]); });
    return out;
  }

  /* ---------- tab: overview ---------- */
  function tabOverview(body, d, slug) {
    var snaps = d.snapshots || [], audits = d.audits || [], last = snaps[snaps.length - 1];
    var base = snaps.filter(function (x) { return !x.older_metric; })[0], aud = audits[audits.length - 1];
    body.appendChild(h('div', { class: 'grid2' },
      card('In plain words', null, h('ul', { class: 'story' }, story(d).map(function (s) { return h('li', { class: s[0], text: s[1] }); }))),
      nextSteps(d, slug)));
    function tile(k, v, sub, vals, max, hero) {
      return h('div', { class: 'kpi' + (hero ? ' hero' : '') }, h('div', { class: 'k', text: k }), h('div', { class: 'v', text: v }), h('div', { class: 's' }, sub), CB.spark(vals, max));
    }
    body.appendChild(h('div', { class: 'kpis' },
      tile('Recommended', last ? pct(last.recommendation_share) : '–', last ? [base && base !== last ? arrow((last.recommendation_share - base.recommendation_share) * 100, ' pts') : null,
        ' likely ' + pct(last.rs_low) + '–' + pct(last.rs_high)] : 'no round yet', snaps.map(function (x) { return x.recommendation_share; }), 1, true),
      tile('Mentioned', last ? pct(last.mentioned_rate) : '–', 'answers that name you', snaps.map(function (x) { return x.mentioned_rate; }), 1),
      tile('Cited as a source', last ? pct(last.cited_rate) : '–', 'answers that link your site', snaps.map(function (x) { return x.cited_rate; }), 1),
      tile('Site health', aud ? String(aud.health_score) : '–', aud ? [audits.length > 1 ? arrow(aud.health_score - audits[0].health_score) : null, ' of 100 · ' + short(aud.date)] : 'no check yet',
        audits.map(function (x) { return x.health_score; }), 100)));
    body.appendChild(h('div', { class: 'grid2' },
      snaps.length ? shareChart(snaps, null, 'recommendation_share', true) : empty('Recommended over time', 'Shown after the first AI round.'),
      engineBoard(last, slug)));
  }
  function nextSteps(d, slug) {
    var open = (d.todo || []).filter(function (t) { return t.status === 'open'; }).slice(0, 5);
    var list = h('ul', { class: 'todos compact' });
    open.forEach(function (t) { list.appendChild(todoRow(slug, t, true)); });
    if (!open.length) list.appendChild(h('li', { class: 'none', text: 'No open to-dos. Ask your assistant for next steps on this project.' }));
    return card('Do next', open.length ? 'Tick a step when it is done. It saves to your project.' : null, list,
      h('a', { class: 'btn tiny', href: '#/p/' + encodeURIComponent(slug) + '/todo', text: 'All to-dos' }));
  }
  function engineBoard(last, slug) {
    var be = (last && last.by_engine) || {}, keys = Object.keys(be);
    if (!keys.length) {
      var ctx = (last && last.context) || {};
      keys = Object.keys(ctx);
      if (!keys.length) return empty('By engine', last ? 'Per-engine numbers appear once Citebase is updated in your Apify account.' : 'Shown after the first AI round.');
      return card('Answers checked', 'Answers per engine in the latest round.', CB.barChart({ aria: 'Answers per engine', labelWidth: 160,
        items: keys.map(function (k) { return { label: CB.engine(k), value: ctx[k].answers || 0, cls: CB.ecls(k) }; }) }));
    }
    keys.sort(function (a, b) { return be[b].recommendation_share - be[a].recommendation_share; });
    return card('By engine', 'How often each engine recommends you in the latest round. Click a bar to follow it over time.',
      CB.barChart({ aria: 'Recommended share by engine', labelWidth: 160, fmt: pct, max: 1, items: keys.map(function (k) {
        var e = be[k];
        return { label: CB.engine(k), value: e.recommendation_share, cls: CB.ecls(k),
          tip: ['Recommended: ' + pct(e.recommendation_share) + ' (likely ' + pct(e.rs_low) + '–' + pct(e.rs_high) + ')', 'Mentioned: ' + pct(e.mentioned_rate), 'Cited: ' + pct(e.cited_rate), 'Click to follow over time'],
          onclick: function () { view.engines = [k]; location.hash = '#/p/' + encodeURIComponent(slug) + '/answers'; } };
      }) }));
  }
  function shareChart(snaps, engines, metric, compact) {
    var labels = snaps.map(CB.roundLabel), mname = METRICS.filter(function (m) { return m[0] === metric; })[0][1];
    var series, band = null, leg;
    if (!engines || !engines.length) {
      series = [{ name: 'All engines', cls: 'cb', vals: snaps.map(function (x) { return x[metric]; }) }];
      if (metric === 'recommendation_share') band = { lo: snaps.map(function (x) { return x.rs_low; }), hi: snaps.map(function (x) { return x.rs_high; }) };
      leg = legend([['All engines', 'cb']].concat(band ? [['Likely range', 'band']] : []));
    } else {
      series = engines.map(function (k) { return { name: CB.engine(k), cls: CB.ecls(k), vals: snaps.map(function (x) { return x.by_engine && x.by_engine[k] ? x.by_engine[k][metric] : null; }) }; });
      leg = legend(engines.map(function (k) { return [CB.engine(k), CB.ecls(k)]; }));
    }
    var chart = h('div', {}, leg, CB.lineChart({ labels: labels, series: series, band: band, aria: mname + ' by round', width: compact ? 460 : 820, height: compact ? 220 : 300,
      endLabels: !compact && series.length > 1,
      tipTitle: function (i) { return CB.roundName(snaps[i]) + ' · ' + day(snaps[i].saved_on); },
      tipExtra: function (i) { var x = snaps[i]; return (band ? ['Likely range: ' + pct(x.rs_low) + '–' + pct(x.rs_high)] : []).concat([num(x.prompts) + ' buying questions']).concat(x.older_metric ? ['Counted more loosely: do not compare'] : []); } }));
    var rows = snaps.map(function (x, i) { var r = { round: CB.roundName(x), date: day(x.saved_on) }; series.forEach(function (se, j) { r['s' + j] = se.vals[i]; }); return r; });
    var tbl = CB.table([{ key: 'round', label: 'Round' }, { key: 'date', label: 'Saved' }].concat(series.map(function (se, j) {
      return { key: 's' + j, label: se.name, num: true, render: function (r) { return pct(r['s' + j]); } }; })), rows, { plain: true });
    var t = tableToggle(chart, tbl);
    var sub = metric === 'recommendation_share' ? 'Share of buying questions where an AI recommends you.' : metric === 'mentioned_rate' ? 'Share of buying answers that name you.' : 'Share of buying answers that link your site.';
    return card(mname + ' over time', sub, t.body, t.button);
  }

  /* ---------- tab: AI answers ---------- */
  function tabAnswers(body, d) {
    var snaps = d.snapshots || [];
    if (!snaps.length) { body.appendChild(empty('No AI round yet', 'Ask your assistant for an AI recommendation check on this project. It will say it is a paid check and wait for your yes.')); return; }
    var have = {};
    snaps.forEach(function (x) { Object.keys(x.by_engine || {}).forEach(function (k) { have[k] = true; }); });
    var engines = CB.ENGINES.map(function (e) { return e[0]; }).filter(function (k) { return have[k]; });
    if (view.engines) { view.engines = view.engines.filter(function (k) { return have[k]; }); if (!view.engines.length) view.engines = null; }
    var holder = h('div', {}), segHolder = h('div', {}), chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Engines' });
    function draw() { CB.clear(holder).appendChild(shareChart(snaps, view.engines, view.metric, false)); }
    function drawSeg() { CB.clear(segHolder).appendChild(seg(METRICS, view.metric, function (m) { view.metric = m; drawSeg(); draw(); }, 'Measure')); }
    function drawChips() {
      CB.clear(chips);
      if (!engines.length) { chips.appendChild(h('span', { class: 'note', text: 'Per-engine lines appear once Citebase is updated in your Apify account.' })); return; }
      chips.appendChild(h('button', { type: 'button', class: 'chip-btn', 'aria-pressed': String(!view.engines), text: 'All engines',
        onclick: function () { view.engines = null; drawChips(); draw(); } }));
      engines.forEach(function (k) {
        var on = !!(view.engines && view.engines.indexOf(k) >= 0);
        chips.appendChild(h('button', { type: 'button', class: 'chip-btn', 'aria-pressed': String(on), onclick: function () {
          var list = (view.engines || []).slice(), i = list.indexOf(k);
          if (i >= 0) list.splice(i, 1); else list.push(k);
          view.engines = list.length ? list : null; drawChips(); draw();
        } }, h('i', { class: 'dot ' + CB.ecls(k) }), CB.engine(k)));
      });
    }
    drawSeg(); drawChips();
    body.appendChild(h('div', { class: 'controls' }, segHolder, chips));
    body.appendChild(holder); draw();
    body.appendChild(compareCard(snaps, engines));
    body.appendChild(rivalsCard(d.rivals));
    body.appendChild(gapCard(d.citation_gap));
  }
  function rivalsCard(rv) {
    if (!rv || !rv.brands || rv.brands.length < 2) return empty('You vs rivals', rv ? rv.note : 'Shown after the first AI round. Add competitors to the project so the checks look for them.');
    var chart = CB.barChart({ aria: 'Share of buying answers that name each brand', width: 820, labelWidth: 200, fmt: pct, max: 1,
      items: rv.brands.map(function (b) {
        return { label: b.you ? b.name + ' (you)' : b.name, value: b.share, cls: b.you ? '' : 'dim',
          tip: [b.answers + ' of ' + rv.answers + ' buying answers name ' + (b.you ? 'you' : b.name)].concat(b.before != null ? ['Round before: ' + pct(b.before)] : []) }; }) });
    var tbl = CB.table([{ key: 'name', label: 'Brand', render: function (b) { return b.you ? b.name + ' (you)' : b.name; } },
      { key: 'share', label: 'Share of answers', num: true, render: function (b) { return pct(b.share); } },
      { key: 'answers', label: 'Answers', num: true },
      { key: 'chg', label: 'Change', num: true, sortValue: function (b) { return b.before == null ? null : b.share - b.before; }, render: function (b) { return b.before == null ? '–' : arrow((b.share - b.before) * 100, ' pts'); } }],
      rv.brands, { sort: 'share' });
    var t = tableToggle(chart, tbl);
    var s = rv.sentiment || {}, total = ['positive', 'neutral', 'mixed', 'negative'].reduce(function (n, k) { return n + (s[k] || 0); }, 0);
    var mood = total ? h('div', { class: 'mood' }, h('span', { class: 'k', text: 'How AI talks about you' }),
      h('div', { class: 'moodbar', role: 'img', 'aria-label': 'Sentiment of answers that name you' }, ['positive', 'neutral', 'mixed', 'negative'].filter(function (k) { return s[k]; }).map(function (k) {
        var seg = h('span', { class: 'm-' + k, title: k + ': ' + s[k] + ' answers' }); seg.style.width = (s[k] / total * 100) + '%'; return seg; })),
      h('div', { class: 'legend' }, ['positive', 'neutral', 'mixed', 'negative'].filter(function (k) { return s[k]; }).map(function (k) { return h('span', {}, h('i', { class: 'm-' + k }), k + ' ' + Math.round(s[k] / total * 100) + '%'); }))) : null;
    var pos = rv.avg_position != null ? h('div', { class: 'posbox' }, h('span', { class: 'k', text: 'Average position when named' }), h('b', { text: '#' + rv.avg_position }), h('small', { text: '1 means named first' })) : null;
    return card('You vs rivals', 'Share of buying answers that name each brand (' + (rv.round === 'baseline' ? 'baseline' : 'round ' + rv.round) + '). ' + rv.note,
      h('div', {}, t.body, (mood || pos) ? h('div', { class: 'rivalfacts' }, pos, mood) : null), t.button);
  }
  function compareCard(snaps, engines) {
    if (snaps.length < 2) return empty('Compare two rounds', 'Needs two AI rounds. Re-check in about a month to see what moved.');
    var a = h('select', { 'aria-label': 'First round' }), b = h('select', { 'aria-label': 'Second round' });
    snaps.forEach(function (x, i) {
      a.appendChild(h('option', { value: String(i), selected: i === 0, text: CB.roundName(x) + ' (' + short(x.saved_on) + ')' }));
      b.appendChild(h('option', { value: String(i), selected: i === snaps.length - 1, text: CB.roundName(x) + ' (' + short(x.saved_on) + ')' }));
    });
    var out = h('div', {});
    function draw() {
      CB.clear(out);
      var A = snaps[+a.value], B = snaps[+b.value], verdict;
      if (A === B) verdict = ['info', 'Pick two different rounds.'];
      else if (A.older_metric || B.older_metric) verdict = ['warn', 'One of these rounds was counted more loosely. Do not compare them.'];
      else if (B.rs_low > A.rs_high) verdict = ['good', 'A clear rise: the two likely ranges do not overlap.'];
      else if (B.rs_high < A.rs_low) verdict = ['bad', 'A clear drop: the two likely ranges do not overlap.'];
      else verdict = ['info', 'The likely ranges overlap, so this may still be normal swing. Another round will tell.'];
      out.appendChild(h('p', { class: 'verdict ' + verdict[0], text: verdict[1] }));
      var rows = [{ name: 'All engines', a: A.recommendation_share, b: B.recommendation_share, am: A.mentioned_rate, bm: B.mentioned_rate }];
      engines.forEach(function (k) {
        var ea = (A.by_engine || {})[k], eb = (B.by_engine || {})[k];
        if (ea || eb) rows.push({ name: CB.engine(k), a: ea ? ea.recommendation_share : null, b: eb ? eb.recommendation_share : null, am: ea ? ea.mentioned_rate : null, bm: eb ? eb.mentioned_rate : null });
      });
      function chg(x, y) { return x == null || y == null ? null : y - x; }
      out.appendChild(CB.table([{ key: 'name', label: 'Engine' },
        { key: 'a', label: CB.roundName(A), num: true, render: function (r) { return pct(r.a); } },
        { key: 'b', label: CB.roundName(B), num: true, render: function (r) { return pct(r.b); } },
        { key: 'chg', label: 'Recommended', num: true, sortValue: function (r) { return chg(r.a, r.b); }, render: function (r) { var c = chg(r.a, r.b); return c == null ? '–' : arrow(c * 100, ' pts'); } },
        { key: 'mchg', label: 'Mentioned', num: true, sortValue: function (r) { return chg(r.am, r.bm); }, render: function (r) { var c = chg(r.am, r.bm); return c == null ? '–' : arrow(c * 100, ' pts'); } }], rows, { plain: true }));
    }
    a.addEventListener('change', draw); b.addEventListener('change', draw); draw();
    return card('Compare two rounds', 'Pick any two rounds to see what moved, overall and per engine.', out, h('div', { class: 'pickers' }, a, h('span', { text: 'vs' }), b));
  }
  function gapCard(gap) {
    if (!(gap && gap.sites && gap.sites.length)) return empty('Cited for rivals, not you', gap ? gap.note : 'Shown after the first AI round.');
    var chart = CB.barChart({ aria: 'Sites cited for rivals', width: 820, labelWidth: 200, items: gap.sites.map(function (x) {
      return { label: x.site, value: x.answers_for_rivals_without_you, cls: 'warnbar', tip: [x.answers_for_rivals_without_you + ' answers named a rival and not you', 'Engines: ' + x.engines.map(CB.engine).join(', ')]
        .concat(x.rivals_named.length ? ['Rivals: ' + x.rivals_named.join(', ')] : []).concat(x.example_questions[0] ? ['e.g. "' + x.example_questions[0] + '"'] : []) }; }) });
    var tbl = CB.table([{ key: 'site', label: 'Site' }, { key: 'answers_for_rivals_without_you', label: 'For rivals', num: true },
      { key: 'answers_that_recommend_you', label: 'Recommend you', num: true }, { key: 'eng', label: 'Engines', sortable: false, render: function (r) { return r.engines.map(CB.engine).join(', '); } },
      { key: 'rv', label: 'Rivals named', sortable: false, render: function (r) { return r.rivals_named.join(', '); } }], gap.sites, { sort: 'answers_for_rivals_without_you' });
    var t = tableToggle(chart, tbl);
    return card('Cited for rivals, not you', 'Sites AI cited in answers that named a rival and left you out (' + (gap.round === 'baseline' ? 'baseline' : 'round ' + gap.round) + '). Your outreach list.',
      h('div', {}, t.body, h('p', { class: 'note', text: gap.note })), t.button);
  }

  /* ---------- tab: questions ---------- */
  function tabQuestions(body, d, slug) {
    var qs = d.questions || [];
    if (!qs.length) {
      body.appendChild(card('Test questions', null, h('div', { class: 'empty' },
        h('p', { text: (d.panel_prompts || 0) ? d.panel_prompts + ' questions saved. Run an AI check to see how each one does.' : 'No questions yet. Add the buying questions your customers ask an AI, then run an AI check.' }),
        (d.panel_prompts || 0) ? h('button', { type: 'button', class: 'btn', text: 'Run AI check', onclick: function () { CB.flows.aiCheck(slug, d, function () { CB.refresh(); route(); }); } })
          : h('button', { type: 'button', class: 'btn', text: 'Add questions', onclick: function () { CB.flows.addQuestions(slug, function () { route(); }, suggestionsFrom(d)); } }))));
      return;
    }
    var engines = CB.ENGINES.map(function (e) { return e[0]; }).filter(function (k) { return qs.some(function (q) { return q.engines && q.engines[k]; }); });
    var groups = {
      all: ['All', function () { return true; }],
      won: ['Recommended', function (q) { return q.recommended > 0; }],
      never: ['Not yet', function (q) { return q.recommended === 0; }],
      gained: ['New wins', function (q) { return q.before && q.before.recommended === 0 && q.recommended > 0; }],
      lost: ['Lost', function (q) { return q.before && q.before.recommended > 0 && q.recommended === 0; }] };
    var topics = qs.map(function (q) { return q.topic; }).filter(function (t, i, all) { return t && all.indexOf(t) === i; }).sort();
    var lostN = qs.filter(groups.lost[1]).length;
    body.appendChild(h('div', { class: 'stats' }, stat('Questions', String(qs.length)), stat('Recommended at least once', qs.filter(groups.won[1]).length + ' of ' + qs.length, 'good'),
      stat('New wins', String(qs.filter(groups.gained[1]).length)), stat('Lost', String(lostN), lostN ? 'bad' : null)));
    var filterBar = h('div', { class: 'chips', role: 'group', 'aria-label': 'Show' });
    var search = h('input', { class: 'search', type: 'search', placeholder: 'Search questions', 'aria-label': 'Search questions', value: view.qSearch });
    var topicSel = h('select', { 'aria-label': 'Topic' }, h('option', { value: '', text: 'All topics' }), topics.map(function (t) { return h('option', { value: t, selected: t === view.qTopic, text: t }); }));
    var cols = [{ key: 'question', label: 'Question', sortValue: function (q) { return q.question.toLowerCase(); }, render: function (q) {
        return h('div', { class: 'qtext' }, h('span', { text: q.question }), q.topic ? h('span', { class: 'tag', text: q.topic }) : null); } },
      { key: 'rate', label: 'Recommended', num: true, sortValue: function (q) { return q.answers ? q.recommended / q.answers : 0; }, render: function (q) {
        var bar = h('span', { class: 'fill' }); bar.style.width = Math.round((q.answers ? q.recommended / q.answers : 0) * 100) + '%';
        return h('div', { class: 'meter', title: q.recommended + ' of ' + q.answers + ' answers' }, h('span', { class: 'track' }, bar), h('b', { text: q.recommended + '/' + q.answers })); } }]
      .concat(engines.map(function (k) { return { key: k, label: CB.engine(k).replace('Google AI ', 'AI '), num: true,
        sortValue: function (q) { var e = q.engines[k]; return e && e.answers ? e.recommended / e.answers : -1; }, render: function (q) {
          var e = q.engines[k];
          if (!e) return h('span', { class: 'cell none', title: 'Not asked', text: '·' });
          var share = e.answers ? e.recommended / e.answers : 0, lvl = !e.recommended ? 0 : share >= .67 ? 3 : share >= .34 ? 2 : 1;
          return h('span', { class: 'cell l' + lvl, title: CB.engine(k) + ': recommended in ' + e.recommended + ' of ' + e.answers + ', named in ' + e.named + ', linked in ' + e.linked, text: e.recommended + '/' + e.answers }); } }; }))
      .concat([{ key: 'chg', label: 'Change', num: true, sortValue: function (q) { return q.before ? q.recommended - q.before.recommended : null; }, render: function (q) {
        if (!q.before) return h('span', { class: 'flat', text: 'new' });
        if (q.before.recommended === 0 && q.recommended > 0) return h('span', { class: 'delta up', text: '★ new win' });
        if (q.before.recommended > 0 && q.recommended === 0) return h('span', { class: 'delta down', text: '✕ lost' });
        return arrow(q.recommended - q.before.recommended); } }]);
    var table = CB.table(cols, [], { sort: 'rate', empty: 'No question matches these filters.' });
    function rows() {
      var t = view.qSearch.trim().toLowerCase();
      return qs.filter(groups[view.qFilter][1]).filter(function (q) { return (!view.qTopic || q.topic === view.qTopic) && (!t || q.question.toLowerCase().indexOf(t) >= 0); });
    }
    function drawFilters() {
      CB.clear(filterBar);
      Object.keys(groups).forEach(function (k) {
        filterBar.appendChild(h('button', { type: 'button', class: 'chip-btn', 'aria-pressed': String(view.qFilter === k), onclick: function () { view.qFilter = k; drawFilters(); table.redraw(rows()); } },
          groups[k][0], h('span', { class: 'count', text: String(qs.filter(groups[k][1]).length) })));
      });
    }
    search.addEventListener('input', function () { view.qSearch = search.value; table.redraw(rows()); });
    topicSel.addEventListener('change', function () { view.qTopic = topicSel.value; table.redraw(rows()); });
    drawFilters(); table.redraw(rows());
    var exportBtn = h('button', { class: 'btn tiny', type: 'button', text: 'Download CSV', onclick: function () {
      CB.csv(slug + '-questions.csv', ['Question', 'Topic', 'Answers', 'Recommended', 'Recommended before'].concat(engines.map(CB.engine)),
        rows().map(function (q) { return [q.question, q.topic, q.answers, q.recommended, q.before ? q.before.recommended : ''].concat(engines.map(function (k) { var e = q.engines[k]; return e ? e.recommended + '/' + e.answers : ''; })); }));
    } });
    body.appendChild(card('Every test question', 'Latest round. Hover a cell for details, click a column to sort.',
      h('div', {}, h('div', { class: 'controls' }, filterBar, h('div', { class: 'row' }, topics.length > 1 ? topicSel : null, search)), table,
        h('p', { class: 'note', text: 'Darker cells: more answers recommended you. Questions you never win are the best ideas for new pages.' })), exportBtn));
  }

  function suggestionsFrom(d) {
    var sd = d.search_demand || {}, seen = {};
    return [].concat(sd.test_in_ai || [], (sd.gaps || []).map(function (g) { return g.query; }), (sd.top_questions || []).map(function (g) { return g.query; }))
      .filter(function (q) { var k = String(q).toLowerCase(); if (seen[k]) return false; seen[k] = 1; return true; }).slice(0, 30);
  }

  /* ---------- tab: site ---------- */
  function tabSite(body, d) {
    var audits = d.audits || [];
    if (!audits.length) { body.appendChild(empty('No site check yet', 'Ask your assistant to check the site with this project name. It saves the result here.')); return; }
    var aud = audits[audits.length - 1], sub = aud.subscores || {}, keys = Object.keys(sub), prev = audits.length > 1 ? audits[audits.length - 2].subscores || {} : {};
    body.appendChild(h('div', { class: 'grid2 even' },
      card('Health score', audits.length > 1 ? 'One point per site check.' : 'Checked ' + day(aud.date) + '. Re-check after fixes to see the trend.',
        h('div', { class: 'health' }, ring(aud.health_score), audits.length > 1 ? CB.lineChart({ labels: audits.map(function (a) { return short(a.date); }), max: 100, height: 180,
          fmt: function (v) { return v == null ? '–' : String(Math.round(v)); }, aria: 'Site health by check', series: [{ name: 'Health', cls: 'cb', vals: audits.map(function (a) { return a.health_score; }) }],
          tipTitle: function (i) { return day(audits[i].date); } }) : null)),
      keys.length ? card('Areas', 'Latest scores out of 100. Under 70 needs work.', CB.barChart({ aria: 'Sub-scores', labelWidth: 120, max: 100, items: keys.map(function (k) {
        return { label: k.replace(/-/g, ' '), value: sub[k], cls: sub[k] < 70 ? 'badbar' : sub[k] < 80 ? 'warnbar' : 'goodbar', tip: [sub[k] + ' of 100'].concat(prev[k] != null ? ['Before: ' + prev[k]] : []) }; }) }))
        : empty('Areas', 'No sub-scores saved.')));
    var ch = d.site_changes;
    function group(title, items, tone) {
      return h('div', { class: 'change ' + tone }, h('h4', {}, title, h('span', { class: 'count', text: String((items || []).length) })),
        (items || []).length ? h('ul', {}, items.map(function (x) { return h('li', { text: String(x).replace(/_/g, ' ') }); })) : h('p', { class: 'note', text: 'None.' }));
    }
    if (ch) body.appendChild(card('What changed since ' + day(ch.since), null, h('div', { class: 'changes' }, group('Fixed', ch.fixed, 'good'), group('New problems', ch['new'], 'bad'), group('Still open', ch.still_open, 'warn'))));
    body.appendChild(card('All site checks', null, CB.table([{ key: 'date', label: 'Checked', render: function (a) { return day(a.date); } }, { key: 'health_score', label: 'Score', num: true }]
      .concat(keys.map(function (k) { return { key: k, label: k.replace(/-/g, ' '), num: true, render: function (a) { return a.subscores && a.subscores[k] != null ? String(a.subscores[k]) : '–'; } }; })),
      audits.slice().reverse(), { plain: true })));
  }

  /* ---------- tab: traffic ---------- */
  function niceMax(vals) { var m = Math.max.apply(null, vals.concat([1])), p = Math.pow(10, Math.floor(Math.log10(m))); return Math.ceil(m / p) * p; }
  function tabTraffic(body, d) {
    var row = h('div', { class: 'grid2 even' }), bots = d.ai_bot_visits, tr = d.ai_traffic;
    if (bots && bots.bots && bots.bots.length) {
      var chart = CB.barChart({ aria: 'AI bot requests', labelWidth: 140, items: bots.bots.slice(0, 10).map(function (b) {
        var refused = b.requests && b.blocked / b.requests >= .5;
        return { label: b.bot, value: b.requests, cls: refused ? 'badbar' : b.kind === 'training' ? 'dim' : '',
          tip: [b.owner + ' · ' + (b.kind === 'answer' ? 'fetches pages to answer questions' : 'collects training data'), num(b.requests) + ' requests, ' + num(b.blocked) + ' refused', num(b.pages) + ' pages read'] }; }) });
      var t = tableToggle(chart, CB.table([{ key: 'bot', label: 'Bot' }, { key: 'owner', label: 'Owner' }, { key: 'kind', label: 'Kind' },
        { key: 'requests', label: 'Requests', num: true }, { key: 'blocked', label: 'Refused', num: true }], bots.bots, { sort: 'requests' }));
      row.appendChild(card('AI bot visits', 'From your server log, ' + day(bots.period && bots.period.from) + ' to ' + day(bots.period && bots.period.to) + '.',
        h('div', {}, legend([['Answers questions', 'cb'], ['Training only', 'dimk'], ['Mostly refused', 'badk']]), t.body,
          bots.findings && bots.findings.length ? h('ul', { class: 'story compact' }, bots.findings.slice(0, 4).map(function (f) { return h('li', { class: 'warn', text: f }); })) : null), t.button));
    } else row.appendChild(empty('AI bot visits', 'Paste a few days of your website\'s access log into a chat and ask Citebase to save it to this project.'));
    if (tr && ((tr.by_month && tr.by_month.length) || (tr.assistants && tr.assistants.length))) {
      var months = (tr.by_month || []).slice(-12);
      row.appendChild(card('Visits from AI assistants', 'From your analytics export.', h('div', {},
        h('div', { class: 'bignum' }, h('b', { text: num(tr.ai_visits) }), h('span', { text: ' visits' + (tr.ai_share != null ? ', ' + (tr.ai_share * 100).toFixed(1) + '% of all' : '') })),
        months.length > 1 ? CB.lineChart({ labels: months.map(function (m) { return short(m.month); }), max: niceMax(months.map(function (m) { return m.ai_visits; })), height: 180,
          fmt: function (v) { return v == null ? '–' : num(v); }, aria: 'AI visits by month', series: [{ name: 'Visits from AI', cls: 'cb', vals: months.map(function (m) { return m.ai_visits; }) }],
          tipTitle: function (i) { return months[i].month; }, tipExtra: function (i) { return [num(months[i].all_visits) + ' visits in all']; } }) : null,
        tr.assistants && tr.assistants.length ? CB.barChart({ aria: 'Visits by assistant', labelWidth: 110, items: tr.assistants.map(function (a) { return { label: a.assistant, value: a.visits }; }) }) : null,
        h('p', { class: 'note', text: 'A floor: people who read an AI answer without clicking are not counted.' }))));
    } else row.appendChild(empty('Visits from AI assistants', 'Export "Traffic acquisition" from Google Analytics and ask Citebase to save it to this project.'));
    body.appendChild(row);
    var sd = d.search_demand;
    if (sd && (sd.gaps || sd.top_questions)) {
      var list = (sd.gaps && sd.gaps.length) ? sd.gaps : (sd.top_questions || []);
      body.appendChild(card('What people search on Google', num(sd.clicks) + ' clicks from ' + num(sd.impressions) + ' views (Search Console).' + (sd.gaps && sd.gaps.length ? ' These searches see you but rarely pick you: write a page that answers each one.' : ''),
        h('div', {}, CB.table([{ key: 'query', label: 'Search' }, { key: 'impressions', label: 'Views', num: true, render: function (x) { return num(x.impressions); } },
          { key: 'clicks', label: 'Clicks', num: true, render: function (x) { return num(x.clicks); } }, { key: 'ctr', label: 'Click rate', num: true, render: function (x) { return (x.ctr * 100).toFixed(1) + '%'; } },
          { key: 'position', label: 'Position', num: true }], list, { sort: 'impressions' }),
          sd.test_in_ai && sd.test_in_ai.length ? h('div', { class: 'testlist' }, h('p', { class: 'note', text: 'Worth adding to your AI test questions:' }),
            h('div', { class: 'chipline' }, sd.test_in_ai.slice(0, 12).map(function (t) { return h('span', { class: 'chip', text: t }); }))) : null)));
    } else body.appendChild(empty('What people search on Google', 'Export Search Console, Performance, Queries, and ask Citebase to save it to this project.'));
    var rk = d.ranks;
    if (rk && rk.positions && rk.positions.length) {
      body.appendChild(card('Search positions', rk.top_10 + ' of ' + rk.keywords + ' keywords in the top 10 · ' + day(rk.saved_on) + (rk.previous_date ? ' vs ' + day(rk.previous_date) : ''),
        CB.table([{ key: 'keyword', label: 'Keyword' }, { key: 'engine', label: 'Where' },
          { key: 'now', label: 'Now', num: true, render: function (m) { return m.now == null ? 'not found' : String(m.now); } },
          { key: 'before', label: 'Before', num: true, render: function (m) { return m.checked_before ? (m.before == null ? 'not found' : String(m.before)) : 'new'; } },
          { key: 'moved_up_by', label: 'Move', num: true, render: function (m) { return m.moved_up_by ? arrow(m.moved_up_by) : '–'; } }], rk.positions, { sort: 'moved_up_by' })));
    }
  }

  /* ---------- tab: to-do (managed here, saved to the project in the user's account) ---------- */
  function todoRow(slug, t, compact) {
    var li = h('li', { class: 'todo-row ' + t.status });
    var box = h('input', { type: 'checkbox', checked: t.status === 'done', 'aria-label': 'Done: ' + t.step });
    box.addEventListener('change', function () { setStatus(slug, t, box.checked ? 'done' : 'open', li); });
    li.appendChild(h('label', { class: 'todo-main' }, box, h('span', { class: 'step', text: t.step })));
    if (!compact) {
      li.appendChild(h('span', { class: 'when', text: t.updated ? short(t.updated) : '' }));
      if (t.status === 'skipped') li.appendChild(h('button', { class: 'btn tiny', type: 'button', text: 'Reopen', onclick: function () { setStatus(slug, t, 'open', li); } }));
      else if (t.status === 'open') li.appendChild(h('button', { class: 'btn tiny', type: 'button', text: 'Skip', onclick: function () { setStatus(slug, t, 'skipped', li); } }));
    }
    return li;
  }
  function setStatus(slug, t, status, li) {
    var before = t.status;
    t.status = status; li.className = 'todo-row ' + status + ' saving';
    CB.saveTodo(slug, [{ step: t.step, status: status }]).then(function () {
      CB.toast(status === 'done' ? 'Marked done' : status === 'skipped' ? 'Skipped' : 'Reopened');
      projectsCache = null; route();
    }, function (e) {
      t.status = before; li.className = 'todo-row ' + before; CB.toast('Not saved: ' + e.message, true);
      var box = li.querySelector('input'); if (box) box.checked = before === 'done';
    });
  }
  function tabTodo(body, d, slug) {
    var todo = d.todo || [], counts = { open: 0, done: 0, skipped: 0 };
    todo.forEach(function (t) { counts[t.status] = (counts[t.status] || 0) + 1; });
    var total = todo.length, prog = h('span', { class: 'fill' });
    prog.style.width = Math.round((total ? counts.done / total : 0) * 100) + '%';
    var list = h('ul', { class: 'todos' }), filter = h('div', {});
    function draw() {
      CB.clear(list);
      var shown = todo.filter(function (t) { return view.todoFilter === 'all' || t.status === view.todoFilter; });
      shown.forEach(function (t) { list.appendChild(todoRow(slug, t, false)); });
      if (!shown.length) list.appendChild(h('li', { class: 'none', text: view.todoFilter === 'open' ? 'Nothing open. Nice work.' : 'Nothing here.' }));
    }
    function drawFilter() {
      CB.clear(filter).appendChild(seg([['open', 'Open ' + counts.open], ['done', 'Done ' + counts.done], ['skipped', 'Skipped ' + counts.skipped], ['all', 'All']],
        view.todoFilter, function (v) { view.todoFilter = v; drawFilter(); draw(); }, 'Show'));
    }
    var input = h('input', { type: 'text', maxlength: '200', placeholder: 'Add a step, e.g. "Write a page about payroll for nonprofits"', 'aria-label': 'New step' });
    var form = h('form', { class: 'addtodo' }, input, h('button', { class: 'btn', type: 'submit', text: 'Add' }));
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var step = input.value.trim();
      if (!step) return;
      if (todo.some(function (t) { return t.step.toLowerCase() === step.toLowerCase(); })) { CB.toast('That step is already on the list.', true); return; }
      input.disabled = true;
      CB.saveTodo(slug, [{ step: step, status: 'open' }]).then(function () { CB.toast('Added'); view.todoFilter = 'open'; projectsCache = null; route(); },
        function (er) { input.disabled = false; CB.toast('Not saved: ' + er.message, true); });
    });
    drawFilter(); draw();
    body.appendChild(h('div', { class: 'grid2' },
      card('To-do', 'Saved to this project in your Apify account, so your assistant sees the same list.',
        h('div', {}, h('div', { class: 'progress', title: counts.done + ' of ' + total + ' done' }, h('span', { class: 'track' }, prog), h('b', { text: counts.done + ' of ' + total + ' done' })),
          filter, list, form)),
      h('div', { class: 'stack' },
        card('Due', null, (d.due || []).length ? h('ul', { class: 'story compact' }, d.due.map(function (x) { return h('li', { class: 'warn', text: x }); })) : h('p', { class: 'ok', text: 'Nothing is due.' })),
        card('Logged changes', 'Changes made to win answers. Each is compared with the next round.',
          (d.experiments || []).length ? h('ol', { class: 'timeline' }, d.experiments.slice().reverse().map(function (e) {
            return h('li', {}, h('span', { class: 'when', text: day(e.date) }), h('b', { text: e.action }), e.mechanism ? h('span', { class: 'why', text: e.mechanism }) : null); }))
            : h('p', { class: 'note', text: 'Ask your assistant to log a change when you make one, e.g. "log that I published the pricing page".' })))));
  }

  /* ---------- routing and start ---------- */
  function route() {
    CB.untip();
    clearTimeout(watchTimer);
    var m = /^#\/p\/([^/]+)(?:\/(\w+))?/.exec(location.hash);
    if (m) { project(decodeURIComponent(m[1]), m[2] || 'overview'); return; }
    var page = (/^#\/(activity|schedules|account)/.exec(location.hash) || [])[1];
    if (!page) { overview(); return; }
    topbar(null, page);
    page === 'account' ? (function () { CB.untip(); CB.clear(main); banner(); CB.pages.account(main); })() : withProjects(function (list) {
      CB.untip(); CB.clear(main); banner(); CB.pages[page](main, list); });
  }
  function withProjects(fn) {
    loading('Loading…');
    (projectsCache ? Promise.resolve(projectsCache) : CB.history().then(function (r) { projectsCache = r.projects || []; return projectsCache; }))
      .then(fn, function (e) { failed(e, route); });
  }
  window.addEventListener('hashchange', route);
  CB.startAuth().then(function (state) {
    if (state === 'demo' || state === 'in') { accountBar(); route(); return; }
    signedOut(state === 'failed' ? 'Sign-in could not be finished. Please try again.' : state === 'cancelled' ? 'Sign-in was cancelled.' : '');
  });
})();
