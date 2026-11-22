/* Google Search report numbers and plain-word insights. Pure functions on a synced
   Search Console record; older records with only query rows still work. */
(function () {
  'use strict';
  var CB = window.CB;
  var DAY = 86400000;
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function sum(rows, key) { return rows.reduce(function (n, r) { return n + (isNum(r[key]) ? r[key] : 0); }, 0); }
  // Clicks, impressions, click rate and impression-weighted position of a list of rows.
  function totals(rows) {
    var clicks = sum(rows, 'clicks'), impressions = sum(rows, 'impressions');
    var shown = rows.filter(function (r) { return isNum(r.position) && isNum(r.impressions) && r.impressions > 0; });
    var weight = sum(shown, 'impressions');
    return { clicks: clicks, impressions: impressions, ctr: impressions ? clicks / impressions : null,
      position: weight ? shown.reduce(function (n, r) { return n + r.position * r.impressions; }, 0) / weight : null };
  }
  // Every day from start to end, with zero for days Google reported nothing.
  function fillDays(daily, start, end) {
    var byDate = {};
    (daily || []).forEach(function (d) { if (d && typeof d.date === 'string') byDate[d.date] = d; });
    var from = Date.parse(start), to = Date.parse(end), out = [];
    if (!isFinite(from) || !isFinite(to) || to < from || (to - from) / DAY > 400) return (daily || []).slice();
    for (var t = from; t <= to; t += DAY) {
      var key = new Date(t).toISOString().slice(0, 10), d = byDate[key];
      out.push(d ? { date: key, clicks: d.clicks || 0, impressions: d.impressions || 0, position: isNum(d.position) ? d.position : null }
        : { date: key, clicks: 0, impressions: 0, position: null });
    }
    return out;
  }
  function pathOf(url) {
    try { var u = new URL(url); return (u.pathname || '/') + (u.search || ''); } catch (_) { return String(url || ''); }
  }
  // Brand words: the brand name as a phrase and the domain name as a whole word.
  function words(text) { return String(text || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim(); }
  function brandTerms(brand) {
    brand = brand || {};
    var terms = [], name = words(brand.name);
    if (name.length >= 3) terms.push(name);
    var host = String(brand.domain || '').toLowerCase();
    if (!host) { try { host = new URL(brand.site).hostname; } catch (_) { host = ''; } }
    var label = host.replace(/^www\./, '').split('.')[0];
    if (label && label.length >= 4 && terms.indexOf(label) < 0) terms.push(label);
    var compact = name.replace(/ /g, '');
    if (compact.length >= 4 && terms.indexOf(compact) < 0) terms.push(compact);
    return terms;
  }
  function isBranded(term, terms) {
    var text = ' ' + words(term) + ' ';
    return terms.some(function (t) { return text.indexOf(' ' + t + ' ') >= 0; });
  }
  // Seen often on page one or two but rarely clicked.
  function quickWin(row) {
    return isNum(row.impressions) && row.impressions >= 50 && isNum(row.position) &&
      row.position > 3 && row.position <= 20 && (row.clicks || 0) / row.impressions < 0.02;
  }
  var BANDS = [['top3', 'Top 3', 0, 3], ['top10', '4 to 10', 3, 10], ['top20', '11 to 20', 10, 20], ['rest', '21 and lower', 20, Infinity]];
  function bands(rows) {
    return BANDS.map(function (b) {
      var inBand = (rows || []).filter(function (r) { return isNum(r.position) && r.position > b[2] && r.position <= b[3]; });
      return { key: b[0], label: b[1], count: inBand.length, clicks: sum(inBand, 'clicks'), impressions: sum(inBand, 'impressions') };
    });
  }
  function byKey(rows, key) {
    var map = Object.create(null);
    (rows || []).forEach(function (r) { if (r && r[key] != null && !(r[key] in map)) map[r[key]] = r; });
    return map;
  }
  // One model for the tab: current rows, filled daily series, previous period and brand words.
  function prepare(report, brand) {
    report = report || {};
    var rows = (report.rows || []).filter(function (r) { return r && r.term != null; });
    var prev = report.previous && typeof report.previous === 'object' ? report.previous : null;
    var daily = Array.isArray(report.daily) && report.daily.length ? fillDays(report.daily, report.start_date, report.end_date) : [];
    var prevDaily = prev && Array.isArray(prev.daily) ? fillDays(prev.daily, prev.start_date, prev.end_date) : [];
    var now = report.totals && isNum(report.totals.clicks) ? report.totals : daily.length ? totals(daily) : totals(rows);
    if (!rows.length && !daily.length && isNum(report.clicks)) now = { clicks: report.clicks, impressions: report.impressions, ctr: null, position: null };
    return { report: report, rows: rows, daily: daily, totals: now, terms: brandTerms(brand),
      pages: report.pages || [], countries: report.countries || [], devices: report.devices || [],
      previous: prev ? { start_date: prev.start_date, end_date: prev.end_date, daily: prevDaily, rows: prev.rows || [], pages: prev.pages || [],
        totals: prev.totals && isNum(prev.totals.clicks) ? prev.totals : prevDaily.length ? totals(prevDaily) : null } : null,
      prevByTerm: byKey(prev && prev.rows, 'term'), prevByPage: byKey(prev && prev.pages, 'page') };
  }
  // Clicks in the headline total that the search list cannot show: Google keeps very rare or
  // personal searches private and lists at most 1,000. Null when the list covers the total.
  var LIST_LIMIT = 1000;
  function hiddenClicks(model) {
    var all = model && model.totals && model.totals.clicks, listed = sum((model && model.rows) || [], 'clicks');
    if (!isNum(all) || !model.rows.length || all - listed < 1) return null;
    return { all: all, listed: listed, hidden: all - listed, capped: model.rows.length >= LIST_LIMIT };
  }
  // Ranges the daily series supports: 7 days (compared with the 7 before) and the full period.
  function ranges(model) {
    var n = model.daily.length, out = [];
    if (n >= 7) out.push(7);
    if (n > 7) out.push(n);
    return out;
  }
  function range(model, days) {
    var n = model.daily.length;
    if (!n || days >= n) {
      return { days: n || null, daily: model.daily, totals: model.totals, prevDaily: model.previous ? model.previous.daily : [],
        prevTotals: (model.previous && model.previous.totals) || null, full: true };
    }
    var cur = model.daily.slice(n - days), before = n >= days * 2 ? model.daily.slice(n - days * 2, n - days) : [];
    return { days: days, daily: cur, totals: totals(cur), prevDaily: before, prevTotals: before.length ? totals(before) : null, full: false };
  }
  function change(now, before) {
    if (!isNum(now) || !isNum(before)) return null;
    return { diff: now - before, pct: before ? (now - before) / before : null };
  }
  function percent(x) { return Math.round(Math.abs(x) * 100) + '%'; }
  function fmt(x) { return Math.round(x).toLocaleString('en-US'); }
  function names(list) {
    var q = list.map(function (t) { return '“' + t + '”'; });
    return q.length > 1 ? q.slice(0, -1).join(', ') + ' and ' + q[q.length - 1] : q[0];
  }
  // The page behind most of a change in clicks. A page missing from a full top-100 list is unknown, not zero.
  function mainPage(model, net) {
    var cur = model.pages, before = model.previous ? model.previous.pages : [];
    if (!cur.length || !before.length || !net) return null;
    var nowMap = byKey(cur, 'page'), beforeMap = model.prevByPage, best = null;
    var nowComplete = cur.length < 100, beforeComplete = before.length < 100;
    Object.keys(Object.assign({}, nowMap, beforeMap)).forEach(function (page) {
      var a = nowMap[page] ? nowMap[page].clicks || 0 : nowComplete ? 0 : null;
      var b = beforeMap[page] ? beforeMap[page].clicks || 0 : beforeComplete ? 0 : null;
      if (a == null || b == null) return;
      var d = a - b;
      if (d * net > 0 && (!best || Math.abs(d) > Math.abs(best.diff))) best = { page: page, diff: d };
    });
    return best && Math.abs(best.diff) >= 3 && Math.abs(best.diff) >= Math.abs(net) * 0.4 ? best : null;
  }
  function trendInsights(model, out) {
    var prev = model.previous, now = model.totals, period = 'the previous ' + (model.daily.length || 28) + ' days';
    if (!prev || !prev.totals || !isNum(now.clicks) || !isNum(prev.totals.clicks)) return;
    var c = change(now.clicks, prev.totals.clicks);
    if (!prev.totals.clicks) {
      if (now.clicks) out.push({ tone: 'good', text: 'Clicks went from 0 to ' + fmt(now.clicks) + ' compared with ' + period + '.' });
    } else if (Math.abs(c.pct) < 0.05) {
      out.push({ tone: 'info', text: 'Clicks held steady: ' + fmt(now.clicks) + ', against ' + fmt(prev.totals.clicks) + ' in ' + period + '.' });
    } else {
      var page = mainPage(model, c.diff);
      out.push({ tone: c.diff > 0 ? 'good' : 'bad', text: 'Clicks ' + (c.diff > 0 ? 'up ' : 'down ') + percent(c.pct) + ' vs ' + period +
        ' (' + fmt(prev.totals.clicks) + ' → ' + fmt(now.clicks) + ')' + (page ? ', mostly from ' + pathOf(page.page) : '') + '.' });
    }
    var v = change(now.impressions, prev.totals.impressions);
    if (v && v.pct != null && Math.abs(v.pct) >= 0.1) {
      out.push({ tone: v.diff > 0 ? 'good' : 'bad', text: 'Google showed your site ' + percent(v.pct) + (v.diff > 0 ? ' more' : ' less') +
        ' often (' + fmt(prev.totals.impressions) + ' → ' + fmt(now.impressions) + ' impressions).' });
    }
  }
  function rankInsights(model, out) {
    if (!model.previous || !model.previous.rows.length) return;
    var up = [], down = [];
    model.rows.forEach(function (r) {
      var b = model.prevByTerm[r.term];
      if (!b || !isNum(b.position) || !isNum(r.position)) return;
      if (r.position <= 10 && b.position > 10) up.push(r);
      if (r.position > 10 && b.position <= 10) down.push(r);
    });
    function top(list) { return list.sort(function (x, y) { return (y.impressions || 0) - (x.impressions || 0); }).slice(0, 3).map(function (r) { return r.term; }); }
    function count(n) { return n + (n === 1 ? ' search' : ' searches'); }
    if (up.length) out.push({ tone: 'good', text: count(up.length) + ' moved into the top 10: ' + names(top(up)) + (up.length > 3 ? ' and more' : '') + '.' });
    if (down.length) out.push({ tone: 'bad', text: count(down.length) + ' fell out of the top 10: ' + names(top(down)) + (down.length > 3 ? ' and more' : '') + '.' });
  }
  function share(list, min) {
    var rows = list.filter(function (d) { return isNum(d.clicks); }), all = sum(rows, 'clicks');
    var best = rows.slice().sort(function (a, b) { return b.clicks - a.clicks; })[0];
    return best && all >= 10 && best.clicks / all >= min ? { row: best, part: best.clicks / all } : null;
  }
  // Plain sentences, each backed by the synced numbers. tone: good, bad or info.
  function insights(model) {
    var out = [];
    trendInsights(model, out);
    rankInsights(model, out);
    var wins = model.rows.filter(quickWin).sort(function (a, b) { return b.impressions - a.impressions; });
    if (wins.length) out.push({ tone: 'info', text: (wins.length === 1 ? '1 search shows' : wins.length + ' searches show') +
      ' your site on page one or two but rarely ' + (wins.length === 1 ? 'gets' : 'get') + ' a click, led by ' + names([wins[0].term]) + '. A clearer page title could win those clicks.' });
    var clicks = sum(model.rows, 'clicks');
    if (model.terms.length && clicks >= 10) {
      var branded = sum(model.rows.filter(function (r) { return isBranded(r.term, model.terms); }), 'clicks') / clicks;
      out.push({ tone: 'info', text: percent(branded) + ' of search clicks come from people who searched your name. ' +
        (branded < 0.5 ? 'Most come from people who did not know you yet.' : 'Most visitors already knew you before searching.') });
    }
    var device = share(model.devices, 0.6), country = share(model.countries, 0.3);
    if (device) out.push({ tone: 'info', text: percent(device.part) + ' of clicks come from ' + deviceName(device.row.device, true) + '.' });
    if (country) out.push({ tone: 'info', text: 'Most clicks come from ' + countryName(country.row.country) + ' (' + percent(country.part) + ').' });
    return out.slice(0, 6);
  }
  function deviceName(code, plural) {
    var n = { MOBILE: ['Phone', 'phones'], DESKTOP: ['Computer', 'computers'], TABLET: ['Tablet', 'tablets'] }[String(code).toUpperCase()];
    return n ? n[plural ? 1 : 0] : String(code || 'Unknown');
  }
  // Search Console uses three-letter country codes. The browser names the two-letter ones.
  var A3 = 'usaUS gbrGB indIN pakPK canCA ausAU deuDE fraFR espES itaIT nldNL braBR mexMX argAR colCO chlCL perPE ' +
    'phlPH idnID mysMY sgpSG thaTH vnmVN jpnJP korKR chnCN hkgHK twnTW areAE sauSA qatQA kwtKW egyEG ngaNG kenKE ' +
    'zafZA turTR rusRU ukrUA polPL sweSE norNO dnkDK finFI irlIE prtPT belBE cheCH autAT czeCZ romRO hunHU grcGR ' +
    'isrIL nzlNZ bgdBD lkaLK nplNP marMA dzaDZ tunTN ghaGH ethET venVE ecuEC bolBO uryUY pryPY criCR panPA domDO ' +
    'gtmGT hrvHR srbRS svkSK svnSI bgrBG ltuLT lvaLV estEE islIS luxLU mltMT cypCY jorJO lbnLB omnOM bhrBH irqIQ ' +
    'irnIR afgAF kazKZ uzbUZ azeAZ geoGE armAM mmrMM khmKH';
  var A2 = {};
  A3.split(' ').forEach(function (p) { if (p.length === 5) A2[p.slice(0, 3)] = p.slice(3); });
  var regionNames = null;
  try { regionNames = new Intl.DisplayNames(['en'], { type: 'region' }); } catch (_) { regionNames = null; }
  function countryName(code) {
    var c = String(code || '').toLowerCase();
    if (!c || c === 'zzz') return 'Unknown region';
    try { if (A2[c] && regionNames) return regionNames.of(A2[c]); } catch (_) { /* fall back to the code */ }
    return c.toUpperCase();
  }
  CB.searchData = { totals: totals, fillDays: fillDays, pathOf: pathOf, brandTerms: brandTerms, isBranded: isBranded,
    quickWin: quickWin, bands: bands, hiddenClicks: hiddenClicks, prepare: prepare, ranges: ranges, range: range, change: change, insights: insights,
    deviceName: deviceName, countryName: countryName };
})();
