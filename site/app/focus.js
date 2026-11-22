/* The project queue reads the same action and evidence records as their detail pages. */
(function () {
  'use strict';
  const CB = window.CB, h = CB.h, s = CB.s;
  const MAX_ITEMS = 20, PAGE_SIZE = 4;
  const groups = [
    {key: 'review', label: 'Needs review', state: 'Needs review'},
    {key: 'overdue', label: 'Overdue', state: 'Overdue action'},
    {key: 'open', label: 'Open actions', state: 'Open action'},
    {key: 'opportunity', label: 'Opportunities', state: 'Opportunity'}
  ];
  const groupFor = key => groups.find(group => group.key === key);
  const path = (project, section) => '#/p/' + encodeURIComponent(project) + '/' + section;
  const count = value => Number.isSafeInteger(value) && value >= 0;
  const words = value => typeof value === 'string' && value.trim();
  const icons = {
    all: 'M4 6h16M7 12h10M10 18h4',
    review: 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm0 4.5v4.5m0 3h.01',
    overdue: 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm0 4v5l3.5 2',
    open: 'M6 3v18m.5-16H18l-2.5 4L18 13H6.5',
    opportunity: 'm12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6L12 3Z',
    arrow: 'M4.5 12h14M13 6.5l5.5 5.5-5.5 5.5',
    external: 'M7.5 16.5 17 7m-8 0h8v8',
    down: 'm6.5 9.5 5.5 5.5 5.5-5.5'
  };
  function icon(name) {
    return s('svg', {class: 'focus-icon', viewBox: '0 0 24 24', width: 18, height: 18,
      fill: 'none', stroke: 'currentColor', 'stroke-width': 1.7, 'stroke-linecap': 'round',
      'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false'}, s('path', {d: icons[name]}));
  }
  function recordLink(project, item, className, label, arrow) {
    const url = path(project, item.kind === 'action' ? 'todo' : 'evidence') + '?record=' + encodeURIComponent(item.record_id);
    return h('a', {class: className, href: url}, label, arrow ? icon('arrow') : null);
  }
  function sectionLinks(project, filter) {
    return h('div', {class: 'focus-links'},
      filter !== 'opportunity' ? h('a', {href: path(project, 'todo')}, 'View actions', icon('arrow')) : null,
      (!filter || filter === 'all' || filter === 'opportunity') ?
        h('a', {href: path(project, 'evidence')}, 'View evidence', icon('arrow')) : null);
  }
  function sourceLink(project, value) {
    if (!words(value)) return null;
    const prefix = path(project, '');
    const sections = {answers: 'View AI answers', questions: 'View questions', site: 'View site check',
      evidence: 'View saved evidence', todo: 'View saved actions', traffic: 'View traffic'};
    if (value.startsWith(prefix)) {
      const section = value.slice(prefix.length);
      return Object.hasOwn(sections, section) ? h('a', {class: 'focus-source', href: path(project, section)},
        sections[section], icon('arrow')) : null;
    }
    // Match the project's saved-source rules. Keep credentials and private query strings out of links.
    if (!/^https:\/\//i.test(value) || /[\s\\\x00-\x1f]/.test(value)) return null;
    try {
      const url = new URL(value);
      if (!url.hostname.includes('.') || url.username || url.password || url.port || url.search || url.hash) return null;
      return h('a', {class: 'focus-source', href: url.href, target: '_blank', rel: 'noopener noreferrer',
        'aria-label': 'View source on ' + url.hostname + ' (opens in a new tab)'}, 'Source on ' + url.hostname, icon('external'));
    } catch (error) { return null; }
  }
  function status(item) {
    return h('span', {class: 'focus-state focus-state-' + item.priority}, icon(item.priority), groupFor(item.priority).state);
  }
  function metadata(item) {
    const facts = [];
    if (words(item.due_date)) facts.push(['Due', CB.day(item.due_date)]);
    if (words(item.owner)) facts.push(['Owner', item.owner]);
    if (words(item.observed_on)) facts.push(['Observed', CB.day(item.observed_on)]);
    return facts.length ? h('dl', {class: 'focus-meta'}, facts.map(([key, value]) =>
      h('div', {}, h('dt', {text: key}), h('dd', {text: value})))) : null;
  }
  function why(item) {
    return h('p', {class: 'focus-why'}, h('span', {class: 'focus-sr', text: 'Why this is here. '}), item.reason);
  }
  function next(item) {
    return h('div', {class: 'focus-step'}, h('strong', {text: 'Next step'}), h('p', {text: item.next_step}));
  }
  // The same site check can fail on several pages; name the page so the rows read differently.
  function pagePath(item) {
    if (!/^https?:\/\//i.test(item.evidence_url || '')) return '';
    try {
      const url = new URL(item.evidence_url);
      return (url.pathname || '/') + (url.search ? '…' : '');
    } catch (_) { return ''; }
  }
  function pageTag(item) {
    const path = pagePath(item);
    // Leading space keeps screen readers from joining the title and the page name.
    return path ? [' ', h('span', {class: 'focus-page', text: 'on ' + (path.length > 40 ? path.slice(0, 39) + '…' : path)})] : null;
  }
  function primary(project, item) {
    const cta = item.kind === 'action' ? 'Open action' : 'Open opportunity';
    return h('article', {class: 'focus-feature'}, status(item), h('h3', {}, item.title, pageTag(item)),
      why(item), next(item), metadata(item),
      h('div', {class: 'focus-choices'}, recordLink(project, item, 'focus-primary', cta, true), sourceLink(project, item.evidence_url)));
  }
  function queueRow(project, item) {
    const link = recordLink(project, item, 'focus-title-link', item.title);
    const disclosure = h('details', {class: 'focus-details'},
      h('summary', {'aria-label': 'Details for ' + item.title}, icon('down')),
      h('div', {class: 'focus-detail-body'}, why(item), next(item), metadata(item), sourceLink(project, item.evidence_url)));
    return h('li', {class: 'focus-row'}, status(item), h('h4', {}, link, pageTag(item)), disclosure);
  }
  function readResponse(result, filter) {
    if (!result || !Array.isArray(result.items) || !count(result.total) || !result.counts ||
        !groups.every(group => count(result.counts[group.key])) ||
        groups.reduce((n, group) => n + result.counts[group.key], 0) !== result.total) return null;
    const matched = filter === 'all' ? result.total : result.counts[filter];
    if (result.matched_total !== undefined && result.matched_total !== matched) return null;
    if (result.items.length > Math.min(matched, MAX_ITEMS) || (matched && !result.items.length)) return null;
    if (!result.items.every(item => item && (item.kind === 'action' || item.kind === 'opportunity') &&
        groupFor(item.priority) && (filter === 'all' || filter === item.priority) &&
        [item.record_id, item.title, item.reason, item.next_step].every(words))) return null;
    return {items: result.items, counts: result.counts, total: result.total, asOf: result.as_of, matched};
  }
  function mount(body, history, project) {
    const heading = h('h2', {id: 'project-focus-heading', tabindex: -1, text: 'What to do next'});
    const select = h('select', {'aria-label': 'Filter by priority'});
    const choices = [{key: 'all', label: 'All priorities'}, ...groups];
    const options = choices.map(group => h('option', {value: group.key, text: group.label}));
    select.append(...options);
    const picker = h('label', {class: 'focus-picker', hidden: true}, icon('all'), select);
    const content = h('div', {class: 'focus-content'});
    const announce = h('p', {class: 'focus-sr', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true'});
    body.appendChild(h('section', {id: 'project-focus', class: 'project-focus', 'aria-labelledby': heading.id},
      h('div', {class: 'focus-head'}, heading, picker), content, announce));
    const responses = new Map();
    let request = 0;
    function show(result, filter) {
      choices.forEach((group, i) => {
        const n = group.key === 'all' ? result.total : result.counts[group.key];
        options[i].textContent = group.label + ' (' + CB.num(n) + ')';
      });
      picker.hidden = result.total === 0 && filter === 'all';
      if (!result.matched) {
        const empty = {all: 'No next steps yet', review: 'No actions need review', overdue: 'No overdue actions',
          open: 'No open actions in this group', opportunity: 'No opportunities in the saved evidence'};
        const message = filter === 'all' ? 'Add an action or review the evidence from your project checks.' :
          'Choose another priority to see the rest of your queue.';
        content.replaceChildren(h('div', {class: 'focus-message'}, h('h3', {text: empty[filter]}),
          h('p', {text: message}), sectionLinks(project, filter)));
        announce.textContent = empty[filter];
        return;
      }
      const queue = h('ol', {class: 'focus-queue'});
      const queueBox = result.items.length > 1 ? h('div', {class: 'focus-queue-box'},
        h('h3', {text: 'Also in the queue'}), queue) : null;
      const countLabel = h('span', {class: 'focus-count'});
      const more = h('button', {class: 'focus-more', type: 'button'});
      const completeFirstPage = result.matched <= PAGE_SIZE && result.items.length === result.matched;
      const footer = h('div', {class: 'focus-foot', hidden: !words(result.asOf) && completeFirstPage},
        h('div', {class: 'focus-foot-meta'}, words(result.asOf) ?
          h('span', {text: 'As of ' + CB.day(result.asOf)}) : null, countLabel), more);
      content.replaceChildren(h('div', {class: queueBox ? 'focus-layout' : 'focus-layout focus-single'},
        primary(project, result.items[0]), queueBox), footer);
      let visible = 1;
      function reveal(userRequested) {
        const end = Math.min(result.items.length, userRequested ? visible + PAGE_SIZE : PAGE_SIZE);
        const added = result.items.slice(visible, end).map(item => queueRow(project, item));
        queue.append(...added);
        visible = end;
        countLabel.textContent = completeFirstPage ? '' : 'Showing ' + CB.num(visible) + ' of ' + CB.num(result.matched);
        const remaining = result.items.length - visible;
        more.hidden = !remaining;
        if (remaining) more.replaceChildren('Show ' + Math.min(remaining, PAGE_SIZE) + ' more', icon('down'));
        else if (visible < result.matched) footer.appendChild(sectionLinks(project, filter));
        announce.textContent = 'Showing ' + CB.num(visible) + ' of ' + CB.num(result.matched) + ' next steps.';
        if (userRequested && added.length) added[0].querySelector('a').focus();
      }
      more.addEventListener('click', () => reveal(true));
      reveal(false);
    }
    function cachedGroup(filter) {
      if (responses.has(filter)) return responses.get(filter);
      const all = responses.get('all');
      if (!all) return null;
      const items = all.items.filter(item => item.priority === filter);
      const matched = all.counts[filter];
      return items.length === matched ? {...all, items, matched} : null;
    }
    async function load(event) {
      const current = ++request, filter = select.value;
      const retry = event && event.type === 'click';
      if (retry) heading.focus({preventScroll: true});
      const cached = !retry && cachedGroup(filter);
      if (cached) {
        content.setAttribute('aria-busy', 'false');
        show(cached, filter);
        return;
      }
      content.setAttribute('aria-busy', 'true');
      content.replaceChildren(h('div', {class: 'focus-message focus-loading', text: 'Loading next steps…'}));
      announce.textContent = 'Loading next steps.';
      try {
        const query = {limit: MAX_ITEMS};
        if (filter !== 'all') query.priority = filter;
        const reply = await CB.work(project, 'project_focus', query, retry);
        if (current !== request) return;
        const result = readResponse(reply, filter);
        if (!result) throw new Error('Project focus unavailable');
        const previous = responses.values().next().value;
        if (previous && (previous.asOf !== result.asOf || groups.some(group => previous.counts[group.key] !== result.counts[group.key])))
          responses.clear();
        responses.set(filter, result);
        show(result, filter);
      } catch (error) {
        if (current !== request) return;
        const message = 'The project queue is unavailable. Try again or open Actions and Evidence to check your saved records.';
        content.replaceChildren(h('div', {class: 'focus-message'}, h('p', {text: message}),
          h('div', {class: 'focus-recovery'}, h('button', {type: 'button', class: 'focus-more', text: 'Try again', onclick: load}),
            sectionLinks(project))));
        announce.textContent = message;
      } finally {
        if (current === request) content.setAttribute('aria-busy', 'false');
      }
    }
    select.addEventListener('change', load);
    return load();
  }

  // Reuse the fixture record lists so every sample link opens the same record the detail page displays.
  function demo(project, data = {}) {
    if (!data || typeof data !== 'object' || Array.isArray(data) || Object.keys(data).some(k => !['limit', 'priority'].includes(k)))
      throw new Error('Use only the supported fields for this project operation.');
    const rawLimit = Object.hasOwn(data, 'limit') ? data.limit : 5;
    const limit = typeof rawLimit === 'string' && /^[1-9][0-9]?$/.test(rawLimit) ? Number(rawLimit) : rawLimit;
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_ITEMS) throw new Error('Choose a whole-number limit from 1 to 20.');
    if (Object.hasOwn(data, 'priority') && !groupFor(data.priority)) throw new Error('Choose review, overdue, open, or opportunity for priority.');
    const history = window.CB_DEMO.call('get_history', {project});
    const actions = CB.demoWork(project, 'actions_list', {}).actions;
    const findings = CB.demoWork(project, 'opportunities_list', {}).opportunities;
    const dates = [...(history.snapshots || []).map(r => r.saved_on), ...(history.audits || []).map(r => r.date),
      ...actions.map(a => a.updated_at || a.updated), ...findings.map(f => f.observed_on)];
    const asOf = dates.filter(words).map(v => v.slice(0, 10)).sort().at(-1) || null;
    const items = [];
    const usedFindings = new Set(actions.map(a => a.finding_id).filter(Boolean));
    actions.forEach(action => {
      const check = (action.recheck || {}).status;
      if (['done', 'skipped'].includes(action.status) || check === 'verified') return;
      const review = action.page_url && (action.after_title || action.after_description || action.technical_check);
      const priority = review ? 'review' : action.due_date && asOf && action.due_date < asOf ? 'overdue' : 'open';
      const finding = action.finding_id && findings.find(f => f.id === action.finding_id);
      const reason = action.evidence || action.rationale || (finding && finding.coverage) ||
        (priority === 'overdue' ? 'This action was still open after its due date.' :
          priority === 'review' ? 'The requested page change still needs verification.' : 'This action is open on the project’s saved action list.');
      items.push({id: action.id, record_id: action.id, kind: 'action', section: 'todo', title: action.title,
        priority, reason, next_step: priority === 'review' ? 'Open the action and check the saved page against the requested change.' :
          action.acceptance_condition || (finding && finding.suggested_action) || 'Open the action to record the next change or update its progress.',
        owner: action.owner, due_date: action.due_date, evidence_url: action.page_url || action.evidence_url || (finding && finding.evidence_url),
        observed_on: (action.recheck && action.recheck.checked_at) || (finding && finding.observed_on)});
    });
    const order = key => groups.findIndex(group => group.key === key);
    items.sort((a, b) => order(a.priority) - order(b.priority) ||
      (a.due_date || '9999').localeCompare(b.due_date || '9999') ||
      Number(Boolean(b.owner)) - Number(Boolean(a.owner)) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    const channels = ['technical', 'answers', 'off_page', 'search'];
    const severity = {fail: 0, warn: 1};
    const opportunities = findings.slice().sort((a, b) =>
      channels.indexOf(a.channel) - channels.indexOf(b.channel) || (b.observed_on || '').localeCompare(a.observed_on || '') ||
      (severity[a.severity] ?? 2) - (severity[b.severity] ?? 2) || (b.observations || 0) - (a.observations || 0) ||
      a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    opportunities.forEach(f => {
      if (usedFindings.has(f.id)) return;
      usedFindings.add(f.id);
      items.push({id: f.id, record_id: f.id, kind: 'opportunity', section: 'evidence',
        priority: 'opportunity', title: f.question ? f.title + ' · ' + f.question : f.title,
        reason: [f.source, f.coverage].filter(Boolean).join(' · '),
        next_step: f.channel === 'technical' ? f.manual_alternative || f.suggested_action : f.suggested_action,
        evidence_url: f.evidence_url, observed_on: f.observed_on});
    });
    const counts = Object.fromEntries(groups.map(group => [group.key, 0]));
    items.forEach(item => { counts[item.priority]++; });
    const matches = data.priority ? items.filter(item => item.priority === data.priority) : items;
    return {items: matches.slice(0, limit), counts, total: items.length, matched_total: matches.length, as_of: asOf};
  }
  CB.focusUI = {mount, demo};
})();
