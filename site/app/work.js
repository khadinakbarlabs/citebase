/* Project workflows use the same authenticated operations as the assistant. */
(function () {
  'use strict';
  const CB = window.CB, h = CB.h, F = CB.flows;
  const UI = CB.workUI = {};
  const lines = value => String(value || '').split('\n').map(item => item.trim()).filter(Boolean);
  const words = value => String(value == null ? '' : value).replace(/_/g, ' ');
  const button = (label, run, primary) => h('button', {type: 'button', class: 'btn ' + (primary ? 'small' : 'tiny'), text: label, onclick: run});
  const note = message => h('p', {class: 'muted', text: message});
  const actions = (...items) => h('div', {class: 'work-buttons'}, ...items);
  const field = (label, control) => h('label', {class: 'field'}, h('span', {text: label}), control);
  const group = (title, ...content) => h('details', {class: 'work-details'}, h('summary', {text: title}), ...content);
  const card = (title, ...content) => h('section', {class: 'card work-card'}, h('h3', {text: title}), ...content);
  const row = (...content) => h('article', {class: 'work-row'}, ...content);
  const heading = title => h('h4', {text: title});
  const sectionLink = (project, tab, label) => h('a', {class: 'ext', href: '#/p/' + encodeURIComponent(project) + '/' + tab, text: label});
  const recordRoute = (project, tab, id) => '#/p/' + encodeURIComponent(project) + '/' + tab + (id ? '?record=' + encodeURIComponent(id) : '');
  function selectedRecord(project, tab) {
    const [path, query] = location.hash.split('?');
    return path === recordRoute(project, tab) ? new URLSearchParams(query || '').get('record') : null;
  }
  // A shared link opens the exact record even when it normally falls beyond the first page.
  function recordList(host, items, opts) {
    const match = opts.id && items.find(item => item.id === opts.id);
    const ordered = match ? [match, ...items.filter(item => item !== match)] : items;
    CB.clear(host);
    if (opts.id && !match) host.appendChild(h('p', {class:'record-notice', role:'status', text:'This ' + opts.noun + ' is no longer in this project.'}));
    if (!ordered.length) { host.appendChild(note(opts.empty)); return; }
    const count = h('p', {class:'record-count', 'aria-live':'polite', 'aria-atomic':'true'});
    const list = h('div', {class:'record-list'});
    const more = button('Show more', () => append(true));
    host.append(count, list, more);
    let shown = 0;
    function append(moveFocus) {
      const end = Math.min(shown + 8, ordered.length);
      let first;
      for (; shown < end; shown++) {
        const item = ordered[shown], el = opts.row(item);
        if (item.id) el.dataset.recordId = item.id;
        el.tabIndex = -1;
        list.appendChild(el);
        if (!first) first = el;
        if (match && item === match) {
          el.setAttribute('data-selected-record', '');
          if (opts.focus) requestAnimationFrame(() => {
            if (el.isConnected && selectedRecord(opts.project, opts.tab) === item.id) {
              el.focus({preventScroll:true});
              el.scrollIntoView({block:'nearest'});
            }
          });
        }
      }
      count.textContent = (shown < ordered.length ? shown + ' of ' : '') + ordered.length + ' ' + opts.noun + (ordered.length === 1 ? '' : 's');
      more.hidden = shown >= ordered.length;
      more.textContent = 'Show ' + Math.min(8, ordered.length - shown) + ' more';
      if (moveFocus && first) first.focus();
    }
    append(false);
  }
  function source(url, label) {
    const href = CB.safeUrl(url);
    return href && h('a', {class: 'ext', href, target: '_blank', rel: 'noopener noreferrer', text: label || href});
  }
  function details(pairs) {
    const visible = pairs.filter(pair => pair[1] != null && pair[1] !== '' && pair[1] !== false);
    return visible.length ? h('dl', {class: 'work-facts'}, visible.map(([label, value]) =>
      h('div', {}, h('dt', {text: label}), h('dd', {}, value)))) : null;
  }
  function select(options, current) {
    return h('select', {}, options.map(opt => {
      const [value, label] = Array.isArray(opt) ? opt : [opt, words(opt)];
      return h('option', {value, selected: value === current, text: label});
    }));
  }
  // Fields with array values use one entry per line.
  function fields(spec, values) {
    const controls = {}, nodes = [];
    spec.forEach(([key, label, type, options]) => {
      const value = values[key];
      let control;
      if (type === 'select') control = select(options, value);
      else if (type === 'textarea' || type === 'lines') {
        control = h('textarea', {rows: 3});
        control.value = Array.isArray(value) ? value.join('\n') : value || '';
      } else {
        control = h('input', {type: type || 'text'});
        if (type === 'checkbox') control.checked = !!value;
        else control.value = value == null ? '' : value;
      }
      control.setAttribute('aria-label',label);
      controls[key] = control;
      nodes.push(type === 'checkbox' ? h('label', {class: 'check'}, control, label) : field(label, control));
    });
    return {nodes, controls, data() {
      const out = {};
      spec.forEach(([key, label, type]) => {
        const input = controls[key];
        if (!input.reportValidity()) throw new Error('Please check “' + label + '”.');
        if (type === 'checkbox') out[key] = input.checked;
        else if (type === 'lines') out[key] = lines(input.value);
        else if (type === 'number') out[key] = Number(input.value);
        else out[key] = input.value.trim();
      });
      return out;
    }};
  }
  function storageRecovery(project) {
    const box = h('div',{class:'storage-recovery'});
    const consoleLink = h('a',{class:'ext',href:'https://console.apify.com/storage/key-value-stores',
      target:'_blank',rel:'noopener noreferrer',text:'Open Apify Storage ↗'});
    const controls = h('div',{}), status = h('p',{role:'status'});
    box.append(h('strong',{text:'Use private storage for this schedule'}),
      h('p',{text:'Apify needs this project’s store set to Restricted before it can pass a storage grant to a scheduled check.'}),controls,status,consoleLink);
    if (!CB.cfg.oauth || CB.cfg.oauth.session === false || CB.demo) return box;
    const session=CB.sessionId();
    const review=button('Review project storage',async()=>{
      review.disabled=true;status.textContent='Checking this project’s store…';CB.clear(controls).append(review);
      try {
        const store=await CB.tool('dashboard_storage_review',{project});
        if (CB.sessionId()!==session || !box.isConnected) return;
        if (store.access==='RESTRICTED') {status.textContent='The store is Restricted. Preview the schedule again.';return;}
        if (store.access!=='FOLLOW_USER_SETTING') {status.textContent='This store has explicit sharing settings. Review them in Apify Storage.';return;}
        status.textContent='Current sharing follows this account’s default.';
        const check=h('input',{type:'checkbox'});
        const confirm=button('Set store to Restricted',async()=>{
          if (!check.checked || CB.sessionId()!==session) return;
          check.disabled=true;confirm.disabled=true;review.disabled=true;
          try {
            const saved=await CB.tool('dashboard_restrict_storage',{project,store_id:store.id,confirmed:true});
            if (CB.sessionId()!==session || !box.isConnected) return;
            if (saved.access!=='RESTRICTED') throw Error('Review the current store access in Apify.');
            CB.clear(controls);status.textContent='Private storage verified. Preview the schedule again.';
          } catch (e) {
            if (CB.sessionId()!==session || !box.isConnected) return;
            CB.clear(controls).append(review);status.textContent=e.message;
          } finally {review.disabled=false;}
        });
        confirm.disabled=true;
        check.addEventListener('change',()=>{confirm.disabled=!check.checked;});
        controls.append(h('label',{class:'check'},check,'I want to restrict '+store.name+' for every project in that store. Older links shared without sign-in may stop working.'),confirm);
      } catch (e) {if (CB.sessionId()===session) status.textContent=e.message;}
      finally {review.disabled=false;}
    });
    controls.append(review);return box;
  }
  function formDialog(title, nodes, saveLabel, submit, onSaved, usage, recoveryProject) {
    const session = CB.sessionId();
    let submitting = false;
    const error = h('div', {class: 'form-err', role: 'alert'});
    const dialog = F.dialog(title, h('div', {class: 'form'}, nodes, error), [
      {label: 'Cancel', ghost: true},
      {label: saveLabel, async onclick(close, btn) {
        if (submitting || btn.disabled) return;
        submitting = true;
        if (usage) usage.bind(null);
        btn.disabled = true;
        error.textContent = '';
        try {
          const result = await submit();
          if (session !== CB.sessionId()) return;
          close();
          if (onSaved) onSaved(result);
        } catch (e) {
          if (session === CB.sessionId()) {
            const billing = CB.usage.errorDetails(e);
            if (billing) CB.clear(error).appendChild(billing);
            else if (recoveryProject && /needs a Restricted project store/i.test(e.message)) CB.clear(error).appendChild(storageRecovery(recoveryProject));
            else error.textContent = e.message;
          }
        } finally {
          submitting = false;
          if (usage) usage.bind(btn); else btn.disabled = false;
        }
      }}
    ], {wide: true});
    if (usage) usage.bind(dialog.foot.lastElementChild);
    return dialog;
  }
  // A failed section can retry independently. Ignore late results after a newer filter request.
  function reader(section, load, render) {
    const content = h('div', {}); section.appendChild(content);
    let serial = 0;
    async function refresh() {
      const request = ++serial;
      content.setAttribute('aria-busy','true');
      CB.clear(content).appendChild(note('Loading…'));
      try {
        const result = await load();
        if (request === serial) { CB.clear(content); render(content, result, refresh); }
      } catch (e) {
        if (request === serial) CB.clear(content).appendChild(h('div', {role: 'alert'}, note(e.message), button('Try again', refresh)));
      } finally {
        if (request === serial) content.removeAttribute('aria-busy');
      }
    }
    refresh();
    return refresh;
  }
  const get = (project, operation, data) => CB.work(project, operation, data || {});
  function write(project, operation, data) {
    if (CB.demo) throw new Error('Sign in with Apify to save changes to your own project. The sample is read-only.');
    return get(project, operation, data);
  }
  function briefEditor(project, brief, refresh) {
    const form = fields([
      ['goal','Business goal'], ['audience','Target customers'], ['offer','Product or service'], ['business_type','Business type'],
      ['market','Market'], ['language','Language'], ['key_pages','Priority page URLs, one per line','lines'],
      ['editorial_rules','Editorial rules','textarea'], ['buyer_vocabulary','Terms your customers use','textarea'],
      ['confirmed_facts','Confirmed facts, one per line','lines'], ['inferred_facts','Facts still to confirm, one per line','lines']
    ], brief);
    formDialog('Edit project brief', form.nodes, 'Save brief', () =>
      write(project, 'brief_save', {...form.data(), expected_revision: brief.revision}), refresh);
  }
  UI.brief = function (project) {
    const box = card('Project brief');
    reader(box, () => get(project, 'brief_get'), (content, result, refresh) => {
      const b = result.brief, pages = (b.key_pages || []).map(url => source(url)).filter(Boolean);
      content.appendChild(h('div', {}, details([['Goal', b.goal], ['Customers', b.audience], ['Offer', b.offer],
        ['Market and language', [b.market, b.language].filter(Boolean).join(' · ')],
        ['Priority pages', pages.length ? h('div', {class: 'work-links'}, pages) : null]]),
        b.goal ? null : note('Add a goal and a priority page to guide the work.'),
        button(b.revision ? 'Edit brief' : 'Set project brief', () => briefEditor(project, b, refresh))));
    });
    return box;
  };
  const states = [['open','Open'], ['in_progress','In progress'], ['approved','Approved'], ['done','Change recorded'], ['skipped','Dismissed']];
  function actionEditor(project, action, refresh) {
    const origin = action.finding_id || (!action.id ? 'manual/' + crypto.randomUUID() : undefined);
    const main = fields([
      ['title','Action'], ['page_url','Affected page URL','url'], ['question','Target customer question'],
      ['evidence','Finding or factual basis','textarea'], ['evidence_url','Source URL','url'],
      ['owner','Responsible person or assistant'], ['due_date','Due date','date'],
      ['status','Work status','select',states], ['outcome','Recorded outcome','textarea']
    ], action);
    const page = fields([
      ['before_title','Current page title'], ['after_title','Expected page title'],
      ['before_description','Current description','textarea'], ['after_description','Expected description','textarea'],
      ['rationale','Reason for the edit','textarea'], ['constraints','Brand or factual constraints','textarea'],
      ['acceptance_condition','Acceptance condition','textarea'],
      ['technical_check','Technical check','select',[['','None'],['canonical','Canonical URL'],['http_status','HTTP status'],['internal_link','Internal link']]],
      ['before_value','Previously observed URL or status'], ['expected_value','Expected URL or status']
    ], action);
    main.controls.title.required = true;
    const inspected = h('div',{ 'aria-live':'polite' });
    const autofilled = new Map();
    const inspect = button('Read current page',async e => {
      const b = e.currentTarget, address = main.controls.page_url.value.trim();
      if (!address || !main.controls.page_url.reportValidity()) {
        CB.clear(inspected).appendChild(note('Enter the affected page URL first.')); return;
      }
      b.disabled = true; CB.clear(inspected).appendChild(note('Reading the selected public page…'));
      try {
        const {page:reading} = await get(project,'page_inspect',{page_url:address});
        if (main.controls.page_url.value.trim() !== address) return;
        CB.clear(inspected);
        if (reading.status !== 'observed') {inspected.appendChild(note(reading.reason || 'The page could not be observed.'));return;}
        inspected.appendChild(h('div',{},details([['Observed URL',source(reading.page_url)], ['Checked',reading.checked_at],
          ['HTTP status',reading.http_status],['Observed title',reading.title || '(absent)'], ['Observed description',reading.description || '(absent)'],
          ['Canonical', source(reading.canonical)],['Headings',(reading.h1 || []).join(' · ')],['Coverage',reading.coverage]]),
          note(({keep_current:'The page already has a title. Keep it if it answers the customer question.',review_heading:'The page has no title. Review its heading as a possible title.',draft_needed:'There is no observed title or heading to suggest. Draft a title using a verified source.'})[reading.title_guidance] || 'Review the observed metadata against the customer question.')));
        // Preserve every user edit. Use the observation directly only when the current-value field is empty.
        for (const [name,value] of [['before_title',reading.title],['before_description',reading.description]]) {
          const input=page.controls[name];
          if (value && !input.value.trim()) {input.value=value;autofilled.set(input,value);}
        }
        if (reading.suggested_title && !page.controls.after_title.value.trim()) inspected.appendChild(button(reading.title_guidance === 'keep_current' ? 'Keep observed title' : 'Use observed heading',()=>{
          if (main.controls.page_url.value.trim() !== address || page.controls.after_title.value.trim()) return;
          page.controls.after_title.value=reading.suggested_title;autofilled.set(page.controls.after_title,reading.suggested_title);
          page.controls.after_title.closest('details').open=true;page.controls.after_title.focus();
        }));
      } catch (err) {CB.clear(inspected).appendChild(note(err.message));}
      finally {b.disabled=false;}
    });
    main.controls.page_url.addEventListener('input',()=>{
      CB.clear(inspected);
      autofilled.forEach((value,input)=>{if(input.value === value) input.value='';});autofilled.clear();
    });
    const proposed = group('Review page copy and acceptance',
      h('div',{class:'record-form-pair'}, ...page.nodes.slice(0,2)),
      h('div',{class:'record-form-pair'}, ...page.nodes.slice(2,4)), ...page.nodes.slice(4));
    const context = group('Question and supporting evidence',...main.nodes.slice(2,5));
    context.open = !!action.finding_id && !action.id;
    formDialog(action.id ? 'Review action' : 'New action', [...main.nodes.slice(0,2),actions(inspect),inspected,
      h('div',{class:'record-form-pair'},main.nodes[5],main.nodes[6]),main.nodes[7],context,proposed,
      group('Record an outcome',main.nodes[8])],
      'Save action', () => write(project, 'action_save', {...main.data(), ...page.data(), id: action.id || undefined,
        finding_id: origin, expected_revision: action.revision || 0}), refresh);
  }
  UI.pageReview = function (project, website) {
    return card('Page review',actions(button('Review a page',()=>actionEditor(project,{page_url:website || ''},
      ()=>{location.hash='#/p/'+encodeURIComponent(project)+'/todo';}),true),sectionLink(project,'evidence','See saved findings')));
  };
  function actionRow(project, item, refresh) {
    const checked = item.recheck;
    const buttons = actions(button('Review or edit', () => actionEditor(project,item,refresh)));
    if (item.technical_ticket) buttons.appendChild(button('Copy ticket', e => F.copy(item.technical_ticket, e.currentTarget)));
    if (item.after_title || item.after_description) {
      if (item.after_title) buttons.appendChild(button('Copy proposed title',e=>F.copy(item.after_title,e.currentTarget)));
      if (item.status !== 'skipped') buttons.appendChild(button('Keep current copy',()=>formDialog('Keep the current page copy?',[
        details([['Current title',item.before_title],['Proposed title',item.after_title],['Current description',item.before_description],['Proposed description',item.after_description]])
      ],'Keep current copy',()=>write(project,'action_save',{id:item.id,expected_revision:item.revision,status:'skipped',outcome:'Reviewed and kept the current copy.'}),refresh)));
    }
    if (item.page_url && (item.after_title || item.after_description || item.technical_check)) {
      buttons.appendChild(button('Recheck page', () => formDialog('Recheck page', [
        note('Read the current HTML at this URL and compare it with the saved expectations.'),
        source(item.page_url), details([['Expected title',item.after_title],['Expected description',item.after_description], ['Check',words(item.technical_check)], ['Expected value',item.expected_value]])],
        'Check this page', () => write(project, 'action_recheck', {id:item.id, expected_revision:item.revision}), refresh)));
    }
    const status = (states.find(([key]) => key === item.status) || ['',words(item.status)])[1];
    const linkedFinding = /^[0-9a-f]{24}$/.test(item.finding_id) || (CB.demo && (item.finding_id || '').startsWith('sample/'));
    const finding = linkedFinding ?
      h('a',{class:'ext',href:recordRoute(project,'evidence',item.finding_id),text:'Open original finding'}) : null;
    const facts = details([['Page',source(item.page_url)], ['Question',item.question], ['Evidence',item.evidence],
      ['Source',source(item.evidence_url)], ['Reason for the edit',item.rationale], ['Recorded outcome',item.outcome], ['Acceptance',item.acceptance_condition],
      ['Current title',item.before_title], ['Proposed title',item.after_title],
      ['Current description',item.before_description], ['Proposed description',item.after_description],
      ['Observed title',checked && checked.observed_title], ['Observed description',checked && checked.observed_description],
      ['Observed value',checked && checked.observed_value], ['Coverage',checked && checked.reason]]);
    return row(h('div',{class:'record-meta'},
      h('span',{class:'record-state',text:status}),
      item.owner ? h('span',{text:'Owner · '+item.owner}) : null,
      item.due_date ? h('span',{text:'Due '+CB.day(item.due_date)}) : null),
      heading(item.title),
      checked ? h('p',{class:'record-verification',text:'Page check: '+words(checked.status)+' · '+CB.day(checked.checked_at)}) : null,
      facts || finding ? group('Evidence and expected change',facts,finding) : null,
      item.history && item.history.length ? group('Revision history', h('ol',{},item.history.map(v=> h('li',{text:'Revision '+v.revision+' · '+v.title+' · '+words(v.status)})))) : null, buttons);
  }
  UI.actions = function (body, d, project) {
    const box = card('Actions'), filter = select([['all','All statuses'], ...states], 'all');
    body.appendChild(box);
    const search = h('input',{type:'search',placeholder:'Title, owner, or page'});
    let items = [], refresh, enter = true;
    const results = h('div', {}), summary = h('div', {});
    const stateTone = {open:'brand', in_progress:'spark', approved:'e1', done:'good', skipped:'muted'};
    function draw() {
      const bar = CB.summaryBar(states.map(([key,label]) => ({key,label,tone:stateTone[key] || 'muted',
        count:items.filter(item => item.status === key).length})), filter.value, key => { filter.value = key; draw(); }, 'Filter actions by status');
      summary.replaceChildren(...(bar ? [bar] : []));
      const term = search.value.trim().toLowerCase();
      const filtered = !!term || filter.value !== 'all';
      const shown = items.filter(item => (filter.value === 'all' || item.status === filter.value)
        && (!term || [item.title,item.owner,item.page_url,item.question].some(v => String(v || '').toLowerCase().includes(term))));
      recordList(results,shown,{project,tab:'todo',id:!filtered && selectedRecord(project,'todo'),focus:enter,noun:'action',
        empty:filtered ? 'No actions match your search or status.' : 'There are no saved actions yet. Start with a finding or add an action for this project.',
        row:item=>actionRow(project,item,refresh)});
      enter = false;
      if (!shown.length && filtered) results.appendChild(button('Clear filters',()=>{search.value='';filter.value='all';draw();search.focus();}));
    }
    box.appendChild(h('div',{class:'record-toolbar'},field('Search actions',search),field('Show actions',filter),
      button('New action', () => actionEditor(project, {}, refresh), true),sectionLink(project,'evidence','Find an opportunity')));
    search.oninput = draw; filter.onchange = draw;
    refresh = reader(box, () => get(project,'actions_list'), (content,data) => {items = data.actions; content.append(summary, results); draw();});
    if (CB.seoPlan) CB.seoPlan.render(body, project);
    if ((d.experiments || []).length) body.appendChild(card('Logged changes', h('ol',{class:'timeline'}, d.experiments.slice().reverse().map(v =>
      h('li',{},h('span',{class:'when',text:CB.day(v.date)}),h('b',{text:v.action}),note(v.mechanism || ''))))));
  };

  function timestamp(value, zone) {
    if (!value) return '';
    try { return new Intl.DateTimeFormat(undefined, {dateStyle:'medium', timeStyle:'short', timeZone:zone}).format(new Date(value)); }
    catch (_) { return String(value); }
  }
  const weekdays = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
  const amountLabel = (n, unit) => CB.num(n)+' '+unit+(n === 1 ? '' : 's');
  function calendarRule(plan) {
    if (plan.cadence) return plan.cadence;
    const day = plan.frequency === 'weekly' ? 'Every '+weekdays[plan.weekday || 0] :
      plan.frequency === 'monthly' ? 'Day '+(plan.month_day || 1)+' of every month' : 'Every day';
    return day+' at '+(plan.local_time || '08:00');
  }
  function planFacts(plan, questions) {
    const paid = plan.scope === 'site_and_ai', count = plan.checks_per_occurrence;
    const qNames = new Map((questions || []).map(q=>[q.prompt_id, q.question || q.prompt || q.prompt_id]));
    const ids = plan.prompt_ids || [];
    const allowance = plan.monthly_allowance || count;
    const rounds = count > 0 ? Math.floor(allowance / count) : null;
    return h('div',{}, details([
      ['Checks',paid ? 'Website and paid AI questions' : 'Website only'], ['Starting page',source(plan.site)],
      ['Website coverage','Up to '+plan.max_pages+' '+(plan.max_pages === 1 ? 'page' : 'pages')],
      ['AI coverage',paid ? amountLabel(plan.question_count,'question')+' · '+(plan.engines || []).map(CB.engine).join(', ') : null],
      ['Assistant repeats',paid ? plan.repeats : null],
      ['Schedule',calendarRule(plan)+' · '+plan.timezone],
      ['Next planned check',plan.planned_next_check && timestamp(plan.planned_next_check,plan.timezone)+' · '+plan.timezone],
      ['Same-day changes','One round per local calendar day. If the schedule already ran today, the new time applies on the next eligible date.'],
      ['Checks per round', count], ['Monthly allowance',amountLabel(allowance,'check')+' · '+rounds+' full '+(rounds === 1 ? 'round' : 'rounds')+' · UTC'],
      ['End date',plan.stop_date ? CB.day(plan.stop_date)+' (inclusive)' : 'Until paused'],
      ['Platform usage',plan.platform_usage], ['After the allowance is used','Citebase skips checks until the next UTC month. An enabled Apify schedule can still incur a start charge.'],
      ['End-date handling',plan.stop_policy]
    ]), paid && ids.length ? group('Selected questions',h('ul',{},ids.map(id=>h('li',{text:qNames.get(id) || id})))) : null);
  }
  function confirmSchedule(title, label, plan, submit, done, questions) {
    const usage = plan.scope === 'site_and_ai' && !CB.demo ? CB.usage.guard(plan.cap_per_occurrence_usd,{
      monthlyAllowance:plan.monthly_allowance, checksPerOccurrence:plan.checks_per_occurrence
    }) : null;
    const dialog = formDialog(title, [planFacts(plan,questions),usage && usage.node],label,async () => {
      if (usage) await usage.verify();
      if (!dialog.el.open) throw new Error('Schedule confirmation closed.');
      return submit();
    },done,usage);
    return dialog;
  }
  function scheduleSelection(title, defaultLabel, options, initial) {
    const fixed = new Set(initial || []);
    const picked = options.map(([id,label]) => {
      const input = h('input',{type:'checkbox',checked:fixed.has(id)});
      return {id,input,node:h('label',{class:'check'},input,label)};
    });
    const mode = select([['default',defaultLabel],['custom','Choose '+title.toLowerCase()]],fixed.size ? 'custom' : 'default');
    mode.setAttribute('aria-label',title);
    const list = h('div',{class:'form'},picked.map(item=>item.node));
    const toggle = () => { list.hidden = mode.value !== 'custom'; };
    mode.onchange = toggle; toggle();
    if (!options.length) mode.lastElementChild.disabled = true;
    return {node:h('div',{class:'form'},field(title,mode),list),value() {
      if (mode.value === 'default') return null;
      const ids = picked.filter(item=>item.input.checked).map(item=>item.id);
      if (!ids.length) throw new Error('Select at least one item under '+title+'.');
      return ids;
    }};
  }
  function scheduleEditor(project, done, current, questions, targetPage) {
    const initial = current || {};
    const form = fields([
      ['frequency','Frequency','select',[['monthly','Monthly'],['weekly','Weekly'],['daily','Daily']]],
      ['weekday','Day of the week','select',weekdays.map((day,i)=>[String(i),day])],
      ['month_day','Day of the month (1–28)','number'], ['local_time','Local start time','time'], ['timezone','Time zone'],
      ['url','Starting page (defaults to the project website)','url'], ['max_pages','Maximum pages per site check','number'],
      ['include_ai','Include paid AI question checks','checkbox'],
      ['monthly_allowance','Monthly allowance in checks','number'], ['stop_date','Last date for site and AI checks (optional)','date']
    ], {frequency:'monthly',timezone:Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',month_day:1,local_time:'08:00',
      ...initial,url:targetPage || initial.site || '',weekday:String(initial.weekday || 0),
      max_pages:targetPage ? 1 : initial.max_pages || 15,include_ai:!targetPage && initial.scope === 'site_and_ai'});
    const controls = form.controls;
    controls.month_day.min = 1; controls.month_day.max = 28; controls.month_day.required = true;
    controls.local_time.required = true; controls.timezone.required = true;
    controls.max_pages.min = 1; controls.max_pages.max = 30; controls.max_pages.required = true;
    controls.monthly_allowance.min = 1; controls.monthly_allowance.max = 100000;
    controls.monthly_allowance.placeholder = 'One full round per UTC month';
    const engines = scheduleSelection('AI engines','Use project engines',CB.ENGINES,initial.engines);
    const qOptions = new Map((questions || []).filter(q=>q.prompt_id).map(q=>[q.prompt_id,q.question || q.prompt || q.prompt_id]));
    (initial.prompt_ids || []).forEach(id=>{if (!qOptions.has(id)) qOptions.set(id,id);});
    const prompts = scheduleSelection('Questions','All saved questions',[...qOptions],initial.prompt_ids);
    const repeat = fields([['repeats','Repeats per assistant question','number']],{repeats:initial.repeats || 1});
    repeat.controls.repeats.min = 1; repeat.controls.repeats.max = 5; repeat.controls.repeats.required = true;
    const aiFields = h('div',{class:'form'},engines.node,prompts.node,...repeat.nodes,
      note('Google AI Overviews and AI Mode check each eligible buying question once.'));
    const dayFields = {weekday:h('div',{class:'form'},form.nodes[1]),month_day:h('div',{class:'form'},form.nodes[2])};
    function toggle() {
      aiFields.hidden = !controls.include_ai.checked;
      for (const [name,freq] of [['weekday','weekly'],['month_day','monthly']]) {
        controls[name].disabled = controls.frequency.value !== freq;
        dayFields[name].hidden = controls[name].disabled;
      }
    }
    controls.frequency.onchange = toggle; controls.include_ai.onchange = toggle; toggle();
    const stopHelp = note('Leave the allowance blank for one full round per UTC month. Each round includes one site check and any selected AI checks.');
    const parts = [current && targetPage ? note('This project already has a schedule. Confirming the revision changes its starting page and coverage.') : null,
      heading('When to run'),form.nodes[0],dayFields.weekday,dayFields.month_day,
      h('div',{class:'record-form-pair'},form.nodes[3],form.nodes[4]),heading('What to check'),...form.nodes.slice(5,8),
      aiFields,heading('Limits'),form.nodes[8],stopHelp,form.nodes[9]];
    formDialog(current ? 'Revise schedule' : 'Plan a check', parts, 'Preview schedule', async () => {
      const data = form.data();
      for (const name of ['stop_date','url','monthly_allowance']) if (!controls[name].value.trim()) delete data[name];
      if (data.frequency === 'weekly') data.weekday = Number(data.weekday); else delete data.weekday;
      if (data.frequency !== 'monthly') delete data.month_day;
      if (data.include_ai) {
        data.repeats = repeat.data().repeats;
        const platforms = engines.value(), ids = prompts.value();
        if (platforms) data.platforms = platforms;
        if (ids) data.prompt_ids = ids;
      }
      const preview = await get(project,'schedule_preview',data);
      const live = await get(project,'schedule_list');
      const bound = (live.schedules || [])[0];
      if ((bound && bound.plan_id) !== (current && current.plan_id) && (bound || current)) {
        throw new Error('This project’s schedule changed while you were editing. Close this form and open the current schedule to review it.');
      }
      return preview;
    }, plan => {
      confirmSchedule('Confirm schedule', current ? 'Apply revised schedule' : 'Enable this schedule', plan,
        () => write(project,'schedule_apply',{plan_id:plan.plan_id,confirmed:true}), () => {CB.toast('Schedule saved'); if (done) done();},questions);
    },null,project);
  }
  function scheduleRow(project, entry, refresh, questions) {
    const label = entry.enabled ? 'Pause' : 'Resume';
    const statuses = {active:'Active',paused:'Paused',ended:'End date reached',allowance_reached:'Monthly allowance reached',
      allowance_unverified:'Monthly allowance unavailable'};
    const checkStatus = entry.check_status || (entry.enabled ? 'active' : 'paused');
    const last = entry.last_occurrence;
    const check = entry.planned_next_check || (!entry.check_status ? entry.next_run : null);
    const next = check ? timestamp(check,entry.timezone)+' · '+entry.timezone :
      checkStatus === 'paused' ? 'Paused' : checkStatus === 'ended' ? 'End date reached' :
      checkStatus === 'allowance_unverified' ? 'Allowance must be verified before a check can start' :
      'No eligible check date reported';
    const checks = entry.checks_remaining == null ? null : CB.num(entry.checks_remaining)+' of '+amountLabel(entry.monthly_allowance,'check')+' remaining';
    const runHistory = h('a',{class:'ext',href:recordRoute(project,'evidence')+'?view=runs',text:'Open project run history'});
    return row(heading(entry.enabled ? 'Scheduled checks' : 'Paused checks'),
      h('div',{class:'record-meta'},h('strong',{class:'record-state',text:statuses[checkStatus] || words(checkStatus)}),
        h('span',{text:calendarRule(entry)+' · '+entry.timezone})), details([
      ['Next eligible check',next], ['Next Apify trigger',entry.enabled && entry.next_run && (entry.next_run !== check || checkStatus !== 'active') ?
        timestamp(entry.next_run,entry.timezone)+' · '+entry.timezone : null],
      ['Coverage',entry.scope === 'site_and_ai' ? 'Website and '+amountLabel(entry.question_count,'AI question')+' on '+(entry.engines || []).map(CB.engine).join(', ') :
        'Website · up to '+amountLabel(entry.max_pages,'page')],
      ['This UTC month',checks], ['Allowance renews',checkStatus === 'allowance_reached' && entry.allowance_resets_at ?
        timestamp(entry.allowance_resets_at,'UTC')+' UTC' : null],
      ['Last check',last ? timestamp(last.scheduled_at,entry.timezone)+' · '+words(last.status) : words(entry.last_outcome) || 'No recorded check'],
      ['AI answers saved',last && last.snapshot ? (last.expected_answers != null ?
        (last.matched_answers == null ? last.saved_answers : last.matched_answers)+' of '+last.expected_answers+' planned' : last.saved_answers) : null],
      ['AI datasets with matching answers',last && last.expected_datasets != null ? last.saved_datasets+' of '+last.expected_datasets : null]
    ]), entry.needs_manual_pause ? h('div',{role:'alert'},note('Apify still has this trigger enabled. Pause it to stop further platform starts.'),
      source('https://console.apify.com/schedules/'+encodeURIComponent(entry.schedule_id),'Pause in Apify Console')) : null,
      group('Scope and allowance',planFacts(entry,questions)),actions(runHistory,
        last && last.run_id ? source('https://console.apify.com/view/runs/'+encodeURIComponent(last.run_id),'View last run in Apify') : null),
      CB.demo ? note('This is a sample schedule. Sign in to manage checks for your website.') :
      actions((entry.enabled || checkStatus !== 'ended') ? button(label+' schedule', () =>
      entry.enabled ? formDialog('Pause schedule?', [note('Pausing stops future starts. A check already in progress can finish.'),planFacts(entry,questions)], 'Pause schedule', () =>
        write(project,'schedule_pause',{plan_id:entry.plan_id,schedule_id:entry.schedule_id,confirmed:true}), refresh) :
      confirmSchedule('Resume schedule?', 'Resume schedule',entry, () =>
        write(project,'schedule_resume',{plan_id:entry.plan_id,schedule_id:entry.schedule_id,confirmed:true}), refresh,questions)) : null,
      button('Revise schedule', () => scheduleEditor(project, refresh, entry, questions))));
  }
  function reminder(project) {
    const when = h('input',{type:'date',required:true});
    formDialog('One-time reminder',[field('Review date',when),note('Download a calendar event. Opening the reminder takes you to the project.')],
      'Download reminder',() => {
        if (!when.reportValidity()) throw new Error('Choose a date.');
        const date = when.value.replace(/-/g,'');
        const link = new URL(location.href); link.search=''; link.hash='/p/'+encodeURIComponent(project)+'/overview';
        const stamp = new Date().toISOString().replace(/[-:]/g,'').replace(/\.\d{3}/,'');
        const text = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Citebase//Project review//EN','BEGIN:VEVENT',
          'UID:'+crypto.randomUUID()+'@citebase','DTSTAMP:'+stamp,'DTSTART;VALUE=DATE:'+date,
          'SUMMARY:Review '+project+' in Citebase','URL:'+link.href,'END:VEVENT','END:VCALENDAR',''].join('\r\n');
        const objectURL = URL.createObjectURL(new Blob([text],{type:'text/calendar;charset=utf-8'}));
        const anchor = h('a',{href:objectURL,download:project+'-review.ics'});
        document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(objectURL),1000);
      });
  }
  function changeAlert(project, alert) {
    if (!alert || !alert.message) return null;
    const proof = h('a',{class:'ext',href:recordRoute(project,'evidence')+'?view=changes',text:'Review changes'});
    return h('aside',{class:'snapshot-alert'},heading('Recommendation change'),h('p',{text:alert.message}),
      alert.compared_questions ? note('Compared '+alert.compared_questions+' buying '+(alert.compared_questions === 1 ? 'question' : 'questions')+
        ' across '+alert.compared_answers_per_round+' saved '+(alert.compared_answers_per_round === 1 ? 'answer' : 'answers')+' per round.') : null,
      (alert.examples || []).length ? h('ul',{},alert.examples.map(example=>h('li',{text:example}))) : null,
      actions(proof,sectionLink(project,'questions','Open saved questions')));
  }
  function schedulesBox(project, questions, done, listLegacy, alert) {
    const box = card('Next check');
    const change = changeAlert(project,alert); if (change) box.appendChild(change);
    reader(box, () => get(project,'schedule_list'), (content,result,refresh) => {
      const rows = result.schedules || [];
      const reloaded = () => { refresh(); if (done) done(); };
      if (rows.length) rows.forEach(entry => content.appendChild(scheduleRow(project,entry,reloaded,questions)));
      else content.appendChild(h('div', {}, note('No shared schedule for this project. Choose a time for site checks and add paid AI questions if needed.'), actions(button('Plan a check', () => scheduleEditor(project,reloaded,null,questions)),button('One-time reminder',()=>reminder(project)))));
      if (listLegacy) {
        const legacy = h('div',{}); content.appendChild(legacy);
        reader(legacy, async () => {
          const schedules = []; let offset = 0;
          while (true) {
            const page = await CB.apify('GET','schedules?limit=100&offset='+offset);
            const batch = page.items || [];
            schedules.push(...batch.filter(s => s.name === 'citebase-'+project && !rows.some(r => r.schedule_id === s.id)));
            offset += batch.length;
            if (!batch.length || (page.total == null ? batch.length < 100 : offset >= page.total)) return schedules;
          }
        }, (el,old) => old.forEach(s => el.appendChild(row(heading('Earlier Apify schedule'),
          note((s.isEnabled ? 'Enabled' : 'Paused') + ' · Managed in Apify Console'), source('https://console.apify.com/schedules/'+encodeURIComponent(s.id),'Manage in Console')))));
      }
    });
    return box;
  }
  UI.schedule = function (project, done) {
    const session = CB.sessionId();
    CB.history(project).then(d => {
      if (session !== CB.sessionId()) return;
      F.dialog('Project schedule', schedulesBox(project, d.questions || [], done, true,d.scheduled_alert), [{label:'Close',ghost:true}]);
    }, e => { if (session === CB.sessionId()) CB.toast(e.message,true); });
  };
  UI.schedules = function (main, projects) {
    main.appendChild(h('div',{class:'head'}, h('h1',{text:'Schedules'})));
    if (!projects.length) { main.appendChild(note('Add a project to schedule its next check.')); return; }
    const query = new URLSearchParams(location.hash.split('?')[1] || '');
    const offeredProject = query.get('project');
    const selected = projects.find(p => p.project === offeredProject);
    if (query.has('plan')) {
      const proposal = query.get('plan');
      const exact = query.size === 2 && query.getAll('plan').length === 1 && query.getAll('project').length === 1;
      if (!exact || !selected || !/^[0-9a-f]{64}$/.test(proposal) || CB.demo) {
        main.appendChild(note('This schedule proposal is unavailable in this workspace.'));
      } else {
        reader(main, () => Promise.all([get(offeredProject,'schedule_preview',{plan_id:proposal}),CB.history(offeredProject)]),
          (host,[plan,history]) => {
            const label = plan.revises_existing ? 'Apply revised schedule' : 'Enable this schedule';
            host.appendChild(h('section',{class:'card'},heading('Saved schedule proposal'),
              note((selected.brand || offeredProject) + ' · ' + calendarRule(plan) + ' · ' + plan.timezone),
              button('Review saved proposal', () => confirmSchedule('Confirm schedule',label,plan,
                () => write(offeredProject,'schedule_apply',{plan_id:plan.plan_id,confirmed:true}),
                () => { CB.toast('Schedule saved'); location.hash = '#/schedules?project='+encodeURIComponent(offeredProject); },history.questions || []))));
          });
      }
      main.appendChild(h('a',{class:'ext',href:'#/schedules',text:'View all schedules'}));
      return;
    }
    const selector = select(projects.map(p=>[p.project,p.brand || p.project]), selected ? offeredProject : projects[0].project);
    const results = h('div',{});
    main.append(field('Project',selector), results);
    function show() {
      const project = selector.value;
      CB.clear(results);
      reader(results,()=>CB.history(project),(target,d) => target.appendChild(schedulesBox(project,d.questions || [],null,true,d.scheduled_alert)));
    }
    selector.onchange = show; show();
  };
  function projectEvidence(project, url, label) {
    if (!url) return null;
    const prefix = '#/p/'+encodeURIComponent(project)+'/';
    if (url.startsWith(prefix) && /^\w+$/.test(url.slice(prefix.length))) return sectionLink(project,url.slice(prefix.length),label || 'Review evidence');
    return source(url,label);
  }
  function opportunityRow(project,o) {
    const channel = {answers:'AI answers',technical:'Site audit',search:'Google search',off_page:'Cited publishers'}[o.channel] || words(o.channel);
    return row(h('div',{class:'record-meta'},h('span',{class:'record-state',text:channel}),
      o.observed_on ? h('span',{text:CB.day(o.observed_on)}) : null),
      heading(o.question || o.title),o.coverage ? h('p',{class:'record-signal',text:o.coverage}) : null,
      o.suggested_action ? h('p',{class:'record-next'},h('strong',{text:'Next step. '}),o.suggested_action) : null,
      group('Finding details',details([['Finding',o.question ? o.title : null],['Page',source(o.page)],
        ['Saved source',o.source],['Manual alternative',o.manual_alternative]])),
      actions(button('Create action', () => actionEditor(project,{title:o.question || o.title, page_url:o.page || '',
        finding_id:o.id, evidence:[o.title,o.source,o.observed_on,o.coverage].filter(Boolean).join(' · '),
        rationale:o.suggested_action || '', evidence_url:CB.safeUrl(o.evidence_url) || '', question:o.question || ''},
        result => { location.hash=recordRoute(project,'todo',result.action.id); })),
      projectEvidence(project,o.evidence_url,'Open evidence')));
  }
  function score(sample) {
    if (!sample || !sample.answers) return 'No sample';
    return sample.recommended + ' recommended · ' + sample.cited + ' cited · ' + sample.answers + ' answers';
  }
  function findingsPanel(project) {
    const opportunities = card('Opportunities');
    const filter = fields([['channel','Channel','select',[['','All channels'],['answers','AI answers'],['technical','Site audit'],['off_page','Cited publishers'],['search','Google search']]],
      ['page','Page'],['question','Question'],['since','Observed since','date']],{});
    let query = {}, enter = true;
    const reset = button('Clear filters',()=>{filterForm.reset();query={};reload();});
    reset.hidden = true;
    const filterForm = h('form',{class:'work-filters'}, filter.nodes, h('button',{class:'btn small',type:'submit',text:'Apply filters'}),reset);
    opportunities.appendChild(filterForm);
    const reload = reader(opportunities,()=>get(project,'opportunities_list', query),(el,result) => {
      const filtered = Object.keys(query).length > 0;
      reset.hidden = !filtered;
      const found = result.opportunities || [];
      const channels = [['answers','AI answers','brand'],['technical','Site audit','e1'],['off_page','Cited publishers','e2'],['search','Google search','e3']];
      const bar = CB.summaryBar(channels.map(([key,label,tone]) => ({key,label,tone,count:found.filter(o => o.channel === key).length})),
        query.channel || 'all', key => { filter.controls.channel.value = key === 'all' ? '' : key; filterForm.requestSubmit(); }, 'Filter findings by type');
      const list = h('div',{});
      el.append(...(bar ? [bar] : []), list);
      recordList(list,found,{project,tab:'evidence',id:!filtered && selectedRecord(project,'evidence'),focus:enter,noun:'finding',
        empty:filtered ? 'No saved findings match these filters.' : 'No findings yet. A saved site audit or AI answer round can surface the first opportunity.',
        row:o=>opportunityRow(project,o)});
      enter = false;
    });
    filterForm.onsubmit = e => { e.preventDefault(); query = Object.fromEntries(Object.entries(filter.data()).filter(([,v]) => v)); reload(); };
    return opportunities;
  }
  const movements = new Set(['gained','lost','increased','decreased']);
  const comparisonLabels = {gained:'New recommendation',lost:'Recommendation lost',increased:'Recommended more often',
    decreased:'Recommended less often',unchanged:'Same recommendation count',missing_baseline:'No earlier answer',
    missing_current:'No recent answer',unsampled:'No saved answers',changed_coverage:'Different coverage',changed_panel:'Different questions'};
  function questionChange(project,q) {
    const sources = (q.cited_sources || []).map(cite => {
      if (typeof cite === 'string') return h('span',{text:cite});
      return source(cite.url,cite.site || cite.url) || h('span',{text:cite.site});
    });
    return row(h('div',{class:'record-meta'},h('span',{class:'record-state',text:CB.engine(q.engine)}),
      h('span',{text:comparisonLabels[q.status] || words(q.status)})),
      heading(q.question || q.prompt_id),
      details([['Previous',score(q.before)],['Current',score(q.after)],['Destination page',source(q.destination_page)],
        ['Sources cited',sources.length ? h('div',{class:'work-links'},sources) : null]]),
      projectEvidence(project,q.evidence_url,'Open saved evidence'));
  }
  function changesPanel(project) {
    const weekly = card('Changes between saved rounds');
    const date = h('input',{type:'date'});
    weekly.appendChild(field('Changes since',date));
    const reloadChanges = reader(weekly,()=>get(project,'changes_list',date.value ? {since:date.value} : {}),(el,r) => {
      const c = r.coverage || {};
      const questions = r.questions || [], changed = r.changes || [];
      el.appendChild(h('p',{class:'record-signal',text:r.from_date && r.to_date ?
        'Comparing '+CB.day(r.from_date)+' with '+CB.day(r.to_date)+'.' : r.current_round ?
          'One round is available for this comparison.' : 'No saved AI round in this period.'}));
      if (c.stale) el.appendChild(note('The latest observation is over two weeks old.'));
      el.appendChild(group('Dates and coverage',details([['Previous round',r.previous_round],['Current round',r.current_round],
        ['Days apart',r.interval_days], ['Question set',words(c.panel)], ['Engines',(c.engines || []).map(CB.engine).join(', ')],
        ['Missing questions',(c.unobserved_prompt_ids || []).join(', ')],['Coverage note',c.note]])));
      if (changed.length) el.appendChild(group(changed.length+' change'+(changed.length === 1 ? '' : 's')+' in this period',
        changed.map(v=>row(heading(v.title),note(v.detail),details([['Source',v.source],['Observed',v.observed_on]])))));
      if (!questions.length) { if (!changed.length) el.appendChild(note('No comparable change for this period.')); return; }
      const engines = Array.from(new Set(questions.map(q=>q.engine))).sort().map(key=>[key,CB.engine(key)]);
      const engine = select([['','All engines'],...engines],'');
      const movement = select([['','All comparisons'],['changed','Recommendation changed'],['unchanged','No change'],['coverage','Coverage to review']],'');
      const results = h('div',{});
      const draw = () => {
        const list = questions.filter(q=>(!engine.value || q.engine === engine.value) &&
          (!movement.value || (movement.value === 'changed' ? movements.has(q.status) :
            movement.value === 'coverage' ? !movements.has(q.status) && q.status !== 'unchanged' : q.status === 'unchanged')));
        recordList(results,list,{noun:'comparison',row:q=>questionChange(project,q),empty:'No question and engine pairs match this selection.'});
      };
      engine.onchange = movement.onchange = draw;
      el.append(h('div',{class:'record-toolbar'},field('AI engine',engine),field('What changed',movement)),results);
      draw();
    });
    date.onchange = reloadChanges;
    return weekly;
  }
  function runsPanel(project) {
    const runs = card('Project runs');
    reader(runs,()=>get(project,'runs_list'),(el,data) => {
      recordList(el,data.runs || [],{noun:'run',empty:'No saved run attributed to this project.',
        row:v=>row(heading(v.snapshot || v.id),details([['Status',words(v.status)], ['Date',v.observed_on],
          ['Run ID',v.id],['Evidence',projectEvidence(project,v.evidence_url,'Open evidence')]]))});
    });
    return runs;
  }
  UI.evidence = function (body,d,project) {
    const views = [['findings','Findings',findingsPanel],['changes','Changes',changesPanel],['runs','Run history',runsPanel]];
    const options = new URLSearchParams(location.hash.split('?')[1] || '');
    const active = !options.has('record') && views.some(([key])=>key === options.get('view')) ? options.get('view') : 'findings';
    const controls = h('div',{class:'record-switch',role:'group','aria-label':'Evidence view'});
    const panels = new Map();
    body.appendChild(controls);
    function show(key) {
      for (const [view,,render] of views) {
        const selected = view === key;
        const btn = controls.querySelector('[data-view="'+view+'"]');
        btn.setAttribute('aria-pressed',String(selected));
        if (selected && !panels.has(view)) { const panel = render(project); panels.set(view,panel); body.appendChild(panel); }
        if (panels.has(view)) panels.get(view).hidden = !selected;
      }
    }
    views.forEach(([key,label]) => {
      controls.appendChild(h('button',{type:'button','data-view':key,text:label,onclick:()=>{
        if (controls.querySelector('[data-view="'+key+'"]').getAttribute('aria-pressed') === 'true') return;
        // Keep the subview on reload. A change of evidence view leaves any record selection.
        history.replaceState(history.state,'',recordRoute(project,'evidence')+(key === 'findings' ? '' : '?view='+key));
        if (panels.has('findings') && panels.get('findings').querySelector('[data-selected-record],.record-notice')) {
          panels.get('findings').remove();panels.delete('findings');
        }
        show(key);
      }}));
    });
    show(active);
  };

  function prospectEditor(project,p,options,refresh) {
    const form = fields([
      ['recipientType','Who is the recipient?','select',options.recipientTypes],
      ['email','Recipient email','email'],['sourceUrl','Specific source page','url'],['readerFit','Why this fits their readers','textarea'],
      ['asset','What you can offer','textarea'],['contactProvenance','Where you found the contact'],
      ['lastContact','Last contact','date'],['outcome','Outreach outcome','select',options.outcomes],
      ['proofUrl','Published URL you have verified','url']
    ],p);
    form.controls.email.readOnly = !!p.id;
    const guidance = note('');
    const update = () => {guidance.textContent = options.guidance[form.controls.recipientType.value] || '';};
    form.controls.recipientType.onchange = update; update();
    formDialog(p.id ? 'Update prospect' : 'Add a prospect', [form.nodes[0],guidance,...form.nodes.slice(1)],
      'Save prospect',() => write(project,'prospect_save',{...form.data(),id:p.id || undefined,expected_revision:p.revision || 0}),refresh);
  }
  function draftEditor(project,p,refresh) {
    const f = fields([['subject','Subject'],['body','Exact message','textarea']],p.draft || {});
    formDialog('Edit outreach draft',[details([['Recipient',p.email]]),...f.nodes],
      'Save draft',() => write(project,'draft_save',{prospectId:p.id,expected_revision:p.draft ? p.draft.revision : 0,...f.data()}),refresh);
  }
  function prospectRow(project,p,options,refresh) {
    const draft = p.draft, consumed = draft && p.closedDraftVersion === draft.version, stopped = p.suppressed || p.outcome === 'declined';
    const buttons = actions(button('Update prospect',()=>prospectEditor(project,p,options,refresh)));
    if (p.citationVerified && draft?.approved && CB.citationOutreach) {
      buttons.appendChild(button('Review Gmail handoff',()=>CB.citationOutreach.review(project,p)));
    }
    if (!stopped) buttons.appendChild(button(draft ? 'Edit draft' : 'Write draft',()=>draftEditor(project,p,refresh)));
    const preview = draft ? group('Saved draft',details([['To',draft.to],['Subject',draft.subject]]),h('p',{class:'work-preview',text:draft.body})) : null;
    if (!stopped && draft && !draft.approved && !consumed) buttons.appendChild(button('Review for approval',()=>formDialog('Approve this exact draft?',[
      details([['To',draft.to],['Subject',draft.subject]]), h('p',{class:'work-preview',text:draft.body}),
      note('Approval records this version. Delivery is a separate step in your email account.')
    ],'Approve draft',()=>write(project,'draft_approve',{prospectId:p.id,version:draft.version,expected_revision:draft.revision}),refresh)));
    return row(heading(p.email),details([['Recipient type',words(p.recipientType)],['Outcome',words(p.outcome)],
      ['Contact status',p.suppressed ? 'Suppressed' : null],['Source',source(p.sourceUrl)],['Reader fit',p.readerFit],
      ['Asset',p.asset],['Contact source',p.contactProvenance],['Last contact',p.lastContact],
      ['Verified placement',source(p.proofUrl)],['Draft',draft ? (consumed ? 'Contact recorded' : draft.approved ? 'Approved for this version' : 'Awaiting approval') : null]]),preview,buttons);
  }
  function clientPreview(v) {
    return details([['What changed',v.whatChanged], ['Needs a decision',v.needsDecision], ['Next check',v.nextCheck]]);
  }
  function issueRow(project, issue, result) {
    const v = issue.preview || {};
    const recipients = result.recipients || [];
    const prepare = () => formDialog('Review email copies', [
      clientPreview(v),details([['Recipients',recipients.join(', ')]])
    ], 'Prepare copies', () => write(project,'digest_handoff',{
      week:issue.week,version:issue.version,recipients,confirmed:true
    }), handoff => {
      F.dialog('Prepared email copies', h('div',{},note('Copy each message to your own email account for delivery.'),
        handoff.messages.map(m=>row(heading(m.to), note(m.subject), h('p',{class:'work-preview',text:m.body}),
          button('Copy message',e=>F.copy(m.subject+'\n\n'+m.body,e.currentTarget))))), [{label:'Close',ghost:true}],{wide:true});
    });
    return group(issue.periodStart+' – '+issue.periodEnd, clientPreview(v),
      issue.status === 'muted' ? note('Muted this week.') : (result.enabled && recipients.length && issue.version ? button('Prepare email copies',prepare) : null));
  }
  function digestBox(project) {
    const box = card('Weekly client summary');
    reader(box,()=>get(project,'digest_get'),(el,result,refresh) => {
      const v = result.preview || {};
      el.appendChild(h('div',{},note(result.enabled ? 'Enabled. Your first visit each week adds the previous week’s summary to the archive.' : 'Optional · currently off.'),
        heading('Current preview'),clientPreview(v),
        result.currentIssue && result.currentIssue.status === 'muted' ? note('The week ending '+result.currentIssue.periodEnd+' was muted because it had no changes.') : null,
        actions(button('Summary settings',()=>{
          const form = fields([['enabled','Enable the weekly summary','checkbox'],['recipients','Recipient emails, one per line','lines'],
            ['muteUnchanged','Mute unchanged weeks','checkbox']],result);
          formDialog('Summary settings',[...form.nodes,note(result.handoff)],'Save settings',()=>write(project,'digest_save',{...form.data(),expected_revision:result.revision || 0}),refresh);
        }),button('Copy client preview', e=>F.copy([v.whatChanged,v.needsDecision,v.nextCheck].filter(Boolean).join('\n'),e.currentTarget)),
        sectionLink(project,'evidence','Review the signed-in evidence')),
        (result.archive || []).length ? h('div',{},heading('Weekly archive'),result.archive.map(issue=>issueRow(project,issue,result))) : null));
    });
    return box;
  }
  UI.outreach = function (body,d,project) {
    const box = card('Prospects and drafts'); body.append(box,digestBox(project));
    reader(box,()=>get(project,'prospects_list'),(el,data,refresh) => {
      el.appendChild(button('Add a prospect',()=>prospectEditor(project,{},data,refresh),true));
      if (!data.prospects.length) el.appendChild(note('Save a specific source page and its reader fit before drafting a pitch.'));
      data.prospects.forEach(p=>el.appendChild(prospectRow(project,p,data,refresh)));
    });
  };
  UI.overview = function (body,project,questions) {
    const projectChecks = schedulesBox(project,questions,null,false);
    const next = card('Suggested follow-on');
    body.appendChild(projectChecks); body.appendChild(next);
    reader(next,()=>get(project,'offers_list'),(el,data,refresh)=>{
      const offer = data.offer;
      if (!offer) { next.hidden = true; return; }
      next.hidden = false;
      el.appendChild(h('div',{},heading(offer.title),note(offer.detail),note(offer.manual_alternative),
        actions(button('Preview page recheck',async e=>{
          const b = e.currentTarget, session = CB.sessionId();
          b.disabled = true;
          try {
            const result = await get(project,'schedule_list');
            if (session === CB.sessionId()) scheduleEditor(project,refresh,(result.schedules || [])[0],questions,offer.page);
          } catch (err) { if (session === CB.sessionId()) CB.toast(err.message,true); }
          finally { b.disabled = false; }
        }),sectionLink(project,'todo','Review saved action'),
          button('Dismiss suggestion', async e=>{
            const b = e.currentTarget; b.disabled = true;
            try { await write(project,'offer_dismiss',{id:offer.id}); refresh(); }
            catch(err) { b.disabled=false; CB.toast(err.message,true); }
          }))));
    });
  };

})();
