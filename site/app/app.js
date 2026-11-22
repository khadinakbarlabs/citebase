/* Citebase dashboard screens and project navigation. Uses window.CB from core.js. */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h, pct = CB.pct, num = CB.num, day = CB.day, short = CB.short;
  var main = document.getElementById('main'), crumbs = document.getElementById('crumbs'), who = document.getElementById('who');
  var SECTIONS = [
    { tabs: (CB.hasProjectWork ? [['overview', 'Overview'], ['setup', 'Project setup']] : [['overview', 'Overview']]).concat([['connections', 'Connections']]) },
    { label: 'Measure', tabs: [['answers', 'AI answers'], ['questions', 'Questions'], ['site', 'Site'], ['search', 'Search'], ['traffic', 'Traffic']]
      .concat(CB.hasProjectWork ? [['competitors', 'Competitors']] : []) },
    { label: 'Act', tabs: CB.hasProjectWork ? [['evidence', 'Evidence'], ['todo', 'Actions'], ['outreach', 'Outreach']] : [['todo', 'Actions']] }
  ];
  var TABS = SECTIONS.reduce(function (tabs, group) { return tabs.concat(group.tabs); }, []);
  var METRICS = [['recommendation_share', 'Recommended'], ['mentioned_rate', 'Mentioned'], ['cited_rate', 'Cited']];
  function interfaceIcon(name) {
    return CB.s('svg', { class: 'interface-icon', viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' },
      CB.s('use', { href: '../assets/icons.svg#' + name }));
  }
  var sectionIcons = { overview:'overview', setup:'setup', answers:'answers', questions:'questions', site:'site',
    search:'search', traffic:'traffic', competitors:'target', evidence:'evidence', todo:'action', outreach:'outreach', connections:'plug' };
  var metricIcons = { recommendation_share:'results', mentioned_rate:'mention', cited_rate:'sources', site_health:'health' };
  function initialView() { return { metric: 'recommendation_share', engines: null, qFilter: 'all', qTopic: '', qSearch: '' }; }
  var view = initialView(), viewProject = null;
  var mountedProject = null, navigation = 0, access = 'checking';
  var skipLink = document.getElementById('skip-content');
  if (skipLink) skipLink.addEventListener('click', function (event) {
    event.preventDefault(); (mountedProject ? mountedProject.body : main).focus();
  });

  function page() {
    CB.untip(); CB.clear(main); mountedProject = null;
    main.removeAttribute('aria-busy'); main.classList.remove('project-page', 'enter'); void main.offsetWidth; main.classList.add('enter');
  }
  function currentRequest() {
    var revision = navigation, address = location.hash, session = CB.sessionId();
    return function () { return revision === navigation && address === location.hash && session === CB.sessionId(); };
  }
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
    if (!Number.isFinite(dlt)) return h('span', { class: 'flat', text: '–' });
    if (!Math.round(dlt)) return h('span', { class: 'flat', text: '= same' });
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
  function topbar(section) {
    CB.clear(crumbs);
    section = section || 'projects';
    NAV.forEach(function (n) {
      crumbs.appendChild(h('a', { href: n[0], class: 'navlink', 'aria-current': n[1].toLowerCase() === section ? 'page' : null, text: n[1] }));
    });
  }
  function accountBar() {
    CB.clear(who);
    who.appendChild(h('button', { class: 'btn icon', type: 'button', title: 'Reload from Apify', 'aria-label': 'Reload from Apify', text: '↻',
      onclick: function () { CB.refresh(); if (!CB.demo) CB.usage.read(true).catch(function () {}); route(); } }));
    if (CB.demo) {
      who.appendChild(h('span', { class: 'pill', title: 'Sample projects. Sign in with Apify to save changes or start checks.', text: 'Sample data' }));
      if (CB.api) who.appendChild(h('a', { class: 'btn link',
        href: CB.cfg.oauth && CB.cfg.oauth.session === false ? './?signin=1' : '/api/session/?start', text: 'Use my data' }));
      return;
    }
    var signOut = h('button', { class: 'btn link', type: 'button', text: 'Sign out', onclick: async function () {
      signOut.disabled = true;
      try { await CB.signOut(); }
      catch (_) { signOut.disabled = false; CB.toast('Could not sign out. Check your connection and try again.', true); }
    } });
    var account = CB.sessionId();
    var usage = h('a', {class:'usage-shortcut',href:'#/account',text:'Apify usage',title:'View account credits and spending limit'});
    var whoName = h('span', {class:'me'});
    who.append(usage, whoName, signOut);
    function current() { return account === CB.sessionId() && who.contains(signOut); }
    function showName(name) {
      if (!current() || !name) return;
      whoName.textContent = name;
      whoName.title = 'Signed in to Apify as ' + name;
    }
    CB.usage.onUpdate = function (snapshot) {
      if (!current()) return;
      usage.textContent = CB.usage.compact(snapshot);
      showName(snapshot.username);
    };
    // Usage can be unavailable while the account itself is fine. Still show who is signed in.
    CB.usage.read().catch(function () { return CB.whoami().then(showName); });
  }

  /* ---------- signed out ---------- */
  function signedOut(msg) {
    var leaving = access === 'in' || access === 'demo';
    CB.usage.reset();
    access = 'out'; navigation++; clearTimeout(watchTimer); CB.forget();
    view = initialView(); viewProject = null;
    Array.from(document.querySelectorAll('dialog.dlg')).reverse().forEach(function (dialog) {
      if (dialog.open) dialog.close();
      dialog.remove();
    });
    CB.clear(document.getElementById('tip'));
    Array.from(document.querySelectorAll('.toast2')).forEach(function (el) { el.remove(); });
    if (leaving) history.replaceState(null, '', location.pathname);
    page(); CB.clear(crumbs); CB.clear(who); document.title = 'Sign in · Citebase';
    document.getElementById('workspace-guide').hidden = true;
    var signIn = h('button', { class: 'btn big apify', type: 'button', onclick: function () { CB.signIn(); } },
      h('span', { class: 'apify-mark', 'aria-hidden': 'true' }), 'Sign in with Apify');
    // Never send a visitor to Apify on their own: explain first, then let them choose.
    main.appendChild(h('section', { class: 'signin', 'aria-labelledby': 'signin-title' },
      h('div', { class: 'signin-symbol', 'aria-hidden': 'true' }, interfaceIcon('target')),
      h('span', { class: 'eyebrow', text: 'Citebase dashboard' }),
      h('h1', { id: 'signin-title', text: 'Sign in to Citebase' }),
      msg ? h('p', { class: 'signin-notice', role: 'status', text: msg }) : null,
      h('p', { class: 'lead', text: 'Citebase uses your Apify account to keep your projects private.' }),
      h('div', { class: 'row' }, signIn),
      h('p', { class: 'signin-sample' }, 'Just looking? ', h('a', { href: './?demo=1', text: 'See sample' })),
      h('details', { class: 'more' }, h('summary', { text: 'What does signing in allow?' }),
        h('p', { text: 'Apify checks it is you, then sends you back here. Citebase can then read your projects and save the changes you choose. ' +
          (CB.cfg.oauth && CB.cfg.oauth.session === false ? 'This local development session lasts until you close the tab.' : 'This browser remembers your sign-in for up to 90 days. You can sign out any time.') }),
        h('p', { text: 'Opening a project starts Citebase in your Apify account for a few seconds, which uses a little of your Apify platform usage. Paid AI checks require your confirmation.' }))));
    if (leaving) { window.scrollTo(0, 0); signIn.focus({ preventScroll: true }); }
  }
  CB.onSignedOut = signedOut;
  function loading(text, shape) {
    page();
    CB.progress.start();
    var view = CB.loadingView(main, text, shape);
    var gone = new MutationObserver(function () {
      if (view.el.isConnected) return;
      gone.disconnect(); view.stop(); CB.progress.done();
    });
    gone.observe(main, { childList: true });
  }
  function failed(err, retry) {
    if (err.message === 'signed out') return;
    var billingError = CB.usage.errorDetails(err);
    if (billingError) {
      page();
      main.appendChild(h('section', {class:'card'}, h('h2', {text:'Apify billing needs attention'}), billingError,
        h('div',{class:'billing-links'},h('a',{class:'ext',href:'#/account',text:'View account usage'}),
          h('button',{class:'btn tiny',type:'button',text:'Refresh',onclick:function () { CB.usage.read(true).catch(function () {}); retry(); }}))));
      return;
    }
    page(); main.appendChild(CB.errorView(err, retry));
  }
  function banner() {
    if (CB.demo) main.appendChild(h('div', { class: 'banner' }, h('b', { text: 'Sample data. ' }), 'Explore the charts and project workflows. Sign in with Apify to save changes or start checks.'));
  }

  /* ---------- project list ---------- */
  var portfolioView;
  function projectHealth(project) {
    var score = project.health_score;
    return Number.isFinite(score) && score >= 0 && score <= 100 ? score : null;
  }
  function hasSiteAudit(project) { return !!project.last_site_check || projectHealth(project) !== null; }
  function projectNameOrder(a, b) { return String(a.brand || a.project).localeCompare(String(b.brand || b.project)); }
  var portfolioFilters = [
    ['all', 'All projects', function () { return true; }],
    ['due', 'Due for a check', function (p) { return !!(p.due || []).length; }],
    ['unaudited', 'No site audit', function (p) { return !hasSiteAudit(p); }],
    ['unmeasured', 'No AI rounds', function (p) { return !p.rounds; }]
  ];
  var portfolioOrders = {
    priority: function (a, b) { return (b.due || []).length - (a.due || []).length || String(b.updated || '').localeCompare(String(a.updated || '')); },
    audited: function (a, b) { return String(b.last_site_check || '').localeCompare(String(a.last_site_check || '')); },
    health: function (a, b) { return (projectHealth(a) ?? 101) - (projectHealth(b) ?? 101); },
    name: projectNameOrder
  };
  function projectRow(p) {
    var name = p.brand || p.project, due = p.due || [], score = projectHealth(p);
    function section(tab, label) { return h('a', { href: projectUrl(p.project, tab), text: label }); }
    function cell(label, content) {
      return h('td', {}, h('span', { class: 'portfolio-cell-label', 'aria-hidden': 'true', text: label }), content);
    }
    return h('tr', {},
      h('th', { scope: 'row' }, section('overview', name),
        h('span', { class: 'portfolio-domain', text: p.site ? CB.host(p.site) : p.project }),
        due.length ? h('span', { class: 'portfolio-due', title: due.join(' '), text: due.length + (due.length === 1 ? ' check due' : ' checks due') }) : null),
      cell('Site health', score === null ? h('span', { class: 'portfolio-missing', text: hasSiteAudit(p) ? 'Unavailable' : 'Not audited' }) :
        h('span', { class: 'portfolio-score' }, h('b', { text: String(score) }), h('span', { text: '/100' }),
          h('meter', { min: '0', max: '100', low: '60', high: '80', optimum: '100', value: String(score), 'aria-hidden': 'true' }))),
      cell('Last site audit', p.last_site_check ? h('time', { datetime: p.last_site_check, text: day(p.last_site_check) }) :
        h('span', { class: 'portfolio-missing', text: score === null ? 'None saved' : 'Date unavailable' })),
      cell('AI rounds', h('span', { class: 'portfolio-rounds' }, h('b', { text: String(p.rounds || 0) }),
        p.last_round_saved ? h('small', { text: short(p.last_round_saved), title: day(p.last_round_saved) }) : null)),
      h('td', { class: 'portfolio-links' }, h('div', { role: 'group', 'aria-label': 'Open sections for ' + name },
        section('site', 'Site audit'), section('answers', 'AI answers'), section('todo', 'Actions'))));
  }
  function projectDirectory(list) {
    if (!portfolioView || portfolioView.session !== CB.sessionId()) {
      portfolioView = { session: CB.sessionId(), filter: 'all', sort: 'priority', search: '' };
    }
    var state = portfolioView, body = h('tbody', {}), count = h('span', { class: 'portfolio-count', role: 'status' });
    var search = h('input', { type: 'search', placeholder: 'Find a project', 'aria-label': 'Find a project', value: state.search });
    var order = h('select', { 'aria-label': 'Sort projects' }, [
      ['priority', 'Checks due first'], ['audited', 'Latest site audit'], ['health', 'Lowest site health'], ['name', 'Project name A–Z']
    ].map(function (item) { return h('option', { value: item[0], selected: state.sort === item[0], text: item[1] }); }));
    var reset = h('button', { type: 'button', class: 'btn small ghost', text: 'Clear filters', onclick: function () {
      state.search = ''; search.value = ''; state.filter = 'all'; draw(); search.focus();
    } });
    var none = h('div', { class: 'portfolio-no-results', hidden: true }, h('strong', { text: 'No matching projects' }), reset);
    var filterIcons = { all:'portfolio', due:'calendar', unaudited:'site', unmeasured:'answers' };
    var filters = portfolioFilters.map(function (item) {
      return h('button', { type: 'button', onclick: function () { state.filter = item[0]; draw(); } },
        interfaceIcon(filterIcons[item[0]]), h('span', {class:'filter-name', text:item[1]}),
        h('strong', {class:'filter-count', text:String(list.filter(item[2]).length)}));
    });
    var store = window.CitebasePrefs, layout = store ? store.get().projects : 'cards', grid = h('div', { class: 'portfolio-cards' });
    var layoutButtons = [['cards', 'Cards', 'grid'], ['table', 'Table', 'list']].map(function (item) {
      return h('button', { type: 'button', 'aria-pressed': String(layout === item[0]), onclick: function () {
        layout = item[0]; if (store) store.set(Object.assign(store.get(), { projects: layout })); draw();
      } }, CB.journey.icon(item[2]), h('span', { text: item[1] }));
    });
    var table = h('table', { class: 'portfolio-table', role: 'table', 'aria-label': 'Saved projects' },
      h('thead', {}, h('tr', {}, ['Project', 'Site health', 'Last site audit', 'AI rounds', 'Open section'].map(function (label) {
        return h('th', { scope: 'col', text: label });
      }))), body);
    function draw() {
      var term = state.search.trim().toLowerCase(), match = portfolioFilters.find(function (item) { return item[0] === state.filter; })[2];
      var rows = list.filter(function (p) {
        return match(p) && [p.project, p.brand, p.site].join(' ').toLowerCase().includes(term);
      }).sort(function (a, b) { return portfolioOrders[state.sort](a, b) || projectNameOrder(a, b); });
      CB.clear(body); rows.forEach(function (p) { body.appendChild(projectRow(p)); });
      CB.clear(grid); if (rows.length) grid.appendChild(CB.journey.cards(rows, projectUrl, CB.demo ? null : openNew));
      table.hidden = !rows.length || layout !== 'table'; grid.hidden = !rows.length || layout !== 'cards'; none.hidden = !!rows.length;
      layoutButtons.forEach(function (button, i) { button.setAttribute('aria-pressed', String(['cards', 'table'][i] === layout)); });
      count.textContent = rows.length === list.length ? rows.length + (rows.length === 1 ? ' project' : ' projects') : rows.length + ' of ' + list.length + ' projects';
      filters.forEach(function (button, i) { button.setAttribute('aria-pressed', String(portfolioFilters[i][0] === state.filter)); });
    }
    search.addEventListener('input', function () { state.search = search.value; draw(); });
    order.addEventListener('change', function () { state.sort = order.value; draw(); });
    draw();
    return h('section', { class: 'portfolio-directory', 'aria-label': 'Project directory' },
      h('div', { class: 'portfolio-filter-bar', role: 'group', 'aria-label': 'Filter projects' }, filters),
      h('div', { class: 'portfolio-toolbar' }, h('label', { class: 'portfolio-search' },
        CB.s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, CB.s('circle', { cx: 10, cy: 10, r: 6 }), CB.s('path', { d: 'm15 15 5 5' })), search),
        h('label', { class: 'portfolio-sort' }, h('span', { text: 'Sort by' }), order), count,
        h('div', { class: 'portfolio-view', role: 'group', 'aria-label': 'Show projects as' }, layoutButtons)), grid, table, none);
  }
  function overview() {
    var current = currentRequest();
    topbar('projects'); document.title = 'Projects · Citebase';
    loading('Opening Citebase in your Apify account… the first look can take a few seconds.');
    CB.history().then(function (r) {
      if (!current()) return;
      page();
      var list = r.projects || [];
      var newBtn = CB.demo && CB.api ? h('a', { class: 'btn', href: './?signin=1#/new', text: 'Add your own project' }) :
        h('button', { type: 'button', class: 'btn', text: '+ New project', onclick: openNew });
      main.appendChild(h('header', { class: 'portfolio-head' }, h('h1', { text: CB.demo ? 'Sample projects' : 'Your projects' }), list.length ? newBtn : null));
      if (!CB.demo) main.appendChild(CB.guide.workspaceGuide(list, CB.justSignedIn));
      else if (!new URLSearchParams(location.search).has('tour')) main.appendChild(h('p',{class:'sample-tour-link'},h('a',{class:'ext',href:CB.guide.tourUrl,text:'Take the dashboard tour →'})));
      main.appendChild(CB.pages.waiting(list));
      if (!list.length) {
        main.appendChild(h('section', { class: 'portfolio-start' }, h('h2', { text: 'Add your first website' }),
          h('p', { text: 'Create a project to check your site and track how often AI answers recommend your brand.' }), newBtn));
      } else main.appendChild(projectDirectory(list));
      if (!CB.demo) {
        var setup = h('details', { class: 'portfolio-setup' }, h('summary', { text: 'Project setup checklist' }));
        setup.addEventListener('toggle', function () {
          if (setup.open && setup.children.length === 1) setup.appendChild(CB.pages.onboarding(list, openNew));
        });
        main.appendChild(setup);
      }
      if (!CB.demo && location.hash === '#/new') {
        history.replaceState(null, '', location.pathname + location.search + '#/');
        openNew();
      }
    }, function (e) { if (current()) failed(e, route); });
  }
  function openNew() {
    CB.flows.newProject(function (p) { if(CB.hasProjectWork) CB.newSetupProject=p; location.hash = projectUrl(p, CB.hasProjectWork ? 'setup' : 'overview'); }, function () {
      if (access === 'in' && (!location.hash || location.hash === '#/')) route();
    });
  }
  function ring(score) {
    var r = 22, c = 2 * Math.PI * r, v = score == null ? 0 : score;
    var tone = score == null ? 'none' : v >= 80 ? 'good' : v >= 60 ? 'warn' : 'bad';
    return h('div', { class: 'ring ' + tone, title: 'Site health ' + (score == null ? 'not checked' : v + ' of 100') },
      CB.s('svg', { viewBox: '0 0 56 56', 'aria-hidden': 'true' }, CB.s('circle', { class: 'rt', cx: 28, cy: 28, r: r }),
        CB.s('circle', { class: 'rv', cx: 28, cy: 28, r: r, 'stroke-dasharray': (c * v / 100) + ' ' + c, transform: 'rotate(-90 28 28)' })),
      h('span', { text: score == null ? '–' : String(v) }));
  }

  /* ---------- one project ---------- */
  function projectUrl(slug, tab) { return '#/p/' + encodeURIComponent(slug) + '/' + tab; }

  function project(slug, tab) {
    var current = currentRequest();
    if (viewProject !== slug) { viewProject = slug; view = initialView(); }
    if (!mountedProject || mountedProject.slug !== slug) {
      topbar('projects');
      loading('Loading ' + slug + '…', 'project');
    } else main.setAttribute('aria-busy', 'true');
    // The project can render while the independent project switcher is still loading.
    var directory = CB.history().then(function (r) { return r.projects || []; }, function () { return []; });
    CB.history(slug).then(function (d) {
      if (!current()) return;
      if (!mountedProject || mountedProject.data !== d || mountedProject.slug !== slug) {
        page();
        mountedProject = projectShell(slug, d);
      }
      var shell = mountedProject;
      renderSection(shell, tab);
      main.removeAttribute('aria-busy');
      directory.then(function (list) {
        if (current() && shell === mountedProject) projectSwitcher(shell, list);
      });
    }, function (e) { if (current()) failed(e, route); });
  }

  function projectSwitcher(shell, projects) {
    if (shell.projects === projects) return;
    shell.projects = projects;
    CB.clear(shell.switcher);
    if (projects.length < 2) return;
    var select = h('select', { class: 'project-switch', 'aria-label': 'Switch project' },
      h('option', { value: '', selected: true, disabled: true, hidden: true, text: 'Switch project' }),
      projects.map(function (p) { return h('option', { value: p.project, text: p.brand || p.project }); }));
    select.addEventListener('change', function () {
      var target = select.value;
      select.value = '';
      if (target) location.hash = projectUrl(target, shell.tab);
    });
    shell.switcher.appendChild(select);
  }

  function projectTools(slug, d, site, reload) {
    var F = CB.flows, summary = h('summary', { class: 'project-tool-trigger', text: 'Project tools' });
    var list = h('div', { class: 'project-tool-list' }), menu = h('details', { class: 'project-tools' }, summary, list);
    function action(label, run) {
      list.appendChild(h('button', { type: 'button', text: label, onclick: function () {
        menu.open = false; summary.focus(); run();
      } }));
    }
    action('Check site', function () { F.checkSite(slug, site, reload); });
    action('Next steps', function () { F.nextSteps(slug, reload); });
    action('Schedule', function () { F.schedule(slug, reload); });
    action('Connect an AI assistant', function () { location.hash = CB.guide.assistantRoute(slug); });
    action('Share report', function () { F.report(slug); });
    if (CB.hasProjectWork && (d.snapshots || []).some(function (round) { return !round.older_metric; })) {
      action('Prospect audit', function () { F.report(slug, true); });
    }
    action('Export', function () { exportProject(slug, d); });
    menu.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && menu.open) { menu.open = false; summary.focus(); event.preventDefault(); }
    });
    menu.addEventListener('focusout', function (event) {
      if (event.relatedTarget && !menu.contains(event.relatedTarget)) menu.open = false;
    });
    return menu;
  }
  document.addEventListener('pointerdown', function (event) {
    var menu = document.querySelector('.project-tools[open]');
    if (menu && !menu.contains(event.target)) menu.open = false;
  });

  function projectNavigation(slug) {
    var links = [], select = h('select', { 'aria-label': 'Project section' });
    var desktop = h('div', { class: 'project-nav-links' });
    SECTIONS.forEach(function (group) {
      var section = h('div', { class: 'project-nav-group' }, group.label ? h('span', { class: 'project-nav-label', text: group.label }) : null);
      var options = group.label ? h('optgroup', { label: group.label }) : select;
      group.tabs.forEach(function (t) {
        var link = h('a', { href: projectUrl(slug, t[0]), 'data-tab': t[0] }, interfaceIcon(sectionIcons[t[0]]), t[1]);
        links.push(link); section.appendChild(link);
        options.appendChild(h('option', { value: t[0], text: t[1] }));
      });
      if (group.label) select.appendChild(options);
      desktop.appendChild(section);
    });
    select.addEventListener('change', function () { location.hash = projectUrl(slug, select.value); });
    var mobile = h('label', { class: 'project-section-picker' }, h('span', { text: 'Project section' }), select);
    return { node: h('nav', { class: 'project-navigation', 'aria-label': 'Project sections' }, desktop, mobile),
      show: function (tab) {
        links.forEach(function (link) {
          if (link.dataset.tab === tab) {
            link.setAttribute('aria-current', 'page');
            var row = link.closest('.project-nav-links');
            if (row && row.scrollWidth > row.clientWidth) row.scrollLeft = Math.max(0, link.offsetLeft - row.offsetLeft - 16);
          }
          else link.removeAttribute('aria-current');
        });
        select.value = tab;
      } };
  }
  function projectShell(slug, d) {
    var brand = d.brand || {}, site = CB.safeUrl(brand.site || (brand.domain ? 'https://' + brand.domain : ''));
    var name = brand.name || slug, switcher = h('span', { class: 'project-switch-holder' });
    function reload() { CB.refresh(); route(); }
    main.classList.add('project-page');
    main.appendChild(h('header', { class: 'project-masthead' },
      h('div', { class: 'project-identity has-badge' }, CB.journey.badge(name, 'lg'),
        h('h1', { text: name }),
        h('div', { class: 'project-meta' }, site ? h('a', { href: site, rel: 'noopener noreferrer', target: '_blank' }, CB.host(site), h('span', { 'aria-hidden': 'true', text: ' ↗' })) : h('span', { text: slug }), switcher)),
      h('div', { class: 'project-commands' },
        h('button', { type: 'button', class: 'btn start-check', text: 'Run AI check', onclick: function () { CB.flows.aiCheck(slug, d, reload); } }),
        CB.hasProjectWork ? h('a', { class: 'btn ghost resume-setup', href: projectUrl(slug, 'setup'), text: 'Resume project setup' }) : null, projectTools(slug, d, site, reload))));
    var navigation = projectNavigation(slug), body = h('div', { class: 'tabbody', role: 'region', tabindex: '-1' });
    var live = h('div', { class: 'live', role: 'status' });
    main.appendChild(h('div', { class: 'project-layout' }, navigation.node, h('div', { class: 'project-content' }, live, body)));
    return { slug: slug, name: name, data: d, body: body, navigation: navigation, switcher: switcher, live: live };
  }
  function renderSection(shell, tab) {
    var selected = TABS.find(function (t) { return t[0] === tab; }) || TABS[0];
    var contentHadFocus = shell.body.contains(document.activeElement);
    shell.tab = selected[0]; shell.navigation.show(shell.tab);
    main.dataset.projectTab = shell.tab;
    document.title = selected[1] + ' · ' + shell.name + ' · Citebase';
    shell.body.setAttribute('aria-label', selected[1] + ' for ' + shell.name);
    CB.clear(shell.body); CB.untip();
    var views = { setup: CB.onboarding, overview: tabOverview, answers: tabAnswers, questions: tabQuestions, site: tabSite, traffic: tabTraffic, search: function (body, d, slug) { CB.searchUI.render(body, d, slug); },
      todo: CB.hasProjectWork ? CB.workUI.actions : CB.historyUI.actions, evidence: CB.workUI.evidence, outreach: CB.workUI.outreach, connections: CB.connectionsUI.render,
      competitors: function (body, d, slug) { CB.competitorsUI.render(body, d, slug, { rivalsCard: rivalsCard, gapCard: gapCard,
        aiCheck: function () { journeyActions(slug, d).aiCheck(); } }); } };
    views[shell.tab](shell.body, shell.data, shell.slug, route);
    if (contentHadFocus && !new URLSearchParams(location.hash.split('?')[1]).has('record')) shell.body.focus({ preventScroll: true });
    watchRuns(shell.slug, shell.live);
  }

  var watchTimer = null;
  function watchRuns(slug, live) {
    clearTimeout(watchTimer);
    if (!live.isConnected || live.awaitingCheck || !CB.flows.pending().some(function (x) { return x.project === slug; })) return;
    live.awaitingCheck = true;
    CB.flows.watch(slug).then(function (st) {
      live.awaitingCheck = false;
      if (!st || !document.body.contains(live)) return;
      CB.clear(live);
      if (st.imported || st.error) {
        live.appendChild(h('div', { class: 'livebox ' + (st.error ? 'bad' : 'good') }, h('b', { text: st.error ? 'AI check finished with a problem' : 'AI check finished' }),
          h('span', { text: st.error || 'Saved as round "' + st.job.round + '". The charts below are up to date.' })));
        if (st.imported) watchTimer = setTimeout(function () { if (live.isConnected) route(); }, 1200);
        return;
      }
      var bar = h('span', { class: 'fill' }); bar.style.width = Math.round(st.done / st.total * 100) + '%';
      live.appendChild(h('div', { class: 'livebox' }, h('span', { class: 'spin', 'aria-hidden': 'true' }),
        h('div', {}, h('b', { text: 'AI check running: ' + st.done + ' of ' + st.total + ' runs finished' }), h('span', { text: 'Results are saved here automatically when all runs finish. You can leave this page.' })),
        h('span', { class: 'track' }, bar)));
      watchTimer = setTimeout(function () { watchRuns(slug, live); }, 15000);
    }, function (e) {
      live.awaitingCheck = false;
      if (live.isConnected) CB.clear(live).appendChild(h('div', { class: 'livebox bad' }, h('b', { text: 'Could not check the runs' }), h('span', { text: e.message })));
    });
  }

  function exportProject(slug, d) {
    var file = new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' });
    var url = URL.createObjectURL(file), a = h('a', { href: url, download: slug + '-citebase.json' });
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    CB.csv(slug + '-rounds.csv', ['Round', 'Saved', 'Questions', 'Recommended', 'Low', 'High', 'Mentioned', 'Cited'],
      (d.snapshots || []).map(function (x) { return [x.snapshot, x.saved_on, x.prompts, x.recommendation_share, x.rs_low, x.rs_high, x.mentioned_rate, x.cited_rate]; }));
    CB.toast('Downloaded the project (JSON) and its rounds (CSV)');
  }

  /* ---------- project overview ---------- */
  function measured(value) { return typeof value === 'number' && Number.isFinite(value); }
  function rate(value) { return measured(value) && value >= 0 && value <= 1; }
  function roundScope(last) {
    if (!last) return '';
    var engines = (last.engines || Object.keys(last.by_engine || {})).length;
    var parts = [];
    if (measured(last.prompts)) parts.push(num(last.prompts) + (last.prompts === 1 ? ' buying question' : ' buying questions'));
    if (engines) parts.push(num(engines) + (engines === 1 ? ' engine' : ' engines'));
    return parts.join(' · ');
  }
  function snapshotReadings(d) {
    var snaps = d.snapshots || [], audits = d.audits || [], last = snaps[snaps.length - 1], audit = audits[audits.length - 1];
    var name = (d.brand || {}).name || 'the brand', brandDomain = (d.brand || {}).domain || CB.host((d.brand || {}).site);
    var current = last && last.prompts !== 0 ? last : {}, countMethod = !current.older_metric;
    var byEngine = current.by_engine || {};
    var engines = Object.keys(byEngine).filter(function (k) { return rate(byEngine[k].recommendation_share) && byEngine[k].prompts !== 0; })
      .sort(function (a, b) { return byEngine[b].recommendation_share - byEngine[a].recommendation_share; });
    var lead = engines[0], scope = roundScope(last), missing = 'An AI check with saved buying answers will fill in this reading.';
    var hasRec = countMethod && rate(current.recommendation_share);
    var recHeadline = 'Recommendation share is available for this round.';
    if (lead) {
      var completePanel = current.prompts > 0 && engines.length > 1 && engines.length === (current.engines || []).length &&
        engines.every(function (k) { return current.engines.indexOf(k) >= 0 && byEngine[k].prompts === current.prompts; });
      recHeadline = completePanel && byEngine[lead].recommendation_share > byEngine[engines[1]].recommendation_share
        ? CB.engine(lead) + ' recommended ' + name + ' most often this round (' + pct(byEngine[lead].recommendation_share) + ').'
        : CB.engine(lead) + ' recorded a ' + pct(byEngine[lead].recommendation_share) + ' recommendation share.';
    }
    else if (scope) recHeadline = 'Recommendation share across ' + scope.replace(' · ', ' and ') + '.';
    var recDetail = 'For each buying question, Citebase calculates how often an answer recommends the brand. Every question then carries equal weight.';
    if (rate(current.rs_low) && rate(current.rs_high) && current.rs_low <= current.rs_high && countMethod) {
      recDetail += ' The likely range for this round is ' + pct(current.rs_low) + ' to ' + pct(current.rs_high) + '.';
    }

    var own = (d.rivals && d.rivals.round === current.snapshot && d.rivals.brands || []).find(function (b) { return b.you; });
    var named = own && measured(own.answers) && d.rivals.answers > 0
      ? num(own.answers) + ' of ' + num(d.rivals.answers) + ' buying answers named ' + name + '.'
      : 'Mentions count any buying answer that names ' + name + '.';
    var gap = d.citation_gap && d.citation_gap.round === current.snapshot && d.citation_gap.sites && d.citation_gap.sites[0];
    var cited = gap && gap.site && gap.answers_for_rivals_without_you > 0
      ? gap.site + ' appeared in ' + num(gap.answers_for_rivals_without_you) + (gap.answers_for_rivals_without_you === 1 ? ' answer' : ' answers') + ' that named a rival and omitted ' + name + '.'
      : 'Citations count buying answers that link to ' + (brandDomain || 'the project website') + '.';
    var areas = audit && audit.subscores || {};
    var weakest = Object.keys(areas).filter(function (k) { return measured(areas[k]); }).sort(function (a, b) { return areas[a] - areas[b]; })[0];
    var area = weakest && auditArea(weakest);
    var siteHeadline = area ? area + ' scored ' + num(areas[weakest]) + ' out of 100 in the latest site check.'
      : 'Site health comes from the latest saved website check.';
    return [
      { key: 'recommendation_share', label: 'Recommended', value: hasRec ? pct(current.recommendation_share) : '–',
        headline: hasRec ? recHeadline : current.older_metric ? 'This round used an earlier recommendation measure.' : 'No recommendation rate is available yet.',
        detail: hasRec ? recDetail : current.older_metric ? 'Run a new AI check to establish a baseline with the current counting method.' : missing },
      { key: 'mentioned_rate', label: 'Brand mentioned', value: rate(current.mentioned_rate) ? pct(current.mentioned_rate) : '–',
        headline: rate(current.mentioned_rate) ? named : 'No mention rate is available yet.',
        detail: rate(current.mentioned_rate) ? 'Each buying answer counts once. A brand can be mentioned alongside a competitor without receiving a recommendation.' : missing },
      { key: 'cited_rate', label: 'Website cited', value: rate(current.cited_rate) ? pct(current.cited_rate) : '–',
        headline: rate(current.cited_rate) ? cited : 'No citation rate is available yet.',
        detail: rate(current.cited_rate) ? 'Each buying answer counts once if it links to the project website. A mention without a link contributes only to the mention rate.' : missing },
      { key: 'site_health', label: 'Site health', value: audit && measured(audit.health_score) ? num(audit.health_score) : '–',
        unit: audit && measured(audit.health_score) ? '/100' : '', headline: audit && measured(audit.health_score) ? siteHeadline : 'No site score is available yet.',
        detail: audit && measured(audit.health_score) ? 'The site check scores the website out of 100 using its technical, on-page and AI-search checks. Open Site to inspect the individual areas.' : 'Use Check site under Project tools to save the first website check.' }
    ];
  }

  function visibilitySnapshot(d, slug, onSelect) {
    var readings = snapshotReadings(d), snaps = d.snapshots || [], audits = d.audits || [];
    var last = snaps[snaps.length - 1], audit = audits[audits.length - 1], buttons = [];
    var stamp = h('span', { class: 'snapshot-stamp' });
    var headline = h('p', { class: 'reading-headline', 'aria-live': 'polite', 'aria-atomic': 'true' });
    var detail = h('p', {}), about = h('details', { class: 'reading-definition' }, h('summary', { text: 'How it’s measured' }), detail);
    var link = h('a', { class: 'reading-link' }), scope = h('span', { class: 'reading-scope' }), active;
    function select(reading) {
      if (reading === active) return;
      active = reading;
      var site = reading.key === 'site_health';
      buttons.forEach(function (button, i) { button.setAttribute('aria-pressed', String(readings[i] === reading)); });
      stamp.textContent = site ? audit && audit.date ? 'Site check · ' + day(audit.date) : 'No dated site check'
        : last && last.saved_on ? 'AI round · ' + day(last.saved_on) : 'No dated AI round';
      headline.textContent = reading.headline; detail.textContent = reading.detail;
      scope.textContent = site ? audits.length + (audits.length === 1 ? ' saved site check' : ' saved site checks') : roundScope(last);
      link.href = projectUrl(slug, site ? 'site' : 'answers');
      link.textContent = site ? 'Explore site checks →' : 'Explore AI answers →';
      link.onclick = function () { if (!site) { view.metric = reading.key; view.engines = null; } };
      onSelect(reading.key);
    }
    var metrics = h('div', { class: 'snapshot-metrics', role: 'group', 'aria-label': 'Visibility measures' });
    readings.forEach(function (reading) {
      var button = h('button', { type: 'button', class: 'snapshot-metric', 'aria-controls': 'metric-reading overview-trend',
        onclick: function () { select(reading); } }, interfaceIcon(metricIcons[reading.key]), h('span', { class: 'metric-label', text: reading.label }),
        h('strong', { class: 'metric-value' }, reading.value === '–' ? h('span', { class: 'not-yet', text: reading.key === 'site_health' ? 'Not checked yet' : 'Needs an AI check' }) : reading.value,
          reading.unit ? h('small', { text: reading.unit }) : null));
      if (reading.value === '–') button.classList.add('is-empty');
      buttons.push(button); metrics.appendChild(button);
    });
    select(!last && audit ? readings[3] : readings[0]);
    return h('section', { class: 'visibility-snapshot', 'aria-labelledby': 'snapshot-title' },
      h('div', { class: 'snapshot-heading' }, h('h2', { id: 'snapshot-title', text: 'Visibility snapshot' }), stamp),
      metrics, h('div', { id: 'metric-reading', class: 'metric-reading' },
        h('div', { class: 'reading-line' }, headline, link),
        h('div', { class: 'reading-notes' }, scope, about)));
  }

  function trendChart(d, metric) {
    var snaps = d.snapshots || [];
    if (metric === 'site_health') {
      var audits = (d.audits || []).filter(function (a) { return measured(a.health_score); });
      if (!audits.length) return empty('Site health over time', 'Your first saved site check will appear here.');
      if (audits.length === 1) return card('Site health over time', null, h('div', { class: 'single-point' },
        h('b', { text: String(audits[0].health_score) }), h('p', { text: 'Your first site check on ' + day(audits[0].date) +
          '. Check the site again after you fix something and this turns into a trend line.' })));
      var graph = CB.lineChart({ labels: audits.map(function (a) { return short(a.date); }), series: [{
        name: 'Site health', cls: 'cb', vals: audits.map(function (a) { return a.health_score; }) }],
        aria: 'Site health by saved check', max: 100, fmt: num, width: 460, height: 220 });
      var switchView = tableToggle(graph, CB.table([{ key: 'date', label: 'Checked', render: function (a) { return day(a.date); } },
        { key: 'health_score', label: 'Score out of 100', num: true }], audits, { plain: true }));
      return card('Site health over time', 'Score out of 100 for each saved website check.', switchView.body, switchView.button);
    }
    var name = METRICS.find(function (m) { return m[0] === metric; })[1];
    if (!snaps.some(function (s) { return s.prompts !== 0 && rate(s[metric]) && (metric !== 'recommendation_share' || !s.older_metric); })) {
      return empty(name + ' over time', snaps.length ? 'No saved round has this reading under the current measure.' : 'Your first saved buying-question round will appear here.');
    }
    return shareChart(snaps, null, metric, true);
  }

  function journeyActions(slug, d) {
    var brand = d.brand || {}, site = CB.safeUrl(brand.site || (brand.domain ? 'https://' + brand.domain : ''));
    function reload() { CB.refresh(); route(); }
    return { checkSite: function () { CB.flows.checkSite(slug, site, reload); }, aiCheck: function () { CB.flows.aiCheck(slug, d, reload); },
      schedule: function () { CB.flows.schedule(slug, reload); } };
  }
  function tabOverview(body, d, slug) {
    body.appendChild(CB.journey.bar(slug, d, journeyActions(slug, d)));
    var trend = h('div', { class: 'overview-trend', id: 'overview-trend' });
    body.appendChild(visibilitySnapshot(d, slug, function (key) { CB.clear(trend).appendChild(trendChart(d, key)); }));
    if (d.scheduled_alert && d.scheduled_alert.message) {
      body.appendChild(h('aside', { class: 'snapshot-alert' }, h('p', { text: d.scheduled_alert.message }),
        h('a', { href: projectUrl(slug, CB.hasProjectWork ? 'evidence?view=changes' : 'site'), text: 'Review changes →' })));
    }
    if (CB.hasProjectWork) CB.focusUI.mount(body, d, slug);
    else CB.historyUI.focus(body, d, slug);
    var snaps = d.snapshots || [];
    body.appendChild(h('div', { class: 'overview-charts' }, trend, engineBoard(snaps[snaps.length - 1], slug, d)));
    if (!CB.hasProjectWork) return;
    var planningBody = h('div', { class: 'planning-body' }), due = d.due || [];
    var planning = h('details', { class: 'project-planning' }, h('summary', {},
        h('span', { text: 'Project planning' }), h('small', { text: due.length ? due.length + (due.length === 1 ? ' check due' : ' checks due') : 'Brief, schedules and reminders' })), planningBody);
    planning.addEventListener('toggle', function () {
      if (!planning.open || planningBody.childElementCount) return;
      if (due.length) planningBody.appendChild(h('ul', { class: 'planning-due' }, due.map(function (message) { return h('li', { text: message }); })));
      planningBody.appendChild(CB.workUI.brief(slug)); CB.workUI.overview(planningBody, slug, d.questions || []);
    });
    body.appendChild(planning);
  }

  function engineBoard(last, slug, d) {
    if (!last && d) {
      var start = h('button', { type: 'button', class: 'btn' }, CB.journey.icon('spark', 'jr-icon sm'), h('span', { text: 'Run AI check' }));
      start.addEventListener('click', function () { journeyActions(slug, d).aiCheck(); });
      return card('Recommendation by engine', 'How often each AI assistant recommends you.', h('div', {},
        h('div', { class: 'engine-preview', 'aria-label': 'AI assistants Citebase can check' }, CB.ENGINES.map(function (e) {
          return h('span', {}, h('i', { class: 'dot ' + CB.ecls(e[0]), 'aria-hidden': 'true' }), CB.engine(e[0]));
        })), h('p', { class: 'note', text: 'Your first AI check fills this in. You see the price before anything runs.' }), start));
    }
    var be = last && !last.older_metric && last.by_engine || {};
    var keys = Object.keys(be).filter(function (k) { return rate(be[k].recommendation_share) && be[k].prompts !== 0; });
    if (!keys.length) {
      var ctx = (last && last.context) || {};
      keys = Object.keys(ctx).filter(function (k) { return measured(ctx[k].answers); });
      if (!keys.length) return empty('Recommendation by engine', last ? 'This round has no current per-engine rates.' : 'Your first saved AI round will appear here.');
      return card('Answers checked', 'Saved answers per engine in the latest round.', CB.barChart({ aria: 'Answers per engine', labelWidth: 160,
        items: keys.map(function (k) { return { label: CB.engine(k), value: ctx[k].answers, cls: CB.ecls(k) }; }) }));
    }
    keys.sort(function (a, b) { return be[b].recommendation_share - be[a].recommendation_share; });
    return card('Recommendation by engine', 'Select an engine to explore its saved rounds.',
      h('ul', { class: 'engine-readings' }, keys.map(function (k) {
        var value = be[k].recommendation_share;
        return h('li', {}, h('a', { href: projectUrl(slug, 'answers'), 'aria-label': CB.engine(k) + ', ' + pct(value) + ' recommendation share',
          onclick: function () { view.metric = 'recommendation_share'; view.engines = [k]; } },
          h('span', { class: 'engine-reading-name', text: CB.engine(k) }),
          h('progress', { class: CB.ecls(k), value: String(value), max: '1', 'aria-hidden': 'true' }),
          h('span', { class: 'engine-value', text: pct(value) }), h('span', { class: 'engine-arrow', 'aria-hidden': 'true', text: '→' })));
      })));
  }
  function shareChart(snaps, engines, metric, compact) {
    var labels = snaps.map(CB.roundLabel), mname = METRICS.filter(function (m) { return m[0] === metric; })[0][1];
    var recommendation = metric === 'recommendation_share';
    function value(round, record) {
      if (!record || record.prompts === 0 || (recommendation && round.older_metric) || !rate(record[metric])) return null;
      return record[metric];
    }
    function hasRange(s) { return value(s, s) != null && rate(s.rs_low) && rate(s.rs_high) && s.rs_low <= s.rs_high; }
    var series, band = null, leg;
    if (!engines || !engines.length) {
      series = [{ name: 'All engines', cls: 'cb', vals: snaps.map(function (x) { return value(x, x); }) }];
      if (recommendation && snaps.every(hasRange)) band = { lo: snaps.map(function (x) { return x.rs_low; }), hi: snaps.map(function (x) { return x.rs_high; }) };
      leg = legend([['All engines', 'cb']].concat(band ? [['Likely range', 'band']] : []));
    } else {
      series = engines.map(function (k) { return { name: CB.engine(k), cls: CB.ecls(k), vals: snaps.map(function (x) { return value(x, x.by_engine && x.by_engine[k]); }) }; });
      leg = legend(engines.map(function (k) { return [CB.engine(k), CB.ecls(k)]; }));
    }
    var chart = h('div', {}, leg, CB.lineChart({ labels: labels, series: series, band: band, aria: mname + ' by round', width: compact ? 460 : 820, height: compact ? 220 : 300,
      endLabels: !compact && series.length > 1,
      tipTitle: function (i) { return CB.roundName(snaps[i]) + ' · ' + day(snaps[i].saved_on); },
      tipExtra: function (i) { var x = snaps[i]; return (recommendation && !engines && hasRange(x) ? ['Likely range ' + pct(x.rs_low) + '–' + pct(x.rs_high)] : [])
        .concat(measured(x.prompts) ? [num(x.prompts) + ' buying questions'] : []).concat(recommendation && x.older_metric ? ['Earlier counting method'] : []); } }));
    var rows = snaps.map(function (x, i) { var r = { round: CB.roundName(x) + (recommendation && x.older_metric ? ' (earlier method)' : ''), date: day(x.saved_on) }; series.forEach(function (se, j) { r['s' + j] = se.vals[i]; }); return r; });
    var tbl = CB.table([{ key: 'round', label: 'Round' }, { key: 'date', label: 'Saved' }].concat(series.map(function (se, j) {
      return { key: 's' + j, label: se.name, num: true, render: function (r) { return pct(r['s' + j]); } }; })), rows, { plain: true });
    var t = tableToggle(chart, tbl);
    var sub = recommendation ? 'Average recommendation rate across buying questions.' : metric === 'mentioned_rate' ? 'Share of buying answers that name you.' : 'Share of buying answers that link your site.';
    if (recommendation && snaps.some(function (x) { return x.older_metric; })) sub += ' Earlier counting methods are excluded.';
    return card(mname + ' over time', sub, t.body, t.button);
  }

  /* ---------- tab: AI answers ---------- */
  function tabAnswers(body, d) {
    var snaps = d.snapshots || [];
    if (!snaps.length) {
      if (d.fact_check_summary) body.appendChild(factChecksCard(d.project, d.fact_check_summary));
      else body.appendChild(CB.journey.emptyState({ icon: 'spark', title: 'No AI check yet',
        text: 'An AI check asks AI assistants your buying questions and records who they recommend, mention and link to.',
        actions: [{ label: 'Run AI check', icon: 'spark', run: function () { journeyActions(d.project || mountedProject.slug, d).aiCheck(); } },
          { label: 'Add questions first', run: function () { location.hash = projectUrl(mountedProject.slug, 'questions'); } }],
        note: 'You see the price and approve it before anything runs.' }));
      return;
    }
    var have = {};
    snaps.forEach(function (x) { Object.keys(x.by_engine || {}).forEach(function (k) { have[k] = true; }); });
    var engines = CB.ENGINES.map(function (e) { return e[0]; }).filter(function (k) { return have[k]; });
    if (view.engines) { view.engines = view.engines.filter(function (k) { return have[k]; }); if (!view.engines.length) view.engines = null; }
    var holder = h('div', {}), chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Engines' });
    function draw() { CB.clear(holder).appendChild(shareChart(snaps, view.engines, view.metric, false)); }
    var metricPicker = seg(METRICS, view.metric, function (key) {
      view.metric = key;
      Array.from(metricPicker.children).forEach(function (button, i) { button.setAttribute('aria-pressed', String(METRICS[i][0] === key)); });
      draw();
    }, 'Measure');
    function engineSelected(key) { return key ? !!(view.engines && view.engines.includes(key)) : !view.engines; }
    if (!engines.length) chips.appendChild(h('span', { class: 'note', text: 'These rounds have no saved per-engine rates.' }));
    else {
      [''].concat(engines).forEach(function (key) {
        chips.appendChild(h('button', { type: 'button', class: 'chip-btn', 'data-engine': key, 'aria-pressed': String(engineSelected(key)), onclick: function () {
          if (!key) view.engines = null;
          else {
            var list = engineSelected(key) ? view.engines.filter(function (engine) { return engine !== key; }) : (view.engines || []).concat([key]);
            view.engines = list.length ? list : null;
          }
          Array.from(chips.children).forEach(function (button) { button.setAttribute('aria-pressed', String(engineSelected(button.dataset.engine))); });
          draw();
        } }, key ? h('i', { class: 'dot ' + CB.ecls(key) }) : null, key ? CB.engine(key) : 'All engines'));
      });
    }
    body.appendChild(h('div', { class: 'controls' }, metricPicker, chips));
    body.appendChild(holder); draw();
    body.appendChild(compareCard(snaps, engines, d.project));
    body.appendChild(rivalsCard(d.rivals));
    body.appendChild(gapCard(d.citation_gap));
    if (d.fact_check_summary) body.appendChild(factChecksCard(d.project, d.fact_check_summary));
  }
  function factChecksCard(project, facts) {
    var reviewed = facts['true'] + facts['false'] + facts.unverified;
    var message = reviewed ? facts['true'] + ' true · ' + facts['false'] + ' false · ' + facts.unverified + ' unverified'
      : (facts.answers_with_text ? 'Ask your assistant to fact-check what AI said about this brand.' : 'This round has no saved answer wording.');
    var open = facts.answers_with_text ? h('button', { class: 'btn ghost small', type: 'button', text: 'Review answers',
      onclick: function () { CB.flows.factChecks(project, facts.snapshot); } }) : null;
    return card('Fact checks', 'Reviewed claims in the latest round', h('p', { text: message }), open);
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
  function roundCoverage(round) {
    var by = round.by_engine || {}, context = round.context || {};
    var engines = (round.engines || Object.keys(by)).slice().sort();
    return JSON.stringify([round.prompts, engines.map(function (k) {
      var entry = context[k] || {};
      var fields = Object.keys(entry).sort().map(function (field) {
        return [field, Array.isArray(entry[field]) ? entry[field].slice().sort() : entry[field]];
      });
      return [k, by[k] && by[k].prompts, fields];
    })]);
  }
  function compareCard(snaps, engines, project) {
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
      var sameMethod = !A.older_metric && !B.older_metric && A.metric_version === B.metric_version;
      var sameCoverage = roundCoverage(A) === roundCoverage(B);
      if (A === B) verdict = ['info', 'Pick two different rounds.'];
      else if (!sameMethod) verdict = ['warn', 'These rounds use an earlier or different counting method. Their rates are shown separately.'];
      else if (!sameCoverage) verdict = ['warn', 'Question, engine or answer coverage differs between these rounds. Their rates are shown separately.'];
      else if ([A.rs_low, A.rs_high, B.rs_low, B.rs_high].every(rate)) {
        verdict = ['info', 'The recommendation range was ' + pct(A.rs_low) + '–' + pct(A.rs_high) + ' in ' + CB.roundName(A) +
          ' and ' + pct(B.rs_low) + '–' + pct(B.rs_high) + ' in ' + CB.roundName(B) + '.'];
      } else verdict = ['info', 'The table shows the saved rates. A likely range is missing from one or both rounds.'];
      out.appendChild(h('p', { class: 'verdict ' + verdict[0] }, verdict[1],
        CB.hasProjectWork && project && A !== B ? h('a', { class: 'comparison-evidence', href: projectUrl(project, 'evidence') + '?view=changes', text: 'See the latest matched questions →' }) : null));
      var rows = [{ name: 'All engines', a: A.recommendation_share, b: B.recommendation_share, am: A.mentioned_rate, bm: B.mentioned_rate }];
      engines.forEach(function (k) {
        var ea = (A.by_engine || {})[k], eb = (B.by_engine || {})[k];
        if (ea || eb) rows.push({ name: CB.engine(k), a: ea ? ea.recommendation_share : null, b: eb ? eb.recommendation_share : null, am: ea ? ea.mentioned_rate : null, bm: eb ? eb.mentioned_rate : null });
      });
      function chg(x, y) { return A !== B && sameMethod && sameCoverage && rate(x) && rate(y) ? y - x : null; }
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
      var saved = d.panel_prompts || 0;
      body.appendChild(CB.journey.emptyState(saved ? {
        icon: 'questions', title: saved + (saved === 1 ? ' question saved' : ' questions saved'),
        text: 'Run an AI check to see how AI assistants answer each one and whether they recommend you.',
        actions: [{ label: 'Run AI check', icon: 'spark', run: function () { journeyActions(slug, d).aiCheck(); } }]
      } : {
        icon: 'questions', title: 'Add the questions your buyers ask AI',
        text: 'For example “best payroll software for a small team”. Citebase asks AI assistants these questions and checks who they recommend.',
        actions: [{ label: 'Add questions', run: function () { CB.flows.addQuestions(slug, function () { route(); }, suggestionsFrom(d)); } }],
        note: 'Start with 5 to 10. You can change them any time.'
      }));
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
    if (view.qTopic && !topics.includes(view.qTopic)) view.qTopic = '';
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
  function auditArea(key) {
    var text = String(key || '').replace(/[-_]/g,' ');
    return { 'ai search': 'AI search', 'on page': 'On-page', technical: 'Technical' }[text] || text.charAt(0).toUpperCase()+text.slice(1);
  }
  function auditFindings(audit, project) {
    var problems = audit.problems || [], passed = audit.passed || [], counts = audit.counts || {};
    var filter = h('select', { 'aria-label': 'Filter findings' }, h('option', { value: 'all', text: 'All priorities' }),
      h('option', { value: 'fail', text: 'High priority' }), h('option', { value: 'warn', text: 'Warnings' }));
    var list = h('div', { class: 'audit-finding-list' }), description = h('p', { class: 'audit-counts', role: 'status' });
    function finding(item) {
      var links = (item.example_urls || []).map(CB.safeUrl).filter(Boolean).map(function (value) {
        var url = new URL(value);
        if (url.username || url.password) return null;
        return h('a', { href: url.href, target: '_blank', rel: 'noopener noreferrer', text: url.host + url.pathname + url.search });
      }).filter(Boolean);
      return h('details', { class: 'audit-finding' },
        h('summary', {}, h('span', { class: 'audit-level ' + (item.level === 'fail' ? 'high' : 'warn'), text: item.level === 'fail' ? 'High priority' : 'Warning' }),
          h('strong', { text: item.check }), h('small', { text: auditArea(item.area) })),
        h('div', { class: 'audit-detail' }, item.detail ? h('p', { text: item.detail }) : null,
          links.length ? h('div', { class: 'audit-urls' }, h('b', { text: links.length === 1 ? 'Example page' : 'Example pages' }), links) : null));
    }
    function show() {
      var rows = problems.filter(function (item) { return filter.value === 'all' || filter.value === item.level; })
        .sort(function (a, b) { return Number(b.level === 'fail') - Number(a.level === 'fail'); });
      var total = filter.value === 'all' ? (Number.isInteger(counts.fail) && Number.isInteger(counts.warn) ? counts.fail + counts.warn : null) : counts[filter.value];
      description.textContent = total > rows.length ? 'Showing ' + rows.length + ' of ' + total + ' findings.' :
        rows.length + (rows.length === 1 ? ' finding' : ' findings') + (Number.isInteger(counts.pass) ? ' · ' + counts.pass + ' checks passed' : '');
      CB.clear(list);
      rows.forEach(function (item) { list.appendChild(finding(item)); });
      if (!rows.length) list.appendChild(h('p', { class: 'audit-quiet', text: total > 0 ?
        'Individual findings were not included in this saved check.' : 'No recorded problems match this selection.' }));
    }
    filter.addEventListener('change', show); show();
    return h('section', { class: 'audit-findings', 'aria-label': 'Audit findings' },
      h('header', { class: 'audit-findings-head' }, h('div', {}, h('h3', { text: 'Audit findings' }), description),
        h('div', { class: 'audit-finding-tools' }, problems.length ? filter : null,
          problems.length ? h('button', { class: 'btn ghost small', type: 'button', text: 'Plan fixes', onclick: function () {
            CB.flows.nextSteps(project, route);
          } }) : null)), list,
      passed.length ? h('details', { class: 'audit-passed' }, h('summary', { text: 'Passed checks (' + passed.length + ')' }),
        h('ul', {}, passed.map(function (check) { return h('li', { text: check }); }))) : null);
  }
  function tabSite(body, d, project) {
    var brand = d.brand || {}, website = brand.site || (brand.domain ? 'https://' + brand.domain : '');
    var audits = d.audits || [], aud = d.latest_audit || audits[audits.length - 1];
    var run = h('button', { type: 'button', class: 'btn', text: 'Run site audit', onclick: function () {
      CB.flows.checkSite(project, website, route);
    } });
    body.appendChild(h('header', { class: 'audit-heading' }, h('div', {}, h('h2', { text: 'Site audit' }),
      h('p', { text: aud ? 'Last checked ' + day(aud.date) + (Number.isInteger(aud.pages_checked) ?
        ' · ' + aud.pages_checked + (aud.pages_checked === 1 ? ' page checked' : ' pages checked') : '') :
        'Check how search engines and AI assistants can read your website.' })), run));
    if (!aud) {
      body.appendChild(h('section', { class: 'audit-first' }, h('h3', { text: 'No site audit yet' }),
        h('p', { text: 'Your first audit gives you a health score and the pages behind each finding.' })));
      if (CB.hasProjectWork) body.appendChild(CB.workUI.pageReview(project, website));
      return;
    }
    var sub = aud.subscores || {}, keys = Object.keys(sub).filter(function (k) { return Number.isFinite(sub[k]); }).sort(function (a, b) { return sub[a] - sub[b]; });
    var score = projectHealth(aud), prior = audits.length > 1 ? projectHealth(audits[audits.length - 2]) : null;
    var scoreLabel = h('div', { class: 'audit-score' }, ring(score), h('div', {}, h('h3', { text: 'Site health' }),
      h('p', { text: score === null ? 'Score unavailable' : 'Score out of 100' }),
      prior !== null ? h('small', { text: 'Previous score ' + prior }) : null));
    var scores = h('section', { class: 'audit-summary', 'aria-label': 'Site health and area scores' }, scoreLabel,
      keys.length ? h('dl', { class: 'audit-areas' }, keys.map(function (k) {
        return h('div', {}, h('dt', { text: auditArea(k) }), h('dd', {},
          h('meter', { min: 0, max: 100, low: 60, high: 80, optimum: 100, value: String(sub[k]), 'aria-hidden': 'true' }), h('b', { text: String(sub[k]) })));
      })) : null);
    body.appendChild(scores);
    if (aud.status === 'partial') body.appendChild(h('p', { class: 'audit-coverage' }, h('b', { text: 'Partial coverage' }), ' The crawl reached its time limit. These results cover the pages Citebase could read.'));
    if (Array.isArray(aud.problems)) body.appendChild(auditFindings(aud, project));
    else body.appendChild(card('Site findings', 'Open the suggested fixes for the latest saved audit.', null,
      h('button', { type: 'button', class: 'btn ghost small', text: 'See suggested fixes', onclick: function () { CB.flows.nextSteps(project, route); } })));
    var ch = d.site_changes;
    function group(title, items, tone) {
      return h('div', { class: 'change ' + tone }, h('h4', {}, title, h('span', { class: 'count', text: String((items || []).length) })),
        (items || []).length ? h('ul', {}, items.map(function (x) { return h('li', { text: String(x).replace(/_/g, ' ') }); })) : h('p', { class: 'note', text: 'None.' }));
    }
    if (ch) body.appendChild(card('Changes since ' + day(ch.since), ch.note || null, h('div', { class: 'changes' }, group('Fixed', ch.fixed, 'good'), group('New problems', ch['new'], 'bad'), group('Still open', ch.still_open, 'warn'))));
    if (CB.hasProjectWork) body.appendChild(CB.workUI.pageReview(project, website));
    var trend = audits.length > 1 ? CB.lineChart({ labels: audits.map(function (a) { return short(a.date); }), max: 100, height: 150,
      fmt: function (v) { return Number.isFinite(v) ? String(Math.round(v)) : '–'; }, aria: 'Site health by audit', series: [
        { name: 'Site health', cls: 'cb', vals: audits.map(projectHealth) }], tipTitle: function (i) { return day(audits[i].date); } }) : null;
    body.appendChild(card('Audit history', null, h('div', { class: 'audit-history' }, trend, CB.table([{ key: 'date', label: 'Checked', render: function (a) { return day(a.date); } }, { key: 'health_score', label: 'Score', num: true }]
      .concat(keys.map(function (k) { return { key: k, label: k.replace(/-/g, ' '), num: true, render: function (a) { return a.subscores && a.subscores[k] != null ? String(a.subscores[k]) : '–'; } }; })),
      audits.slice().reverse(), { plain: true }))));
  }

  /* ---------- tab: traffic ---------- */
  function niceMax(vals) { var m = Math.max.apply(null, vals.concat([1])), p = Math.pow(10, Math.floor(Math.log10(m))); return Math.ceil(m / p) * p; }
  function googleEntry(slug, reports) {
    if (!CB.googleUI) return null;
    var has = { gsc: !!(reports && reports.gsc), ga4: !!(reports && reports.ga4) };
    if (has.gsc || has.ga4) {
      function state(key, label, mark) {
        return h('span', { class: 'gm-state' + (has[key] ? '' : ' is-off') }, CB.journey.icon(mark, 'g-logo sm'), ' ' + label + (has[key] ? ' connected' : ': not connected'));
      }
      var manage = h('details', { class: 'google-manage' }, h('summary', {}, h('span', { text: 'Google connections' }),
        state('gsc', 'Search Console', 'logo-gsc'), state('ga4', 'Google Analytics', 'logo-ga')));
      manage.addEventListener('toggle', function () { if (manage.open && manage.children.length === 1) manage.appendChild(CB.googleUI.panel(slug)); });
      if (!has.gsc || !has.ga4) { manage.open = true; manage.appendChild(CB.googleUI.panel(slug)); }
      return manage;
    }
    var panel = CB.googleUI.panel(slug);
    panel.classList.add('google-entry');
    var title = panel.querySelector('h3');
    if (title) {
      title.textContent = 'Connect Google to see your real traffic';
      title.insertAdjacentElement('afterend', h('p', { class: 'sub', text: 'Read-only. Citebase imports the last 28 days from Search Console and Google Analytics for this website. You can disconnect any time.' }));
    }
    return panel;
  }
  function tabTraffic(body, d, slug) {
    if (CB.hasProjectWork && !CB.demo) {
      var googleReports = h('div', {class:'setup-work'}), googleSlot = h('div', { class: 'google-slot', id: 'google-connect' });
      body.appendChild(googleSlot); body.appendChild(googleReports);
      CB.work(slug, 'research_get', {}).then(function (research) {
        if (!googleReports.isConnected) return;
        var fp = research.first_party || {}, synced = function (r) { return r && r.provenance === 'google_sync' ? r : null; };
        CB.renderGoogleReports(googleReports, { ga4: fp.ga4 }, true);
        fromGoogle(fp);
        var entry = googleEntry(slug, synced(fp.gsc) || synced(fp.ga4) ? { gsc: synced(fp.gsc), ga4: synced(fp.ga4) } : null);
        if (entry) googleSlot.appendChild(entry);
        googleSlot.appendChild(h('p', { class: 'note' }, h('a', { href: projectUrl(slug, 'connections'), text: 'See every connection for this project' })));
      }).catch(function () {
        if (googleReports.isConnected) googleReports.appendChild(h('p', {class:'note'},
          'Connected Google reports could not be loaded. ', h('a', {href:projectUrl(slug, 'setup'),text:'Review project research'})));
      });
    }
    var row = h('div', { class: 'grid2 even' }), bots = d.ai_bot_visits, tr = d.ai_traffic, aiEmpty = null, searchEmpty = null;
    // With Google connected and no uploaded export, fill these two sections from the Google sync instead of asking to connect.
    function fromGoogle(firstParty) {
      var ga = firstParty && firstParty.ga4, gsc = firstParty && firstParty.gsc;
      if (aiEmpty && aiEmpty.isConnected && ga && ga.provenance === 'google_sync' && (ga.rows || []).length) {
        var gaCard = googleAiCard(ga);
        if (gaCard) aiEmpty.replaceWith(gaCard);
      }
      if (searchEmpty && searchEmpty.isConnected && gsc && gsc.provenance === 'google_sync' && (gsc.rows || []).length) {
        var link = h('a', { href: projectUrl(slug, 'search'), text: 'Open the Search tab' });
        searchEmpty.replaceWith(card('What people search on Google', 'From Search Console, ' + day(gsc.start_date) + ' to ' + day(gsc.end_date) + '.',
          h('p', { class: 'note' }, num(gsc.rows.length) + ' searches showed your site. Trends, positions, pages and quick wins are on the Search tab. ', link)));
      }
    }
    // Visits AI assistants sent, from the Google Analytics sync (server totals, or counted here when the server has none).
    function googleAiCard(ga) {
      var rows = ga.rows || [], label = CB.trafficSources ? CB.trafficSources.label : function () { return {}; };
      var total = typeof ga.all_visits === 'number' ? ga.all_visits : rows.reduce(function (n, r) { return n + (Number(r.sessions) || 0); }, 0);
      var byAssistant = {};
      rows.forEach(function (r) { var a = label(r).assistant; if (a) byAssistant[a] = (byAssistant[a] || 0) + (Number(r.sessions) || 0); });
      var assistants = Array.isArray(ga.assistants) && ga.assistants.length ? ga.assistants : Object.keys(byAssistant)
        .map(function (a) { return { assistant: a, visits: byAssistant[a] }; }).sort(function (x, y) { return y.visits - x.visits; });
      var visits = typeof ga.ai_visits === 'number' ? ga.ai_visits : assistants.reduce(function (n, a) { return n + a.visits; }, 0);
      if (!total) return null;
      return card('Visits from AI assistants', 'From Google Analytics, ' + day(ga.start_date) + ' to ' + day(ga.end_date) + '.', h('div', {},
        h('div', { class: 'bignum' }, h('b', { text: num(visits) }), h('span', { text: ' visits, ' + (visits / total * 100).toFixed(1) + '% of all' })),
        assistants.length > 1 ? CB.barChart({ aria: 'Visits by assistant', labelWidth: 110, items: assistants.map(function (a) { return { label: a.assistant, value: a.visits }; }) })
          : assistants.length ? h('p', { class: 'note', text: 'All from ' + assistants[0].assistant + '.' }) : h('p', { class: 'note', text: 'No visits from AI assistants in this period.' }),
        h('p', { class: 'note', text: 'A floor: people who read an AI answer without clicking are not counted.' })));
    }
    function toGoogle() {
      var slot = document.getElementById('google-connect');
      if (!slot || !slot.firstChild) { location.hash = projectUrl(slug, 'connections'); return; }
      slot.scrollIntoView({ behavior: 'smooth', block: 'start' });
      var first = slot.querySelector('button, summary'); if (first) first.focus({ preventScroll: true });
    }
    var googleAction = CB.hasProjectWork && !CB.demo ? [{ label: 'Connect Google', icon: 'logo-google', run: toGoogle }] : [];
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
    } else row.appendChild(CB.journey.emptyState({ compact: true, icon: 'activity', title: 'AI bot visits',
      text: 'See which AI crawlers read your site. Paste a few days of your website’s access log into a chat and ask Citebase to save it here.' }));
    if (tr && ((tr.by_month && tr.by_month.length) || (tr.assistants && tr.assistants.length))) {
      var months = (tr.by_month || []).slice(-12);
      row.appendChild(card('Visits from AI assistants', 'From your analytics export.', h('div', {},
        h('div', { class: 'bignum' }, h('b', { text: num(tr.ai_visits) }), h('span', { text: ' visits' + (tr.ai_share != null ? ', ' + (tr.ai_share * 100).toFixed(1) + '% of all' : '') })),
        months.length > 1 ? CB.lineChart({ labels: months.map(function (m) { return short(m.month); }), max: niceMax(months.map(function (m) { return m.ai_visits; })), height: 180,
          fmt: function (v) { return v == null ? '–' : num(v); }, aria: 'AI visits by month', series: [{ name: 'Visits from AI', cls: 'cb', vals: months.map(function (m) { return m.ai_visits; }) }],
          tipTitle: function (i) { return months[i].month; }, tipExtra: function (i) { return [num(months[i].all_visits) + ' visits in all']; } }) : null,
        tr.assistants && tr.assistants.length ? CB.barChart({ aria: 'Visits by assistant', labelWidth: 110, items: tr.assistants.map(function (a) { return { label: a.assistant, value: a.visits }; }) }) : null,
        h('p', { class: 'note', text: 'A floor: people who read an AI answer without clicking are not counted.' }))));
    } else row.appendChild(aiEmpty = CB.journey.emptyState({ compact: true, icon: 'traffic', title: 'Visits from AI assistants',
      text: 'People who click through from ChatGPT, Perplexity and others. Comes from Google Analytics.', actions: googleAction }));
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
    } else body.appendChild(searchEmpty = CB.journey.emptyState({ compact: true, icon: 'search', title: 'What people search on Google',
      text: 'The searches that show your site, with views and clicks. Comes from Search Console.', actions: googleAction }));
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
  /* ---------- routing and start ---------- */
  function route(event) {
    if (access !== 'in' && access !== 'demo') return;
    navigation++;
    CB.untip();
    clearTimeout(watchTimer);
    if (event && event.type === 'hashchange') window.scrollTo(0, 0);
    var path = location.hash.split('?')[0];
    CB.guide.renderTour();
    if (path === '#/assistants') {
      page(); topbar('account'); document.title = 'Connect an AI assistant · Citebase';
      var requested = new URLSearchParams(location.hash.split('?')[1] || '').get('project') || '';
      CB.guide.assistantPage(main,/^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/.test(requested) ? requested : '');
      return;
    }
    var m = /^#\/p\/([^/]+)(?:\/(\w+))?\/?$/.exec(path);
    if (m) {
      var slug;
      try { slug = decodeURIComponent(m[1]); } catch (_) { overview(); return; }
      project(slug, m[2] || 'overview'); return;
    }
    var section = (/^#\/(activity|schedules|account)\/?$/.exec(path) || [])[1];
    if (!section) { overview(); return; }
    topbar(section); document.title = section.charAt(0).toUpperCase() + section.slice(1) + ' · Citebase';
    var current = currentRequest();
    function mount(list) {
      if (!current()) return;
      page(); banner();
      var content = h('div', {}); main.appendChild(content);
      CB.pages[section](content, list);
    }
    if (section === 'account') mount();
    else {
      loading('Loading…');
      CB.history().then(function (r) { mount(r.projects || []); }, function (e) { if (current()) failed(e, route); });
    }
  }
  window.addEventListener('hashchange', route);
  CB.startAuth().then(function (state) {
    if (state === 'redirecting') return;
    if (state === 'unavailable') { failed(new Error('Could not check your sign-in. Check your connection and try again.'), function () { location.reload(); }); return; }
    if (state === 'demo' || state === 'in') { access = state; accountBar(); route(); return; }
    // A signed-out visitor always sees the Citebase sign-in screen first, never a surprise Apify page.
    signedOut(state === 'failed' ? 'Sign-in could not be finished. Please try again.' : state === 'cancelled' ? 'Sign-in was cancelled.'
      : state === 'ended' ? CB.endedMessage : '');
  });
})();
