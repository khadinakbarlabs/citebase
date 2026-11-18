/* Sample data for ?demo=1 (labelled "Sample data" on screen). Same shapes as Citebase's get_history.
   To-do changes are kept in memory only, so visitors can try managing them. */
(function () {
  'use strict';
  var ENG = ['chatgpt', 'google-aio', 'perplexity', 'gemini'];
  function r2(x) { return Math.round(x * 1000) / 1000; }
  function round(label, date, share, ment, cited, per) {
    var by = {};
    ENG.forEach(function (e, i) {
      var v = per[i];
      by[e] = { prompts: 22, recommendation_share: v, rs_low: r2(Math.max(0, v - .1)), rs_high: r2(Math.min(1, v + .11)),
        mentioned_rate: r2(Math.min(1, v * 1.7 + .05)), cited_rate: r2(v * .7) };
    });
    return { snapshot: label, saved_on: date, prompts: 22, recommendation_share: share, rs_low: r2(share - .08), rs_high: r2(share + .1),
      mentioned_rate: ment, cited_rate: cited, reputation_share: r2(.68 + share / 3), reputation_prompts: 4, engines: ENG.slice(),
      context: { chatgpt: { answers: 66, engine_version: ['gpt-4.1-mini + web_search'], country: ['US'] }, 'google-aio': { answers: 22, country: ['US'] },
        perplexity: { answers: 66, engine_version: ['sonar'], country: ['US'] }, gemini: { answers: 66, country: ['US'] } }, by_engine: by };
  }
  var QUESTIONS = [
    ['best payroll software for a 10 person company', 'small teams', [3, 1, 2, 2], [1, 0, 0, 1]],
    ['cheapest payroll service for startups', 'price', [2, 1, 3, 0], [0, 0, 1, 0]],
    ['payroll software that handles contractors and employees', 'contractors', [0, 0, 1, 0], [0, 0, 0, 0]],
    ['easiest payroll app for a small business owner', 'small teams', [3, 1, 3, 2], [2, 1, 2, 1]],
    ['which payroll provider has the best customer support', 'support', [1, 0, 0, 1], [1, 0, 0, 1]],
    ['payroll with built-in hr and time off tracking', 'hr', [0, 0, 0, 0], [0, 0, 0, 0]],
    ['best payroll for restaurants with tips', 'industries', [0, 0, 0, 0], [0, 0, 1, 0]],
    ['payroll software that files taxes automatically', 'tax', [2, 1, 1, 1], [2, 1, 1, 1]],
    ['alternatives to gusto for small teams', 'alternatives', [2, 0, 3, 1], [0, 0, 1, 0]],
    ['payroll for remote employees in several states', 'remote', [1, 0, 1, 0], [2, 0, 1, 1]],
    ['best payroll app for nonprofits', 'industries', [0, 0, 1, 0], [0, 0, 0, 0]],
    ['simple payroll for a family business', 'small teams', [2, 1, 2, 1], [1, 1, 1, 0]],
    ['payroll software with same day direct deposit', 'features', [1, 0, 1, 0], [0, 0, 0, 0]],
    ['how to switch payroll providers mid year', 'switching', [1, 1, 0, 1], [0, 0, 0, 0]]];
  function questions() {
    return QUESTIONS.map(function (q, i) {
      var engines = {}, rec = 0, before = 0;
      ENG.forEach(function (e, j) {
        var n = e === 'google-aio' ? 1 : 3;
        engines[e] = { answers: n, recommended: Math.min(n, q[2][j]), named: Math.min(n, q[2][j] + 1), linked: Math.min(n, Math.max(0, q[2][j] - 1)) };
        rec += engines[e].recommended; before += Math.min(n, q[3][j]);
      });
      return { prompt_id: 'q' + (i + 1), question: q[0], type: 'consideration', topic: q[1], answers: 10, recommended: rec, engines: engines,
        before: { answers: 10, recommended: before } };
    });
  }
  var acme = {
    project: 'acme-payroll', brand: { name: 'Acme Payroll', site: 'https://acmepayroll.example', domain: 'acmepayroll.example' }, panel_prompts: 26,
    snapshots: [round('baseline', '2026-11-14', .12, .27, .09, [.15, .09, .11, .08]), round('2026-12', '2026-12-14', .15, .32, .12, [.2, .1, .15, .1]),
      round('2027-01', '2027-01-14', .23, .41, .18, [.3, .14, .27, .16]), round('2027-02', '2027-02-14', .31, .5, .23, [.39, .2, .38, .22])],
    audits: [{ date: '2026-11-13', health_score: 71, subscores: { 'ai-search': 62, 'on-page': 80, technical: 70 } },
      { date: '2026-12-12', health_score: 79, subscores: { 'ai-search': 76, 'on-page': 84, technical: 77 } },
      { date: '2027-02-10', health_score: 88, subscores: { 'ai-search': 90, 'on-page': 91, technical: 82 } }],
    site_changes: { since: '2026-12-12', fixed: ['Missing meta descriptions', 'AI bots blocked in robots.txt', 'No FAQ schema'], 'new': ['Slow main image'], still_open: ['Thin pricing page'] },
    experiments: [{ date: '2026-12-20', action: 'Published "Payroll for 10-person teams" guide', mechanism: 'Answers a buying question directly' },
      { date: '2027-01-08', action: 'Got listed on a comparison page', mechanism: 'Site cited for rivals in 6 answers' }],
    settings: { country: 'us', language: 'en', frequency: 'monthly' },
    todo: [{ step: 'Unblock GPTBot and PerplexityBot', status: 'done', updated: '2026-11-20' }, { step: 'Add FAQ schema to the pricing page', status: 'done', updated: '2026-12-02' },
      { step: 'Pitch capterra.com for the payroll comparison', status: 'open', updated: '2027-02-14' }, { step: 'Fix the slow image on the home page', status: 'open', updated: '2027-02-10' },
      { step: 'Write a page for "payroll with hr and time off"', status: 'open', updated: '2027-02-14' }],
    due: [], questions: questions(),
    rivals: { round: '2027-02', answers: 198, previous_round: '2027-01', avg_position: 2.3, sentiment: { positive: 61, neutral: 30, mixed: 4, negative: 4 },
      note: 'Gusto is named in more buying answers than you.', brands: [
        { name: 'Gusto', answers: 112, share: .566, you: false, before: .61 },
        { name: 'Acme Payroll', answers: 99, share: .5, you: true, before: .41 },
        { name: 'Rippling', answers: 71, share: .359, you: false, before: .38 },
        { name: 'ADP', answers: 44, share: .222, you: false, before: .25 },
        { name: 'Paychex', answers: 21, share: .106, you: false, before: .09 }] },
    citation_gap: { round: '2027-02', answers_with_sources: 71,
      note: 'These sites were cited in answers that named a rival and not you. Getting a fair mention there is the most direct way into those answers.', sites: [
        { site: 'capterra.com', answers_citing_it: 14, answers_for_rivals_without_you: 7, answers_that_recommend_you: 2, engines: ['perplexity', 'google-aio'], rivals_named: ['Gusto', 'Rippling'], example_questions: ['best payroll software for a 10 person company'] },
        { site: 'nerdwallet.com', answers_citing_it: 9, answers_for_rivals_without_you: 5, answers_that_recommend_you: 1, engines: ['google-aio', 'chatgpt'], rivals_named: ['Gusto', 'ADP'], example_questions: ['cheapest payroll service for startups'] },
        { site: 'reddit.com', answers_citing_it: 11, answers_for_rivals_without_you: 4, answers_that_recommend_you: 3, engines: ['perplexity'], rivals_named: ['Gusto'], example_questions: ['alternatives to gusto for small teams'] },
        { site: 'forbes.com', answers_citing_it: 5, answers_for_rivals_without_you: 3, answers_that_recommend_you: 0, engines: ['chatgpt'], rivals_named: ['ADP', 'Paychex'], example_questions: ['payroll with built-in hr and time off tracking'] }] },
    ai_bot_visits: { period: { from: '2027-02-01', to: '2027-02-07' }, answer_bot_requests: 2932, training_bot_requests: 310, bots: [
      { bot: 'Googlebot', owner: 'Google', kind: 'answer', requests: 1880, blocked: 0, pages: 240 },
      { bot: 'bingbot', owner: 'Microsoft', kind: 'answer', requests: 640, blocked: 0, pages: 180 },
      { bot: 'GPTBot', owner: 'OpenAI', kind: 'training', requests: 310, blocked: 0, pages: 160 },
      { bot: 'OAI-SearchBot', owner: 'OpenAI', kind: 'answer', requests: 212, blocked: 0, pages: 74 },
      { bot: 'PerplexityBot', owner: 'Perplexity', kind: 'answer', requests: 126, blocked: 0, pages: 51 },
      { bot: 'ChatGPT-User', owner: 'OpenAI', kind: 'answer', requests: 58, blocked: 0, pages: 22 },
      { bot: 'Claude-User', owner: 'Anthropic', kind: 'answer', requests: 16, blocked: 12, pages: 9 }],
      findings: ['Claude-User (Anthropic) is being refused on most requests (12 of 16). It fetches pages to answer questions, so those answers cannot use your pages. Check the firewall or bot settings.'] },
    ai_traffic: { ai_visits: 1840, all_visits: 96000, ai_share: .0192,
      assistants: [{ assistant: 'ChatGPT', visits: 1210 }, { assistant: 'Perplexity', visits: 380 }, { assistant: 'Gemini', visits: 160 }, { assistant: 'Copilot', visits: 90 }],
      by_month: [{ month: '2026-09', ai_visits: 210, all_visits: 15400 }, { month: '2026-10', ai_visits: 240, all_visits: 15900 }, { month: '2026-11', ai_visits: 280, all_visits: 16100 },
        { month: '2026-12', ai_visits: 330, all_visits: 15800 }, { month: '2027-01', ai_visits: 360, all_visits: 16300 }, { month: '2027-02', ai_visits: 420, all_visits: 16500 }] },
    search_demand: { clicks: 4210, impressions: 188000, ctr: .022, gaps: [
      { query: 'best payroll software for small business', impressions: 9100, clicks: 64, ctr: .007, position: 14.2 },
      { query: 'payroll for 10 employees cost', impressions: 3400, clicks: 41, ctr: .012, position: 9.8 },
      { query: 'payroll with hr and time off', impressions: 2100, clicks: 12, ctr: .0057, position: 21.3 },
      { query: 'how to run payroll yourself uk', impressions: 1200, clicks: 9, ctr: .0075, position: 18.4 }],
      test_in_ai: ['best payroll software for small business', 'payroll for 10 employees cost', 'cheapest payroll service for startups'] },
    ranks: { saved_on: '2027-02-12', previous_date: '2027-01-12', keywords: 5, top_3: 1, top_10: 3, not_found: 1, positions: [
      { keyword: 'payroll for small teams', engine: 'google', now: 3, before: 7, checked_before: true, moved_up_by: 4 },
      { keyword: 'payroll software uk', engine: 'google', now: 8, before: 11, checked_before: true, moved_up_by: 3 },
      { keyword: 'best payroll software', engine: 'google', now: 14, before: 13, checked_before: true, moved_up_by: -1 },
      { keyword: 'payroll app', engine: 'bing', now: 6, before: null, checked_before: false, moved_up_by: null },
      { keyword: 'contractor payroll', engine: 'google', now: null, before: 38, checked_before: true, moved_up_by: null }] } };
  var cafe = {
    project: 'northwind-cafe', brand: { name: 'Northwind Café', site: 'https://northwindcafe.example' }, panel_prompts: 22,
    snapshots: [{ snapshot: 'baseline', saved_on: '2026-12-02', prompts: 20, recommendation_share: .05, rs_low: .01, rs_high: .16, mentioned_rate: .15, cited_rate: .05,
      engines: ['chatgpt', 'google-aio'], context: { chatgpt: { answers: 40 }, 'google-aio': { answers: 20 } },
      by_engine: { chatgpt: { prompts: 20, recommendation_share: .07, rs_low: .01, rs_high: .2, mentioned_rate: .2, cited_rate: .05 },
        'google-aio': { prompts: 20, recommendation_share: .02, rs_low: 0, rs_high: .12, mentioned_rate: .1, cited_rate: .05 } } }],
    audits: [{ date: '2026-12-01', health_score: 64, subscores: { 'ai-search': 58, 'on-page': 71, technical: 62 } }], experiments: [],
    todo: [{ step: 'Add opening hours and menu as text, not images', status: 'open' }, { step: 'Unblock GPTBot in robots.txt', status: 'open' },
      { step: 'Write a "best brunch near the station" page', status: 'open' }, { step: 'Claim the Google Business Profile', status: 'open' }],
    due: ['AI recommendation re-check is due (last round 2026-12-02).', 'Site check is due (last one 2026-12-01).'], questions: [],
    citation_gap: { round: 'baseline', answers_with_sources: 12, sites: [], note: 'No site was cited at least twice for rivals while leaving you out in this round.' } };
  var projects = { 'acme-payroll': acme, 'northwind-cafe': cafe };
  function overview() {
    return { projects: Object.keys(projects).map(function (k) {
      var p = projects[k], a = p.audits[p.audits.length - 1], s = p.snapshots[p.snapshots.length - 1];
      return { project: k, site: p.brand.site, brand: p.brand.name, rounds: p.snapshots.length, health_score: a ? a.health_score : null,
        last_round_saved: s ? s.saved_on : null, open_todos: p.todo.filter(function (t) { return t.status === 'open'; }).length,
        updated: s ? s.saved_on : null, due: p.due };
    }) };
  }
  window.CB_DEMO = { call: function (tool, args) {
    if (tool === 'get_history') {
      if (!args.project) return overview();
      if (!projects[args.project]) throw new Error('No saved project called ' + args.project + '.');
      return JSON.parse(JSON.stringify(projects[args.project]));
    }
    if (tool === 'save_results') {
      var p = projects[args.project], today = new Date().toISOString().slice(0, 10);
      (args.todo || []).forEach(function (t) {
        var hit = p.todo.filter(function (x) { return x.step.toLowerCase() === t.step.toLowerCase(); })[0];
        if (hit) { hit.status = t.status; hit.updated = today; } else p.todo.push({ step: t.step, status: t.status, updated: today });
      });
      return { project: args.project, todo: p.todo };
    }
    if (tool === 'save_results' || tool === 'import_ai_results') return { project: args.project, warnings: [], summary: { rows: 0 } };
    if (tool === 'audit_site') return { status: 'ok', health_score: 88 };
    if (tool === 'next_steps') return { tip: 'Start with the step marked "now"; it moves the most answers.', steps: [
      { step: 'Pitch capterra.com for the payroll comparison page', why: 'It was cited for rivals in 7 answers without naming you.', who: 'you', effort: '1 hour', urgency: 'now' },
      { step: 'Write a page for "payroll with hr and time off"', why: 'No engine recommends you there yet, and people search it.', who: 'you', effort: '3 hours', urgency: 'do first' },
      { step: 'Re-check in 30 days', why: 'Shows whether the work moved the number.', who: 'Claude', effort: '5 minutes', urgency: 'later' }] };
    if (tool === 'make_report') return { share_url: null, note: 'In the sample there is no real report. Signed in, you get a link anyone can open.' };
    if (tool === 'quote_cost') return { total_usd: 0, ready_runs: [] };
    if (tool === 'schedule_checks') return { when: 'on the 1st of every month at 08:00', cron: '0 8 1 * *', free_site_check: { input: {} }, ai_checks: { runs: [] } };
    throw new Error('Not available in the sample. Sign in with Apify to do this for real.');
  }, apify: function (method, path) {
    if (method !== 'GET') throw new Error('Not available in the sample. Sign in with Apify to do this for real.');
    var day = function (n) { return new Date(Date.now() - n * 864e5).toISOString(); };
    if (/^actor-runs/.test(path)) return { items: [
      { id: 's1', actId: 'bm', status: 'RUNNING', startedAt: day(0.01) },
      { id: 's2', actId: 'aio', status: 'SUCCEEDED', startedAt: day(1), finishedAt: day(0.99), defaultDatasetId: 'd2' },
      { id: 's3', actId: 'bm', status: 'SUCCEEDED', startedAt: day(1), finishedAt: day(0.98), defaultDatasetId: 'd3' },
      { id: 's4', actId: 'cb', status: 'SUCCEEDED', startedAt: day(3), finishedAt: day(2.99) },
      { id: 's5', actId: 'cb', status: 'FAILED', startedAt: day(6), finishedAt: day(5.99) },
      { id: 's6', actId: 'cb', status: 'SUCCEEDED', startedAt: day(9), finishedAt: day(8.99) }] };
    var acts = { bm: ['ai-search-brand-monitor', 'AI Search Brand Monitor'], aio: ['google-ai-overviews-scraper', 'Google AI Overviews Scraper'], cb: ['citebase', 'Citebase'] };
    var m = /^acts\/([^/?]+)/.exec(path);
    if (m && acts[m[1]]) return { id: m[1], username: 'khadinakbar', name: acts[m[1]][0], title: acts[m[1]][1] };
    if (/^schedules/.test(path)) return { items: [{ id: 'sc1', name: 'citebase-acme-payroll', title: 'Citebase: acme-payroll', cronExpression: '0 8 1 * *', timezone: 'Europe/London',
      isEnabled: true, nextRunAt: day(-12), lastRunAt: day(18), actions: [{}, {}, {}] }] };
    if (path === 'users/me') return { username: 'sample-user', plan: { id: 'STARTER', dataRetentionDays: 14 } };
    if (path === 'users/me/limits') return { monthlyUsageCycle: { startAt: day(20), endAt: day(-10) }, current: { monthlyUsageUsd: 9 }, limits: { maxMonthlyUsageUsd: 30 } };
    if (/^key-value-stores/.test(path)) return { id: 'sample-store' };
    throw new Error('Not in the sample.');
  } };
})();
