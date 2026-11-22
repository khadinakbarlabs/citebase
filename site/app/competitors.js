/* Citebase project Competitors section: who you compete with, their websites, how often AI picks
   them over you, and where they get cited when you do not. Add or pause competitors in place.
   Reads onboarding_get (competitor list) and research_get (traffic estimates); saves through onboarding_save.
   Text is always set with textContent. */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h;
  function J() { return CB.journey; }

  function domainOf(row) {
    var d = String(row.domain || '').trim();
    if (!d && /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(row.name || '')) d = row.name;
    return d.toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/.*$/, '');
  }
  function sourceLabel(row) {
    if (row.source === 'user') return 'You added';
    if (row.source === 'project') return 'Saved';
    return 'Suggested';
  }
  function stat(label, value, hint, tone) {
    return h('div', { class: 'cx-stat' + (tone ? ' is-' + tone : '') }, h('span', { class: 'cx-k', text: label }),
      h('b', { class: 'cx-v', text: value }), hint ? h('span', { class: 'cx-hint', text: hint }) : null);
  }
  // Competitor rows from setup, with the names the project already tracks as a fallback.
  function rowsFrom(state, d) {
    var list = (state && state.competitors) || [];
    if (list.length) return list;
    return ((d.brand || {}).competitors || []).map(function (name) { return { name: name, selected: true, source: 'project' }; });
  }

  function render(body, d, slug, tools) {
    var share = {}, you = null, rv = d.rivals, traffic = {}, state = null;
    (rv && rv.brands || []).forEach(function (b) { if (b.you) you = b; else share[String(b.name).toLowerCase()] = b; });
    var head = h('section', { class: 'cx-hero', 'aria-label': 'Competition at a glance' });
    var listCard = h('section', { class: 'card cx-list', 'aria-labelledby': 'cx-list-title' });
    var status = h('p', { class: 'cx-status', role: 'status', 'aria-live': 'polite' });
    var aiBlock = h('div', { class: 'cx-ai' }), steps = h('ol', { class: 'cx-steps', 'aria-label': 'Competitor setup' });
    body.append(head, steps, listCard, aiBlock);

    function drawHero(rows) {
      var tracked = rows.filter(function (r) { return r.selected; });
      var rivals = (rv && rv.brands || []).filter(function (b) { return !b.you; }).sort(function (a, b) { return b.share - a.share; });
      var top = rivals[0];
      var gap = d.citation_gap && d.citation_gap.sites ? d.citation_gap.sites.length : null;
      var withSite = tracked.filter(function (r) { return domainOf(r); }).length;
      var stepList = [
        ['Add competitors', tracked.length ? tracked.length + ' tracked' : 'Who buyers compare you with', tracked.length > 0],
        ['Add their websites', tracked.length ? withSite + ' of ' + tracked.length + ' have a website' : 'Lets Citebase match citations', tracked.length > 0 && withSite === tracked.length],
        ['Compare in AI', rivals.length ? 'Latest AI check compared you' : 'Run an AI check to compare', rivals.length > 0]];
      var firstOpen = stepList.findIndex(function (x) { return !x[2]; });
      steps.replaceChildren.apply(steps, stepList.map(function (x, i) {
        var li = h('li', { class: 'cx-step' + (x[2] ? ' is-done' : i === firstOpen ? ' is-now' : '') },
          h('span', { class: 'cx-step-dot', 'aria-hidden': 'true' }, x[2] ? J().icon('check', 'jr-icon sm') : String(i + 1)),
          h('span', { class: 'cx-step-text' }, h('b', { text: x[0] }), h('span', { text: x[1] })),
          h('span', { class: 'jr-sr', text: x[2] ? ', done' : ', not done' }));
        if (i === firstOpen) li.setAttribute('aria-current', 'step');
        return li;
      }));
      if (head.childElementCount) head.classList.add('is-static');
      head.replaceChildren(
        stat('Competitors tracked', String(tracked.length), tracked.length ? 'Looked for in every AI check' : 'Add the rivals buyers compare you with', tracked.length ? '' : 'warn'),
        stat('You in AI answers', you ? CB.pct(you.share) : '–', you ? 'Share of buying answers naming you' : 'Needs an AI check'),
        stat('Top rival in AI', top ? top.name : '–', top ? CB.pct(top.share) + ' of buying answers' : 'Needs an AI check', top && you && top.share > you.share ? 'bad' : ''),
        stat('Sites citing rivals, not you', gap == null ? '–' : String(gap), gap ? 'Your outreach list' : 'Needs an AI check'));
    }

    function save(names, domains, done) {
      if (CB.demo) return Promise.reject(new Error('This sample is read-only. Sign in to change competitors.'));
      status.textContent = 'Saving…';
      var data = { revision: state.revision, step: 'competitors', competitors: names };
      if (domains) data.competitor_domains = domains;
      return CB.work(slug, 'onboarding_save', data).then(function (next) {
        state = next; CB.refresh(); status.textContent = '';
        CB.toast(done || 'Competitors saved');
        drawList();
      }, function (e) { status.textContent = ''; throw new Error(e.message || 'Could not save competitors.'); });
    }

    // Two thin bars: how often AI names this competitor versus you.
    function versus(name, theirs, yours) {
      function bar(label, value, cls) {
        var fill = h('i', { class: 'cx-bar-fill ' + cls });
        fill.style.setProperty('--cx-w', String(Math.max(0.02, Math.min(1, value))));
        return h('div', { class: 'cx-bar' }, h('span', { class: 'cx-bar-k', text: label }), h('span', { class: 'cx-bar-track' }, fill), h('b', { text: CB.pct(value) }));
      }
      var ahead = theirs > yours;
      return h('div', { class: 'cx-vs', role: 'img', 'aria-label': 'AI names ' + name + ' in ' + CB.pct(theirs) + ' of buying answers and you in ' + CB.pct(yours) },
        bar('Them', theirs, ahead ? 'is-ahead' : 'is-them'), bar('You', yours, 'is-you'),
        h('span', { class: 'cx-vs-note' + (ahead ? ' is-bad' : ' is-good'), text: ahead ? 'AI picks them more often' : 'AI picks you as often or more' }));
    }
    function tile(row) {
      var domain = domainOf(row), key = String(row.name).toLowerCase();
      var ai = share[key], est = traffic[domain] || traffic[key];
      var toggle = h('input', { type: 'checkbox', role: 'switch', 'aria-label': 'Track ' + row.name + ' in AI checks' });
      toggle.checked = !!row.selected;
      toggle.addEventListener('change', function () {
        var names = rowsFrom(state, d).filter(function (r) { return r.name === row.name ? toggle.checked : r.selected; }).map(function (r) { return r.name; });
        save(names, null, toggle.checked ? row.name + ' is tracked again' : row.name + ' paused').catch(function (e) { toggle.checked = !toggle.checked; status.textContent = e.message; });
      });
      var site = domain ? h('a', { class: 'cx-domain', href: 'https://' + domain, target: '_blank', rel: 'noopener noreferrer' }, domain, h('span', { 'aria-hidden': 'true', text: ' ↗' }))
        : h('span', { class: 'cx-domain is-missing', text: 'No website saved' });
      return h('li', { class: 'cx-tile' + (row.selected ? '' : ' is-paused') },
        h('div', { class: 'cx-tile-top' }, J().badge(row.name), h('div', { class: 'cx-name' }, h('h4', { text: row.name }), site),
          h('label', { class: 'cx-switch', title: row.selected ? 'Tracked in AI checks' : 'Paused' }, toggle, h('i', { class: 'cx-track', 'aria-hidden': 'true' }))),
        h('div', { class: 'cx-facts' },
          h('span', { class: 'cx-chip', text: row.selected ? sourceLabel(row) : 'Paused' }),
          ai && !you ? h('span', { class: 'cx-chip is-ai', text: 'In ' + CB.pct(ai.share) + ' of AI answers' }) : null,
          est && est.estimated_organic_traffic != null ? h('span', { class: 'cx-chip', text: CB.num(est.estimated_organic_traffic) + ' est. monthly visits' }) : null),
        ai && you ? versus(row.name, ai.share, you.share) : null,
        row.reason ? h('p', { class: 'cx-reason', text: row.reason }) : null);
    }

    function addForm() {
      var name = h('input', { type: 'text', placeholder: 'Business name', 'aria-label': 'Competitor name', maxlength: '160' });
      var site = h('input', { type: 'text', placeholder: 'website.com (optional)', 'aria-label': 'Competitor website', maxlength: '253', inputmode: 'url' });
      var err = h('p', { class: 'cx-err', role: 'alert' });
      var label = h('span', { text: 'Add competitor' });
      var btn = h('button', { type: 'submit', class: 'btn' }, label);
      var form = h('form', { class: 'cx-add', 'aria-label': 'Add a competitor' }, name, site, btn, err);
      form.addEventListener('submit', function (event) {
        event.preventDefault(); err.textContent = '';
        var n = name.value.trim(), w = site.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/.*$/, '');
        if (n.length < 2) { err.textContent = 'Write the competitor’s name.'; name.focus(); return; }
        if (w && !/^[a-z0-9.-]+\.[a-z]{2,}$/.test(w)) { err.textContent = 'Write the website like example.com, or leave it empty.'; site.focus(); return; }
        var rows = rowsFrom(state, d);
        if (rows.some(function (r) { return r.name.toLowerCase() === n.toLowerCase(); })) { err.textContent = n + ' is already on the list.'; return; }
        var names = rows.filter(function (r) { return r.selected; }).map(function (r) { return r.name; }).concat([n]);
        var domains = null;
        if (w) { domains = {}; domains[n] = w; }
        btn.disabled = true; label.textContent = 'Adding…';
        save(names, domains, n + ' added').then(function () { name.value = ''; site.value = ''; }, function (e) { err.textContent = e.message; })
          .then(function () { btn.disabled = false; label.textContent = 'Add competitor'; });
      });
      return form;
    }

    function drawList() {
      var rows = rowsFrom(state, d);
      drawHero(rows);
      var grid = rows.length ? h('ul', { class: 'cx-grid' }, rows.slice().sort(function (a, b) { return (b.selected ? 1 : 0) - (a.selected ? 1 : 0); }).map(tile)) :
        h('div', { class: 'cx-empty' }, J().icon('target', 'es-icon'), h('div', {}, h('b', { text: 'No competitors yet' }),
          h('p', { text: (state && state.competitor_help) || 'Add the businesses your buyers compare you with. Citebase then checks whether AI recommends them instead of you.' })));
      listCard.replaceChildren(
        h('div', { class: 'card-top' }, h('div', {}, h('h3', { id: 'cx-list-title', text: 'Your competitors' }),
          h('p', { class: 'sub', text: 'Tracked competitors are looked for in every AI check. Switch one off to pause it.' })),
          h('div', { class: 'tools' }, h('a', { class: 'btn ghost small', href: '#/p/' + encodeURIComponent(slug) + '/setup', text: 'Get suggestions' }))),
        grid, addForm(), status);
    }

    function drawAI() {
      if (rv && rv.brands && rv.brands.length > 1) aiBlock.appendChild(tools.rivalsCard(rv));
      else aiBlock.appendChild(J().emptyState({ icon: 'spark', title: 'See who AI recommends instead of you',
        text: 'After an AI check, this shows how often each competitor is named next to you, and where AI cites them but not you.',
        actions: [{ label: 'Run AI check', icon: 'spark', run: tools.aiCheck }],
        note: 'You see the price and approve it before anything runs.' }));
      if (d.citation_gap && d.citation_gap.sites && d.citation_gap.sites.length) aiBlock.appendChild(tools.gapCard(d.citation_gap));
    }

    var loading = CB.loadingView(listCard, 'Loading your competitors…');
    drawHero(rowsFrom(null, d));
    drawAI();
    Promise.all([
      CB.work(slug, 'onboarding_get', {}).catch(function () { return null; }),
      CB.work(slug, 'research_get', {}).catch(function () { return null; })
    ]).then(function (res) {
      loading.stop();
      if (!listCard.isConnected) return;
      state = res[0] || { revision: 0, competitors: rowsFrom(null, d) };
      ((res[1] && res[1].competitors) || []).forEach(function (r) {
        if (r.domain) traffic[String(r.domain).toLowerCase().replace(/^www\./, '')] = r;
        if (r.name) traffic[String(r.name).toLowerCase()] = r;
      });
      drawList();
    });
  }

  CB.competitorsUI = { render: render };
})();
