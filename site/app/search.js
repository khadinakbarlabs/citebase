/* Search tab: the Google Search Console report with insights, trend, positions,
   brand split, pages, countries, devices, quick wins and every query. */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h, num = CB.num, day = CB.day, D = CB.searchData;
  var PAGE_ROWS = 10, QUERY_ROWS = 25;
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  // replaceChildren would print "null" for a missing optional node.
  function put(el) { el.replaceChildren.apply(el, Array.prototype.slice.call(arguments, 1).filter(Boolean)); }
  function card(title, sub, cls) {
    var top = h('div', { class: 'card-top' }, h('div', {}, h('h3', { text: title }), sub ? h('p', { class: 'sub', text: sub }) : null));
    return h('section', { class: 'card sr-card' + (cls ? ' ' + cls : '') }, top);
  }
  function rate(clicks, impressions) { return isNum(impressions) && impressions ? ((clicks || 0) / impressions * 100).toFixed(1) + '%' : '–'; }
  function place(p) { return isNum(p) ? p.toFixed(1) : '–'; }
  function niceMax(vals) { var m = Math.max.apply(null, vals.concat([1])), p = Math.pow(10, Math.floor(Math.log10(m))); return Math.ceil(m / p) * p; }
  // A change line under a number. Lower is better for position.
  function delta(now, before, kind, period) {
    if (!isNum(now) || !isNum(before)) return null;
    var d, text;
    if (kind === 'position') { d = before - now; text = Math.abs(d).toFixed(1) + (Math.abs(d).toFixed(1) === '1.0' ? ' place' : ' places'); }
    else if (kind === 'rate') { d = (now - before) * 100; text = Math.abs(d).toFixed(1) + ' pts'; }
    else { d = now - before; text = before ? Math.round(Math.abs(d) / before * 100) + '%' : num(Math.abs(d)); }
    if (Math.abs(d) < (kind === 'count' ? 0.5 : 0.05) || text === '0%') return h('span', { class: 'sr-delta flat', text: 'Same as ' + period });
    return h('span', { class: 'sr-delta delta ' + (d > 0 ? 'up' : 'down') }, (d > 0 ? '▲ ' : '▼ ') + text,
      h('span', { class: 'sr-vs', text: ' vs ' + period }));
  }
  function tile(label, value, change, hint) {
    return h('div', { class: 'sr-kpi' }, h('span', { class: 'sr-k', text: label }), h('b', { class: 'sr-v', text: value }), change || null,
      hint ? h('span', { class: 'sr-hint', text: hint }) : null);
  }
  function ctrOf(t) { return t ? (isNum(t.ctr) ? t.ctr : t.impressions ? t.clicks / t.impressions : null) : null; }
  function kpis(slot, r) {
    var t = r.totals, p = r.prevTotals, period = 'previous ' + (r.days || 28) + ' days';
    put(slot, tile('Clicks', num(t.clicks), p && delta(t.clicks, p.clicks, 'count', period)),
      tile('Impressions', num(t.impressions), p && delta(t.impressions, p.impressions, 'count', period), 'Times Google showed your site'),
      tile('Click rate', isNum(ctrOf(t)) ? (ctrOf(t) * 100).toFixed(1) + '%' : '–', p && delta(ctrOf(t), ctrOf(p), 'rate', period)),
      tile('Average position', place(t.position), p && delta(t.position, p.position, 'position', period), '1 is the top result'));
  }
  function trend(slot, r, metric) {
    var daily = r.daily, prev = r.prevDaily || [], off = prev.length - daily.length;
    if (daily.length < 2) { put(slot, h('p', { class: 'note', text: 'Not enough days to draw a trend.' })); return; }
    var vals = daily.map(function (d) { return d[metric]; });
    var before = prev.length ? daily.map(function (_, i) { var x = prev[i + off]; return x ? x[metric] : null; }) : null;
    var series = [{ name: 'This period', cls: 'cb', vals: vals }];
    if (before) series.push({ name: 'Period before', cls: 'sr-prev', vals: before });
    put(slot, CB.lineChart({ labels: daily.map(function (d) { return CB.short(d.date); }), height: 210, width: 640,
      max: niceMax(vals.concat((before || []).filter(isNum))), fmt: function (v) { return v == null ? '–' : num(v); },
      aria: (metric === 'clicks' ? 'Clicks' : 'Impressions') + ' per day', series: series,
      tipTitle: function (i) { return day(daily[i].date); },
      tipExtra: function (i) { var d = daily[i]; return ['Click rate ' + rate(d.clicks, d.impressions), 'Average position ' + place(d.position)]; } }),
      before ? h('div', { class: 'legend sr-legend' }, h('span', {}, h('i', { class: 'cb' }), 'This period'), h('span', {}, h('i', { class: 'sr-prevk' }), 'Period before')) : null);
  }
  function seg(options, value, onpick, label) {
    var group = h('div', { class: 'seg', role: 'group', 'aria-label': label });
    options.forEach(function (o) {
      var button = h('button', { type: 'button', 'aria-pressed': String(o[0] === value), text: o[1] });
      button.addEventListener('click', function () {
        Array.prototype.forEach.call(group.children, function (b) { b.setAttribute('aria-pressed', String(b === button)); });
        onpick(o[0]);
      });
      group.append(button);
    });
    return group;
  }
  function insightList(model) {
    var list = D.insights(model);
    if (!list.length) return null;
    var c = card('What changed', 'Worked out from your Search Console numbers.', 'sr-insights');
    c.append(h('ul', { class: 'sr-says' }, list.map(function (i) { return h('li', { class: 'is-' + i.tone, text: i.text }); })));
    return c;
  }
  function meterBar(part) {
    var fill = h('i', {});
    fill.style.setProperty('--w', String(Math.max(0, Math.min(1, part || 0))));
    return h('span', { class: 'sr-bar', 'aria-hidden': 'true' }, fill);
  }
  function days(model) { return model.daily.length || 28; }
  function positionCard(model) {
    var now = D.bands(model.rows), before = model.previous && model.previous.rows.length ? D.bands(model.previous.rows) : null;
    var total = now.reduce(function (n, b) { return n + b.count; }, 0);
    var c = card('Where you rank', 'Searches by average position, last ' + days(model) + ' days.');
    c.append(h('ol', { class: 'sr-bands' }, now.map(function (b, i) {
      return h('li', { class: 'sr-band is-' + b.key }, h('span', { class: 'sr-k', text: b.label }), h('b', { text: num(b.count) }),
        meterBar(total ? b.count / total : 0),
        h('span', { class: 'sr-hint', text: num(b.clicks) + ' clicks' + (before ? ' · was ' + num(before[i].count) + ' searches' : '') }));
    })));
    return c;
  }
  function brandCard(model) {
    var c = card('Brand and other searches', 'Clicks from people who searched your name, and from everyone else.');
    if (!model.terms.length) { c.append(h('p', { class: 'note', text: 'Add your brand name in project setup to split brand searches from the rest.' })); return c; }
    var brand = model.rows.filter(function (r) { return D.isBranded(r.term, model.terms); });
    var other = model.rows.filter(function (r) { return !D.isBranded(r.term, model.terms); });
    var clicks = D.totals(model.rows).clicks;
    c.append(h('div', { class: 'sr-split' }, [['Searched your name', brand], ['Did not search your name', other]].map(function (g) {
      var t = D.totals(g[1]);
      return h('div', { class: 'sr-split-row' }, h('span', { class: 'sr-k', text: g[0] }), h('b', { text: num(t.clicks) + ' clicks' }),
        meterBar(clicks ? t.clicks / clicks : 0), h('span', { class: 'sr-hint', text: num(g[1].length) + ' searches · ' + num(t.impressions) + ' impressions' }));
    })), h('p', { class: 'note', text: 'Brand searches contain ' + model.terms.map(function (t) { return '“' + t + '”'; }).join(' or ') + '.' }));
    return c;
  }
  function moreButton(left, onclick) { return h('button', { type: 'button', class: 'btn ghost small sr-more', text: 'Show ' + left + ' more', onclick: onclick }); }
  function signed(d) {
    if (!isNum(d) || !Math.round(d)) return h('span', { class: 'sr-delta flat', text: '0' });
    return h('span', { class: 'delta ' + (d > 0 ? 'up' : 'down'), text: (d > 0 ? '+' : '−') + num(Math.abs(d)) });
  }
  function pagesCard(model) {
    if (!model.pages.length) return null;
    var c = card('Top pages', 'Pages Google sent people to, last ' + days(model) + ' days.'), shown = PAGE_ROWS, slot = h('div', { class: 'gr-rows' });
    var hasPrev = !!(model.previous && model.previous.pages.length);
    var head = ['Page', 'Clicks'].concat(hasPrev ? ['Change'] : [], ['Impressions', 'Click rate', 'Position']);
    function draw() {
      var rows = model.pages.slice(0, shown).map(function (p) {
        var link = CB.safeUrl(p.page), b = model.prevByPage[p.page], path = D.pathOf(p.page);
        var name = link ? h('a', { href: link, target: '_blank', rel: 'noopener noreferrer', text: path, title: p.page }) : h('span', { text: path });
        return h('tr', {}, h('td', { class: 'sr-path' }, name), h('td', { class: 'n', text: num(p.clicks) }),
          hasPrev ? h('td', { class: 'n' }, b ? signed((p.clicks || 0) - (b.clicks || 0)) : h('span', { class: 'sr-new', text: 'new' })) : null,
          h('td', { class: 'n', text: num(p.impressions) }), h('td', { class: 'n', text: rate(p.clicks, p.impressions) }), h('td', { class: 'n', text: place(p.position) }));
      });
      put(slot, h('div', { class: 'scroll' }, h('table', { class: 'gr-table' },
        h('thead', {}, h('tr', {}, head.map(function (t, i) { return h('th', { scope: 'col', class: i ? 'n' : null, text: t }); }))), h('tbody', {}, rows))),
        shown < model.pages.length ? moreButton(Math.min(PAGE_ROWS, model.pages.length - shown), function () { shown += PAGE_ROWS; draw(); }) : null);
    }
    draw(); c.append(slot);
    return c;
  }
  function placesCard(model) {
    if (!model.countries.length && !model.devices.length) return null;
    var row = h('div', { class: 'grid2 even sr-places' });
    if (model.countries.length) {
      var top = model.countries.slice(0, 8), useClicks = top.some(function (x) { return x.clicks > 0; });
      var c = card('Countries', (useClicks ? 'Clicks' : 'Impressions') + ' by country, last ' + days(model) + ' days.');
      c.append(CB.barChart({ aria: (useClicks ? 'Clicks' : 'Impressions') + ' by country', labelWidth: 130, width: 460,
        items: top.map(function (x) { return { label: D.countryName(x.country), value: (useClicks ? x.clicks : x.impressions) || 0,
          tip: [num(x.clicks) + ' clicks', num(x.impressions) + ' impressions', 'Average position ' + place(x.position)] }; }) }));
      row.append(c);
    }
    if (model.devices.length) {
      var all = model.devices.reduce(function (n, x) { return n + (x.clicks || 0); }, 0), d = card('Devices', 'Share of clicks by device.');
      d.append(h('div', { class: 'sr-split' }, model.devices.map(function (x) {
        return h('div', { class: 'sr-split-row' }, h('span', { class: 'sr-k', text: D.deviceName(x.device) }),
          h('b', { text: all ? Math.round((x.clicks || 0) / all * 100) + '%' : num(x.clicks) }), meterBar(all ? (x.clicks || 0) / all : 0),
          h('span', { class: 'sr-hint', text: num(x.clicks) + ' clicks · ' + num(x.impressions) + ' impressions · position ' + place(x.position) }));
      })));
      row.append(d);
    }
    return row;
  }
  function winsCard(model) {
    var wins = model.rows.filter(D.quickWin).sort(function (a, b) { return b.impressions - a.impressions; }).slice(0, 5);
    if (!wins.length) return null;
    var c = card('Quick wins', 'People see you for these searches but rarely click. A clearer page title, or a page that answers the search, can win those clicks.', 'sr-wins');
    c.append(h('ul', { class: 'sr-winlist' }, wins.map(function (r) {
      return h('li', {}, h('b', { text: r.term }), h('span', { text: num(r.impressions) + ' impressions · ' + num(r.clicks) + ' clicks · position ' + place(r.position) }));
    })));
    return c;
  }
  var FILTERS = [['all', 'All'], ['wins', 'Quick wins'], ['top10', 'Top 10'], ['brand', 'Brand'], ['other', 'Not brand']];
  var COLUMNS = [['term', 'Search'], ['clicks', 'Clicks'], ['impressions', 'Impressions'], ['ctr', 'Click rate'], ['position', 'Position'], ['move', 'Change']];
  function queriesCard(model, slug) {
    var hasPrev = !!(model.previous && model.previous.rows.length);
    var c = card('All searches', num(model.rows.length) + ' searches showed your site.' + (hasPrev ? ' Change is the move in position against the period before.' : ''), 'sr-queries');
    var state = { filter: 'all', text: '', sort: 'clicks', dir: -1, shown: QUERY_ROWS }, slot = h('div', { class: 'gr-rows' });
    var cols = COLUMNS.filter(function (col) { return hasPrev || col[0] !== 'move'; });
    function move(r) { var b = model.prevByTerm[r.term]; return b && isNum(b.position) && isNum(r.position) ? b.position - r.position : null; }
    function value(r, key) { return key === 'ctr' ? (r.impressions ? (r.clicks || 0) / r.impressions : null) : key === 'move' ? move(r) : r[key]; }
    var tests = { all: function () { return true; }, wins: D.quickWin, top10: function (r) { return isNum(r.position) && r.position <= 10; },
      brand: function (r) { return D.isBranded(r.term, model.terms); }, other: function (r) { return !D.isBranded(r.term, model.terms); } };
    function matches() {
      var q = state.text.trim().toLowerCase();
      return model.rows.filter(function (r) { return tests[state.filter](r) && String(r.term).toLowerCase().indexOf(q) >= 0; }).sort(function (a, b) {
        var x = value(a, state.sort), y = value(b, state.sort);
        if (x == null) return y == null ? 0 : 1;
        if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * state.dir;
      });
    }
    function header(col) {
      var on = state.sort === col[0];
      return h('th', { scope: 'col', class: col[0] === 'term' ? null : 'n', 'aria-sort': on ? (state.dir > 0 ? 'ascending' : 'descending') : 'none' },
        h('button', { type: 'button', class: 'sorter', text: col[1], onclick: function () {
          state.dir = on ? -state.dir : (col[0] === 'term' || col[0] === 'position' ? 1 : -1); state.sort = col[0]; draw(); } }));
    }
    function moveCell(r) {
      var m = move(r), b = model.prevByTerm[r.term];
      if (m == null) return h('span', { class: b ? 'sr-delta flat' : 'sr-new', text: b ? '–' : 'new' });
      if (Math.abs(m) < 0.05) return h('span', { class: 'sr-delta flat', text: '0' });
      return h('span', { class: 'delta ' + (m > 0 ? 'up' : 'down'), text: (m > 0 ? '▲ ' : '▼ ') + Math.abs(m).toFixed(1) });
    }
    function line(r) {
      var tags = [D.quickWin(r) ? 'Quick win' : null, model.terms.length && D.isBranded(r.term, model.terms) ? 'Brand' : null].filter(Boolean);
      return h('tr', {}, h('td', {}, h('span', { text: r.term }), tags.map(function (t) { return [' ', h('span', { class: 'gr-tag' + (t === 'Brand' ? ' is-ai' : ''), text: t })]; })),
        h('td', { class: 'n', text: num(r.clicks) }), h('td', { class: 'n', text: num(r.impressions) }), h('td', { class: 'n', text: rate(r.clicks, r.impressions) }),
        h('td', { class: 'n', text: place(r.position) }), hasPrev ? h('td', { class: 'n' }, moveCell(r)) : null);
    }
    function draw() {
      var list = matches();
      put(slot, h('small', { class: 'sr-count', text: 'Showing ' + Math.min(state.shown, list.length) + ' of ' + num(list.length) + ' searches' }),
        list.length ? h('div', { class: 'scroll' }, h('table', { class: 'gr-table sr-table' }, h('thead', {}, h('tr', {}, cols.map(header))),
          h('tbody', {}, list.slice(0, state.shown).map(line)))) : h('p', { class: 'note', text: 'No searches match.' }),
        state.shown < list.length ? moreButton(Math.min(QUERY_ROWS, list.length - state.shown), function () { state.shown += QUERY_ROWS; draw(); }) : null);
    }
    var find = h('input', { type: 'search', 'aria-label': 'Filter Google searches', placeholder: 'Find a search' });
    find.addEventListener('input', function () { state.text = find.value; state.shown = QUERY_ROWS; draw(); });
    var csv = h('button', { type: 'button', class: 'btn ghost small', text: 'Download CSV', onclick: function () {
      CB.csv((slug || 'project') + '-google-searches.csv', ['Search', 'Clicks', 'Impressions', 'Click rate', 'Position'].concat(hasPrev ? ['Position before'] : []),
        matches().map(function (r) { var b = model.prevByTerm[r.term]; return [r.term, r.clicks, r.impressions, rate(r.clicks, r.impressions), place(r.position)].concat(hasPrev ? [b ? place(b.position) : ''] : []); }));
    } });
    var filters = seg(FILTERS.filter(function (f) { return model.terms.length || (f[0] !== 'brand' && f[0] !== 'other'); }), 'all',
      function (f) { state.filter = f; state.shown = QUERY_ROWS; draw(); }, 'Show searches');
    c.append(h('div', { class: 'sr-tools' }, find, filters, csv), slot);
    draw();
    return c;
  }
  function connection(slug) {
    if (CB.demo || !CB.googleUI) return null;
    var box = h('details', { class: 'google-manage sr-connection' }, h('summary', {}, h('span', { text: 'Search Console connection and sync' })));
    box.addEventListener('toggle', function () { if (box.open && box.children.length === 1) box.append(CB.googleUI.panel(slug, { only: 'gsc', returnTo: 'search' })); });
    return box;
  }
  function overviewCard(model) {
    var periods = D.ranges(model), current = periods.length ? periods[periods.length - 1] : 0, metric = 'clicks';
    var kpiSlot = h('div', { class: 'sr-kpis' }), trendSlot = h('div', { class: 'sr-trend' });
    function redraw() { var r = D.range(model, current); kpis(kpiSlot, r); if (model.daily.length) trend(trendSlot, r, metric); }
    var overview = card('Search performance', model.daily.length ? null : 'Totals of the searches Google listed for this period.', 'sr-overview');
    if (periods.length > 1) overview.querySelector('.card-top').append(h('div', { class: 'tools' },
      seg(periods.map(function (n) { return [n, 'Last ' + n + ' days']; }), current, function (n) { current = n; redraw(); }, 'Date range')));
    overview.append(kpiSlot);
    if (model.daily.length) overview.append(h('div', { class: 'sr-trend-head' }, h('h4', { text: 'Every day' }),
      seg([['clicks', 'Clicks'], ['impressions', 'Impressions']], metric, function (m) { metric = m; redraw(); }, 'Trend measure')), trendSlot);
    redraw();
    return overview;
  }
  function draw(body, report, d, slug) {
    var model = D.prepare(report, d.brand), synced = report.provenance === 'google_sync';
    var meta = [report.property, report.start_date && report.end_date ? day(report.start_date) + ' to ' + day(report.end_date) : null,
      synced ? 'Synced from Google' + (report.observed_at ? ' on ' + day(report.observed_at) : '') :
        report.provenance === 'sample' ? 'Fictional sample numbers' : 'From a saved export'].filter(Boolean).join(' · ');
    body.append(h('header', { class: 'sr-head' }, h('div', {}, h('h2', { text: 'Google Search' }), h('p', { class: 'sub', text: meta }))));
    if (synced && !model.daily.length) body.append(h('p', { class: 'sr-resync' }, h('b', { text: 'More is ready. ' }),
      'Sync Search Console again to add the daily trend, pages, countries, devices and a comparison with the previous 28 days.'));
    [insightList(model), overviewCard(model), model.rows.length ? h('div', { class: 'grid2 even' }, positionCard(model), brandCard(model)) : null,
      pagesCard(model), placesCard(model), winsCard(model), model.rows.length ? queriesCard(model, slug) : null, connection(slug)]
      .forEach(function (node) { if (node) body.append(node); });
  }
  function empty(body, slug) {
    body.append(h('header', { class: 'sr-head' }, h('div', {}, h('h2', { text: 'Google Search' }),
      h('p', { class: 'sub', text: 'Clicks, positions, pages and searches from your own Search Console.' }))));
    body.append(CB.journey.emptyState({ icon: 'search', title: 'Connect Search Console to fill this page',
      text: 'Read-only. Citebase imports the last 28 days and the 28 days before, so you can see what changed. You can disconnect any time.' }));
    if (CB.googleUI && !CB.demo) body.append(h('section', { class: 'card sr-card' }, CB.googleUI.panel(slug, { only: 'gsc', returnTo: 'search' })));
  }
  function hasData(report) { return !!report && ((report.rows || []).length > 0 || (report.daily || []).length > 0 || report.clicks != null); }
  CB.searchUI = {
    render: function (body, d, slug) {
      var holder = h('div', { class: 'sr-page' }, h('p', { class: 'note', role: 'status', text: 'Loading your Google Search report…' }));
      body.append(holder);
      var load = CB.demo ? Promise.resolve(CB.searchSample ? CB.searchSample(d || {}) : null) :
        CB.work(slug, 'research_get', {}).then(function (r) { return r && r.first_party ? r.first_party.gsc : null; });
      return load.then(function (report) {
        if (!holder.isConnected) return;
        holder.replaceChildren();
        if (hasData(report)) draw(holder, report, d || {}, slug); else empty(holder, slug);
      }).catch(function () {
        if (holder.isConnected) put(holder, h('p', { class: 'note', text: 'Your Google Search report could not be loaded. Try again in a moment.' }));
      });
    },
    draw: draw
  };
  /* ---------- fictional sample for the demo project ---------- */
  function seeded(seed) { return function () { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }; }
  function iso(t) { return new Date(t).toISOString().slice(0, 10); }
  CB.searchSample = function (d) {
    var brand = d.brand || {}, site = brand.site || 'https://example.com', name = String(brand.name || 'Example').toLowerCase();
    var host = CB.host(site) || 'example.com', rnd = seeded(name.length * 7919 + 17), DAY = 86400000;
    var end = Date.now() - 3 * DAY, start = end - 27 * DAY;
    var seeds = ((d.search_demand && d.search_demand.gaps) || []).map(function (g) { return [g.query, g.impressions, g.position]; })
      .concat(((d.ranks && d.ranks.positions) || []).map(function (r) { return [r.keyword, 900 + Math.round(rnd() * 1500), r.now || 30]; }));
    var words = seeds.length ? seeds[0][0].split(' ').filter(function (w) { return w.length > 3 && ['best', 'what', 'cheap', 'free', 'with'].indexOf(w) < 0; })[0] || 'service' : 'service';
    [[name, 2600, 1.2], [name + ' login', 1400, 1.1], [name + ' pricing', 800, 1.6], [name + ' reviews', 520, 2.4],
      ['what is ' + words, 2400, 8.4], [words + ' near me', 1800, 6.1], ['cheap ' + words, 1500, 12.6], ['best ' + words + ' 2026', 2900, 11.2],
      [words + ' comparison', 1300, 7.4], [words + ' guide', 700, 4.2], ['free ' + words, 3200, 24.5], [words + ' tips', 610, 16.1]]
      .forEach(function (x) { seeds.push(x); });
    function ctr(p) { return p <= 1.5 ? 0.32 : p <= 3 ? 0.14 : p <= 10 ? 0.035 : p <= 20 ? 0.009 : 0.002; }
    var rows = seeds.map(function (x) {
      var impressions = Math.round(x[1] * (0.5 + rnd() * 0.3)), position = Math.round(x[2] * 10) / 10;
      return { term: x[0], impressions: impressions, position: position, clicks: Math.round(impressions * ctr(position) * (0.7 + rnd() * 0.6)) };
    });
    var before = rows.map(function (r, i) {
      var position = Math.round(Math.max(1, r.position + (i % 3 === 0 ? 3.5 : i % 5 === 0 ? -2.2 : 0.6)) * 10) / 10;
      return { term: r.term, impressions: Math.round(r.impressions * 0.86), position: position, clicks: Math.round(r.impressions * 0.86 * ctr(position)) };
    });
    var shown = rows.reduce(function (n, r) { return n + r.impressions; }, 0), clickRate = rows.reduce(function (n, r) { return n + r.clicks; }, 0) / shown;
    function series(from, scale) {
      var out = [];
      for (var i = 0; i < 28; i++) {
        var t = from + i * DAY, weekend = [0, 6].indexOf(new Date(t).getUTCDay()) >= 0 ? 0.72 : 1;
        var impressions = Math.round(shown * 1.15 / 28 * scale * weekend * (0.85 + rnd() * 0.3) * (0.92 + i / 180));
        out.push({ date: iso(t), impressions: impressions, clicks: Math.round(impressions * clickRate * (0.85 + rnd() * 0.3)), position: Math.round((8.6 - i / 40 + rnd()) * 100) / 100 });
      }
      return out;
    }
    var daily = series(start, 1), clicks = daily.reduce(function (n, x) { return n + x.clicks; }, 0), seen = daily.reduce(function (n, x) { return n + x.impressions; }, 0);
    var pages = ['/', '/pricing', '/blog/' + words.replace(/ /g, '-') + '-guide', '/compare', '/features', '/blog/how-to-choose'].map(function (path, i) {
      var part = [0.36, 0.22, 0.14, 0.1, 0.07, 0.05][i];
      return { page: site.replace(/\/$/, '') + path, impressions: Math.round(seen * part * (0.8 + rnd() * 0.4)), clicks: Math.round(clicks * part),
        position: Math.round((3 + i * 2.4 + rnd()) * 10) / 10 };
    });
    var pagesBefore = pages.map(function (p, i) { return { page: p.page, impressions: Math.round(p.impressions * 0.9), clicks: Math.round(p.clicks * (i === 2 ? 0.45 : 0.95)), position: p.position + 1 }; });
    function split(list) { return list.map(function (c) { return { key: c[0], clicks: Math.round(clicks * c[1]), impressions: Math.round(seen * c[1]), position: Math.round((5 + rnd() * 8) * 10) / 10 }; }); }
    return { service: 'gsc', source: 'Fictional Search Console sample', provenance: 'sample', property: 'sc-domain:' + host, website: host,
      start_date: iso(start), end_date: iso(end), observed_at: iso(end + 3 * DAY), rows: rows, daily: daily, pages: pages,
      countries: split([['usa', 0.46], ['gbr', 0.18], ['can', 0.11], ['ind', 0.09], ['aus', 0.07], ['deu', 0.04]]).map(function (c) {
        return { country: c.key, clicks: c.clicks, impressions: c.impressions, position: c.position }; }),
      devices: split([['MOBILE', 0.58], ['DESKTOP', 0.38], ['TABLET', 0.04]]).map(function (c) {
        return { device: c.key, clicks: c.clicks, impressions: c.impressions, position: c.position }; }),
      previous: { start_date: iso(start - 28 * DAY), end_date: iso(start - DAY), daily: series(start - 28 * DAY, 0.86), rows: before, pages: pagesBefore } };
  };
})();
