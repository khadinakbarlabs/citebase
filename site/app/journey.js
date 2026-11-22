/* Citebase project journey: one picture of where a project stands and the one next move.
   Five steps: add questions, check the site, ask AI, fix, check again.
   Also draws the project badge, the project cards on the Projects page and richer empty states.
   Text is always set with textContent; styles go through the CSSOM (CSP blocks inline styles). */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h, s = CB.s;

  function icon(name, cls) {
    return s('svg', { class: cls || 'jr-icon', 'aria-hidden': 'true', focusable: 'false' }, s('use', { href: '../assets/icons.svg#' + name }));
  }
  function count(list) { return Array.isArray(list) ? list.length : 0; }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }
  function go(slug, tab) { location.hash = '#/p/' + encodeURIComponent(slug) + '/' + tab; }

  /* ---------- project badge: initials on a colour picked from the name ---------- */
  function hue(text) {
    var n = 7;
    for (var i = 0; i < text.length; i++) n = (n * 31 + text.charCodeAt(i)) % 360;
    return n;
  }
  function initials(name) {
    var words = String(name || '?').replace(/^https?:\/\//, '').split(/[\s._-]+/).filter(Boolean);
    var letters = words.length > 1 ? words[0][0] + words[1][0] : (words[0] || '?').slice(0, 2);
    return letters.toUpperCase();
  }
  function badge(name, size) {
    var el = h('span', { class: 'jr-badge' + (size ? ' ' + size : ''), 'aria-hidden': 'true', text: initials(name) });
    el.style.setProperty('--jr-hue', String(hue(String(name || ''))));
    return el;
  }

  /* ---------- the five steps for one opened project ---------- */
  var STEPS = [
    { key: 'setup', label: 'Add questions', icon: 'questions' },
    { key: 'site', label: 'Check site', icon: 'site' },
    { key: 'ai', label: 'Ask AI', icon: 'spark' },
    { key: 'fix', label: 'Fix', icon: 'wrench' },
    { key: 'again', label: 'Check again', icon: 'repeat' }
  ];
  function progress(d) {
    var questions = count(d.questions) || Number(d.panel_prompts) || 0, audits = count(d.audits), rounds = count(d.snapshots);
    var fixed = (d.todo || []).some(function (t) { return t && t.status === 'done'; });
    var again = rounds >= 2 || audits >= 2;
    var done = { setup: questions > 0 || rounds > 0, site: audits > 0, ai: rounds > 0, fix: fixed || again, again: again };
    var current = STEPS.filter(function (st) { return !done[st.key]; })[0];
    return { done: done, questions: questions, audits: audits, rounds: rounds, current: current ? current.key : null };
  }
  // The single move to suggest for the current step.
  function nextMove(p, slug, run) {
    var moves = {
      setup: { title: 'Add the questions your buyers ask AI',
        text: 'Citebase asks AI assistants these questions to see if they recommend you. Start with 5 to 10.',
        label: 'Add questions', run: function () { go(slug, 'questions'); } },
      site: { title: 'Check your website',
        text: 'A free check scores your site out of 100 and lists what to fix so AI can read it.',
        label: 'Check site', run: run.checkSite },
      ai: { title: 'Ask AI about your brand',
        text: 'Run your questions through AI assistants and see who they recommend. You see the price first.',
        label: 'Run AI check', run: run.aiCheck },
      fix: { title: 'Fix what holds you back',
        text: 'Work through the top items in Actions and mark them done as you go.',
        label: 'Open actions', run: function () { go(slug, 'todo'); } },
      again: { title: 'Check again to see what changed',
        text: 'A second check shows whether your fixes moved the numbers.',
        label: p.rounds > 0 ? 'Run AI check' : 'Check site', run: p.rounds > 0 ? run.aiCheck : run.checkSite }
    };
    return p.current ? moves[p.current] : { title: 'Every step is done',
      text: 'Keep a regular schedule so changes show up on their own.', label: 'Schedule checks', run: run.schedule };
  }

  function stepper(p) {
    var doneCount = STEPS.filter(function (st) { return p.done[st.key]; }).length;
    var list = h('ol', { class: 'jr-steps' });
    STEPS.forEach(function (st, i) {
      var state = p.done[st.key] ? 'done' : st.key === p.current ? 'now' : 'todo';
      var li = h('li', { class: 'jr-step is-' + state },
        h('span', { class: 'jr-dot' }, icon(state === 'done' ? 'check' : st.icon)),
        h('span', { class: 'jr-label' }, h('span', { class: 'jr-num', text: 'Step ' + (i + 1) }), h('b', { text: st.label })),
        h('span', { class: 'jr-sr', text: state === 'done' ? ', done' : state === 'now' ? ', next' : ', not started' }));
      if (state === 'now') li.setAttribute('aria-current', 'step');
      list.appendChild(li);
    });
    var fill = h('i', { class: 'jr-fill' });
    var inOrder = 0;
    while (inOrder < STEPS.length && p.done[STEPS[inOrder].key]) inOrder++;
    // The line fills only across steps finished in order, reaching halfway toward the next one.
    fill.style.setProperty('--jr-done', String(inOrder ? Math.min(1, (inOrder - (inOrder < STEPS.length ? 0.5 : 1)) / (STEPS.length - 1)) : 0));
    return { node: h('div', { class: 'jr-track' }, h('span', { class: 'jr-rail', 'aria-hidden': 'true' }, fill), list), doneCount: doneCount };
  }

  // Journey bar shown under the project title on every project page.
  function bar(slug, d, run) {
    var p = progress(d), steps = stepper(p), move = nextMove(p, slug, run);
    var cta = h('button', { type: 'button', class: 'btn jr-cta' }, h('span', { text: move.label }), icon('arrow-right', 'jr-icon sm'));
    cta.addEventListener('click', function () { move.run(); });
    return h('section', { class: 'cb-journey' + (p.current ? '' : ' is-complete'), 'aria-label': 'Project progress' },
      steps.node,
      h('div', { class: 'jr-next' },
        h('span', { class: 'jr-count', 'aria-hidden': 'true' }, h('b', { text: String(steps.doneCount) }), h('span', { text: '/' + STEPS.length })),
        h('div', { class: 'jr-next-text' },
          h('span', { class: 'jr-eyebrow', text: p.current ? steps.doneCount + ' of ' + STEPS.length + ' steps done · next' : 'All ' + STEPS.length + ' steps done' }),
          h('strong', { text: move.title }), h('p', { text: move.text })), cta));
  }

  /* ---------- the Projects page: one card per project ---------- */
  function summary(item) {
    var health = typeof item.health_score === 'number' && item.health_score >= 0 && item.health_score <= 100 ? item.health_score : null;
    var site = !!item.last_site_check || health !== null, rounds = item.rounds || 0, open = item.open_todos || 0;
    var due = item.due || [];
    var steps = [site, rounds > 0, rounds > 0 && site && (open === 0 || rounds >= 2), rounds >= 2];
    var next = !site ? 'Check the website' : !rounds ? 'Run the first AI check' : due.length ? due[0]
      : open ? plural(open, 'open action', 'open actions') + ' to work on' : rounds < 2 ? 'Check again to see progress' : 'On track';
    return { health: health, rounds: rounds, open: open, steps: steps, next: next, due: due.length };
  }
  function ring(score) {
    var r = 20, c = 2 * Math.PI * r, v = score == null ? 0 : score;
    var tone = score == null ? 'none' : v >= 80 ? 'good' : v >= 60 ? 'warn' : 'bad';
    return h('span', { class: 'jr-ring is-' + tone },
      s('svg', { viewBox: '0 0 48 48', 'aria-hidden': 'true' }, s('circle', { class: 'jr-ring-track', cx: 24, cy: 24, r: r }),
        s('circle', { class: 'jr-ring-value', cx: 24, cy: 24, r: r, 'stroke-dasharray': (c * v / 100) + ' ' + c, transform: 'rotate(-90 24 24)' })),
      h('b', { text: score == null ? '–' : String(v) }));
  }
  function projectCard(item, url) {
    var name = item.brand || item.project, sm = summary(item), host = item.site ? CB.host(item.site) : item.project;
    var stepsDone = sm.steps.filter(Boolean).length;
    var dots = h('span', { class: 'jr-dots', 'aria-hidden': 'true' }, sm.steps.map(function (on) { return h('i', { class: on ? 'on' : '' }); }));
    var label = 'Open ' + name + '. ' + (sm.health === null ? 'Site not checked.' : 'Site health ' + sm.health + ' of 100.') + ' ' +
      plural(sm.rounds, 'AI check', 'AI checks') + '. Next: ' + sm.next + '.';
    return h('li', { class: 'pc' + (sm.due ? ' is-due' : '') },
      h('a', { class: 'pc-link', href: url(item.project, 'overview'), 'aria-label': label }),
      h('div', { class: 'pc-top' }, badge(name), h('div', { class: 'pc-name' }, h('h3', { text: name }), h('span', { text: host })),
        sm.due ? h('span', { class: 'pc-flag', text: plural(sm.due, 'check due', 'checks due') }) : null),
      h('div', { class: 'pc-stats' },
        h('div', { class: 'pc-stat' }, ring(sm.health), h('span', { class: 'pc-k', text: 'Site health' })),
        h('div', { class: 'pc-stat' }, h('b', { class: 'pc-big', text: String(sm.rounds) }), h('span', { class: 'pc-k', text: sm.rounds === 1 ? 'AI check' : 'AI checks' })),
        h('div', { class: 'pc-stat' }, h('b', { class: 'pc-big', text: String(sm.open) }), h('span', { class: 'pc-k', text: 'Open actions' }))),
      h('div', { class: 'pc-progress' }, dots, h('span', { text: stepsDone + ' of 4 steps' })),
      h('p', { class: 'pc-next' }, h('span', { class: 'pc-next-k', text: 'Next' }), h('span', { class: 'pc-next-v', text: sm.next }), icon('arrow-right', 'jr-icon sm')));
  }
  function cards(list, url, onNew) {
    var grid = h('ul', { class: 'pc-grid', 'aria-label': 'Saved projects' }, list.map(function (item) { return projectCard(item, url); }));
    if (onNew) {
      var add = h('button', { type: 'button', class: 'pc-link', 'aria-label': 'Add a new project' });
      add.addEventListener('click', onNew);
      grid.appendChild(h('li', { class: 'pc pc-new' }, add, h('span', { class: 'pc-plus', 'aria-hidden': 'true', text: '+' }),
        h('b', { text: 'New project' }), h('span', { text: 'Add another website' })));
    }
    return grid;
  }

  /* ---------- richer empty states: icon, one line, up to two buttons ---------- */
  function emptyState(opts) {
    var actions = h('div', { class: 'es-actions' });
    (opts.actions || []).forEach(function (a, i) {
      var b = h('button', { type: 'button', class: 'btn' + (i ? ' ghost' : '') }, a.icon ? icon(a.icon, 'jr-icon sm') : null, h('span', { text: a.label }));
      b.addEventListener('click', a.run);
      actions.appendChild(b);
    });
    return h('section', { class: 'es card' + (opts.compact ? ' is-compact' : '') },
      h('span', { class: 'es-art', 'aria-hidden': 'true' }, icon(opts.icon || 'info', 'es-icon')),
      h('div', { class: 'es-body' }, h('h3', { text: opts.title }), opts.text ? h('p', { text: opts.text }) : null,
        opts.actions && opts.actions.length ? actions : null, opts.note ? h('p', { class: 'es-note', text: opts.note }) : null));
  }

  CB.journey = { bar: bar, progress: progress, badge: badge, cards: cards, emptyState: emptyState, icon: icon };
})();
