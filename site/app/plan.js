/* The project's SEO plan: on-page, off-page and technical work, each with evidence, steps and guidelines. */
(function () {
  'use strict';
  const CB = window.CB, h = CB.h;
  const PRIORITY = {high:'High priority', medium:'Worth doing', low:'Minor'};

  function itemCard(slug, area, item, done) {
    const card = h('article', {class:'plan-item plan-' + item.priority},
      h('span', {class:'plan-priority', text:PRIORITY[item.priority] || item.priority}),
      h('h4', {text:item.title}),
      h('p', {class:'plan-why', text:item.why}),
      h('p', {class:'plan-how'}, h('b', {text:'How: '}), item.how));
    card.append(h('small', {class:'plan-source', text:item.source + (item.observed_on ? ' · ' + item.observed_on : '')}));
    if (item.pages && item.pages.length) card.append(h('small', {class:'plan-pages', text:'Pages: ' + item.pages.join(', ')}));
    const actions = h('div', {class:'plan-actions'});
    const link = item.evidence_url && (item.evidence_url.startsWith('#/') ? item.evidence_url : CB.safeUrl(item.evidence_url));
    if (link) actions.append(h('a', {class:'ext', href:link, target:link.startsWith('#/') ? null : '_blank',
      rel:'noopener noreferrer', text:'View evidence'}));
    if (CB.demo) {
      actions.append(h('small', {text:'Sign in to track this as an action.'}));
    } else if (item.next_step === 'citation_contact' && CB.citationOutreach && link && !link.startsWith('#/')) {
      actions.append(h('button', {type:'button', class:'btn small', text:'Find the author and draft a pitch',
        onclick:() => CB.citationOutreach.open(slug, {url:link, term:item.title})}));
    } else if (done.has(item.id)) {
      actions.append(h('span', {class:'plan-tracked', text:'✓ Tracked in Actions'}));
    } else {
      const track = h('button', {type:'button', class:'btn small', text:'Track as an action', onclick:async () => {
        track.disabled = true;
        try {
          const payload = {title:item.title.slice(0, 200), finding_id:item.id, evidence:item.why, rationale:item.how};
          if (link && !link.startsWith('#/')) payload.evidence_url = link;
          if (area !== 'off_page' && item.pages && item.pages[0]) payload.page_url = item.pages[0];
          await CB.work(slug, 'action_save', payload);
          done.add(item.id);
          track.replaceWith(h('span', {class:'plan-tracked', text:'✓ Tracked in Actions'}));
        } catch (e) { track.disabled = false; track.textContent = e.message || 'Could not save. Try again.'; }
      }});
      actions.append(track);
    }
    card.append(actions);
    return card;
  }

  function render(container, slug) {
    const box = h('section', {class:'card seo-plan', 'aria-label':'SEO plan'},
      h('h3', {text:'Your SEO plan'}), h('p', {class:'loading', text:'Building your plan from saved results…'}));
    container.append(box);
    Promise.all([CB.work(slug, 'seo_plan'), CB.demo ? Promise.resolve({actions:[]}) : CB.work(slug, 'actions_list').catch(() => ({actions:[]}))])
      .then(([plan, saved]) => {
        const done = new Set((saved.actions || []).map(a => a.finding_id).filter(Boolean));
        const tabs = h('div', {class:'plan-tabs', role:'tablist', 'aria-label':'Plan area'});
        const panel = h('div', {class:'plan-panel', role:'tabpanel'});
        function show(section) {
          for (const tab of tabs.children) tab.setAttribute('aria-selected', String(tab.dataset.area === section.area));
          const list = section.items.length ? section.items.map(item => itemCard(slug, section.area, item, done)) :
            [h('p', {class:'plan-empty', text:section.missing_evidence || 'Nothing to fix here in the saved results.'})];
          panel.replaceChildren(...list,
            section.total > section.items.length ? h('p', {class:'small-note', text:'Showing ' + section.items.length + ' of ' + section.total + '.'}) : '',
            h('details', {class:'plan-guidelines'}, h('summary', {text:section.label + ' guidelines'}),
              h('ul', {}, section.guidelines.map(line => h('li', {text:line})))));
        }
        plan.sections.forEach((section, i) => {
          tabs.append(h('button', {type:'button', role:'tab', class:'plan-tab', 'data-area':section.area,
            'aria-selected':String(i === 0), onclick:() => show(section)},
            section.label, h('span', {class:'plan-count', text:String(section.total)})));
        });
        box.replaceChildren(h('h3', {text:'Your SEO plan'}), h('p', {class:'small-note', text:plan.note}), tabs, panel);
        show(plan.sections[0]);
      })
      .catch(e => { box.replaceChildren(h('h3', {text:'Your SEO plan'}), h('p', {text:e.message || 'Could not build the plan.'})); });
    return box;
  }

  const guidelines = {
    on_page:['Give every important page one clear H1, a unique title under 60 characters and a description under 160.',
      'Answer each tracked buyer question on a real page, with prices, limits and named sources an assistant can quote.',
      'Add a visible author and updated date to long pages, and valid structured data that matches the page.'],
    off_page:['Start with the sites AI answers already cite for your competitors.',
      'Read the actual article first and pitch only where your product genuinely fits its readers.',
      'Offer something useful: corrected facts, original data, a quote or a product to test. Never pay for links.'],
    technical:['Let search engines and AI crawlers read your pages: check robots.txt, noindex tags and server errors first.',
      'Serve the main content in the HTML, not only after JavaScript runs.',
      'Use one canonical address per page, with HTTPS and no redirect chains.']};

  // Sample projects build the same plan from their fictional saved results.
  function demo(d) {
    const audit = (d.audits || []).slice(-1)[0] || {}, round = (d.snapshots || []).slice(-1)[0] || {};
    const site = '#/p/' + encodeURIComponent(d.project) + '/';
    const item = (area, title, why, how, priority, extra) => ({id:'sample/plan/' + area + '/' + title, title, why, how, priority,
      source:extra.source, observed_on:extra.on, pages:[], evidence_url:extra.url, next_step:extra.next});
    const findings = [...((d.site_changes || {}).new || []), ...((d.site_changes || {}).still_open || [])];
    const onPage = (d.questions || []).filter(q => q.answers && !q.recommended).map(q =>
      item('on_page', 'Answer: ' + q.question, 'No assistant recommended you in ' + q.answers + ' sample answers.',
        'Point one page at this question with prices, limits and sources an assistant can cite.', 'medium',
        {source:'Sample AI answers', on:round.saved_on, url:site + 'questions', next:'action_save'}));
    const offPage = ((d.citation_gap || {}).sites || []).map(s =>
      item('off_page', 'Get included on ' + s.site, 'AI answers cited this site ' + s.answers_for_rivals_without_you + ' times for competitors but not for you.',
        'Open the cited article, confirm it fits, find the editor, then review a short pitch.', s.answers_for_rivals_without_you >= 3 ? 'high' : 'medium',
        {source:'Sample cited domains', on:round.saved_on, url:site + 'answers', next:'citation_contact'}));
    const technical = findings.map(title => item('technical', title, 'The latest sample site audit lists this issue.',
      'Fix it on the affected page, then run the site audit again.', 'medium', {source:'Sample site audit', on:audit.date, url:site + 'site', next:'action_save'}));
    const section = (area, label, items) => ({area, label, items, total:items.length, guidelines:guidelines[area], missing_evidence:''});
    return {note:'Fictional sample plan. Signed in, it is built from your own saved results.',
      sections:[section('on_page', 'On-page SEO', onPage), section('off_page', 'Off-page SEO', offPage), section('technical', 'Technical SEO', technical)]};
  }

  CB.seoPlan = {render, demo, guidelines};
})();
