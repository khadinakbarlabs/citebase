/* Citebase dashboard actions: dialogs, new project, site check, paid AI check (start, watch, import), schedules,
   next steps, report, questions. Everything goes through Citebase's own tools or Apify's API with the visitor's
   own token. Paid starts show their data charge cap and check the account's current usage before submission. */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h;
  var F = CB.flows = {};
  F.setupAddress = 'https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run';

  /* ---------- dialog and small helpers ---------- */
  F.dialog = function (title, body, buttons, opts) {
    opts = opts || {};
    var account = CB.sessionId();
    var dlg = h('dialog', { class: 'dlg' + (opts.wide ? ' wide' : ''), 'aria-label': title });
    var foot = h('div', { class: 'dlg-foot' });
    function close() { if (dlg.open) dlg.close(); dlg.remove(); }
    dlg.addEventListener('click', function (event) {
      if (account === CB.sessionId()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      close();
    }, true);
    (buttons || []).forEach(function (b) {
      var btn = h('button', { type: 'button', class: 'btn' + (b.ghost ? ' ghost' : '') + (b.danger ? ' danger' : ''), text: b.label });
      btn.addEventListener('click', function () { if (b.onclick) b.onclick(close, btn); else close(); });
      foot.appendChild(btn);
    });
    dlg.appendChild(h('div', { class: 'dlg-head' }, h('h2', { text: title }), h('button', { type: 'button', class: 'x', 'aria-label': 'Close', text: '×', onclick: close })));
    dlg.appendChild(h('div', { class: 'dlg-body' }, body));
    if (buttons && buttons.length) dlg.appendChild(foot);
    dlg.addEventListener('cancel', function (e) { e.preventDefault(); close(); });
    document.body.appendChild(dlg); dlg.showModal();
    return { close: close, el: dlg, foot: foot };
  };
  function field(label, input, hint) { return h('label', { class: 'field' }, h('span', { text: label }), input, hint ? h('small', { text: hint }) : null); }
  function busy(btn, on, text) { if (!btn) return; btn.disabled = on; if (text) btn.textContent = text; }
  function slugify(t) { return String(t || '').toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40); }
  function lines(t) { return String(t || '').split('\n').map(function (x) { return x.trim(); }).filter(Boolean); }
  function progress(list) {
    var ol = h('ol', { class: 'progress-steps' });
    var items = list.map(function (t) { var li = h('li', { text: t }); ol.appendChild(li); return li; });
    return { el: ol, set: function (i, state, text) { items[i].className = state; if (text) items[i].textContent = text; } };
  }
  function actorPath(name) { return 'acts/' + String(name).replace('/', '~'); }
  F.copy = function (text, btn) {
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () {
      CB.toast('Copied');
      if (btn) { var t = btn.textContent; btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = t; }, 1500); }
    }, function () { CB.toast('Copy failed: select the text and copy it by hand.', true); });
  };
  F.copyBox = function (text, label) {
    var b = h('button', { type: 'button', class: 'btn tiny', text: label || 'Copy' });
    b.addEventListener('click', function () { F.copy(text, b); });
    return h('div', { class: 'copybox' }, h('code', { text: text }), b);
  };
  function errorIn(body, e) { CB.clear(body).appendChild(CB.usage.errorDetails(e) || h('p', { class: 'form-err', text: e.message })); }

  function sampleOnly() {
    if (!CB.demo) return false;
    CB.toast('Sign in with Apify to save your own project or run a check.');
    return true;
  }

  /* ---------- new project ---------- */
  var activeSiteAudits = new Set();
  function runSiteAudit(project, url, pages) {
    var key = CB.sessionId() + '/' + project;
    if (activeSiteAudits.has(key)) return Promise.reject(new Error('A site audit is already running for this project.'));
    activeSiteAudits.add(key);
    return CB.tool('audit_site', { project: project, url: url, max_pages: pages }).finally(function () { activeSiteAudits.delete(key); });
  }
  function auditReceipt(audit) {
    var blocked = audit.status === 'unreadable';
    var title = blocked ? 'The site could not be read' : audit.saved ? 'Site audit saved' : 'Site audit finished';
    var counts = audit.counts || {}, first = (audit.problems || [])[0];
    var metrics = [
      [Number.isFinite(audit.health_score) ? audit.health_score + '/100' : null, 'Site health'],
      [audit.pages_checked, 'Pages checked'], [counts.fail, 'High priority'], [counts.warn, 'Warnings']
    ].filter(function (item) { return item[0] != null; });
    return h('section', { class: 'audit-receipt', role: 'status' }, h('h3', { text: title }),
      blocked ? h('p', { text: audit.headline || 'Check the address and crawler access, then run a new audit.' }) :
        h('dl', {}, metrics.map(function (item) { return h('div', {}, h('dt', { text: item[1] }), h('dd', { text: String(item[0]) })); })),
      audit.status === 'partial' ? h('p', { text: 'The crawl reached its time limit. The results cover the pages it could read.' }) : null,
      !blocked && first && first.check ? h('div', { class: 'audit-first-finding' }, h('b', { text: first.check }),
        first.detail ? h('p', { text: first.detail }) : null) : null);
  }
  function projectWebsite(value) {
    var text = value.trim();
    if (!text || /\s|\\/.test(text)) throw new Error('Enter a website such as yourbrand.com.');
    var url;
    try {
      var address = /^[a-z][a-z\d+.-]*:/i.test(text) ? text : 'https://' + text;
      url = new URL(address);
    } catch (_) { throw new Error('Enter a website such as yourbrand.com.'); }
    if (url.username || url.password) throw new Error('Use a website address without a username or password.');
    if (!/^https?:$/.test(url.protocol) || !url.hostname.includes('.') || /^\/\//.test(text)) {
      throw new Error('Enter a website such as yourbrand.com.');
    }
    if (url.href.length > 200) throw new Error('Use a website address of 200 characters or fewer.');
    return url;
  }
  F.projectWebsite = projectWebsite;
  F.newProject = function (done, onDirectoryChange) {
    if (sampleOnly()) return;
    var account = CB.sessionId();
    var site = h('input', { type: 'text', inputmode: 'url', required: true, autocapitalize: 'none', spellcheck: 'false', placeholder: 'yourbrand.com', autocomplete: 'url' });
    var name = h('input', { type: 'text', placeholder: 'Your brand', maxlength: 200, autocomplete: 'organization' });
    var slug = h('input', { type: 'text', placeholder: 'yourbrand-com', maxlength: 40, spellcheck: 'false', autocapitalize: 'none' });
    var rivals = h('input', { type: 'text', placeholder: 'Rival One, Rival Two' });
    var language = h('input',{type:'text', placeholder:'e.g. en', maxlength:'8'});
    var regions = typeof Intl.DisplayNames === 'function' ? new Intl.DisplayNames(['en'],{type:'region'}) : null;
    var markets = 'ae au bd be br ca ch de eg es fr gb id ie in it jp ke mx my ng nl nz ph pk pl pt sa se sg us za'.split(' ');
    var choices = markets.map(function (code) { return [code,regions ? regions.of(code.toUpperCase()) : code.toUpperCase()]; })
      .sort(function (a,b) { return a[1].localeCompare(b[1]); });
    var country = h('select', {}, h('option',{value:'',text:'Choose a market'}),
      choices.map(function (c) { return h('option', {value:c[0],text:c[1]}); }), h('option',{value:'other',text:'Another country…'}));
    var customCountry = h('input',{type:'text',maxlength:'2',placeholder:'Two-letter code',autocapitalize:'characters'});
    var otherMarket = field('Country code',customCountry,'Use the two-letter code, such as DK for Denmark.');
    otherMarket.hidden = true;
    country.onchange = function () { otherMarket.hidden = country.value !== 'other'; if (!otherMarket.hidden) customCountry.focus(); };
    var qs = h('textarea', { rows: '4', placeholder: 'Which payroll software works for a ten-person company?' });
    var touched = false, named = false;
    name.addEventListener('input', function () { named = true; });
    slug.addEventListener('input', function () { touched = true; });
    site.addEventListener('input', function () {
      var host = '';
      try { host = projectWebsite(site.value).hostname.replace(/^www\./i,''); } catch (_) { /* Still entering an address. */ }
      if (!named) name.value = host;
      if (!touched) slug.value = slugify(host);
    });
    var err = h('div', { class: 'form-err', role: 'alert' });
    var details = h('details', { class: 'work-details project-options' }, h('summary', { text: 'Project details and buying questions' }),
      h('div', { class: 'project-options-fields' },
        h('div', { class: 'two' }, field('Brand name', name), field('Project name', slug, '3 to 40 letters, numbers or dashes.')),
        field('Competitors', rivals, 'Separate brand names with commas.'),
        h('div', { class: 'two' }, field('Country', country), field('Language code', language, 'For example, en or fr.')), otherMarket,
        field('Buying questions', qs, 'One per line, as a customer would ask an AI. You can add these later.')));
    var fields = h('fieldset', { class: 'project-form-fields' }, field('Website', site), details);
    var status = h('div', { class: 'project-create-status', hidden: true });
    var form = h('form', { class: 'form project-create', novalidate: true },
      h('p', { class: 'audit-intro', text: 'Save your website and audit up to 15 public pages. Apify platform usage applies.' }),
      fields, status, err, h('button', { type: 'submit', hidden: true, tabindex: '-1', text: 'Create and check the site' }));
    var d = F.dialog('New project', form, [{ label: 'Cancel', ghost: true }, { label: 'Create and check the site', onclick: submit }], { wide: true });
    var primary = d.foot.lastElementChild, savedProject = '', directoryChanged = false;
    function active() { return account === CB.sessionId() && d.el.isConnected; }
    function refreshDirectory() {
      if (directoryChanged && account === CB.sessionId() && !d.el.isConnected && onDirectoryChange) {
        directoryChanged = false; onDirectoryChange();
      }
    }
    d.el.addEventListener('close', refreshDirectory);
    function invalid(input, message) {
      err.textContent = message;
      if (details.contains(input)) details.open = true;
      input.focus();
    }
    function existing(p) {
      invalid(slug, 'A project with this name is already saved. Choose another name or open it below.');
      err.appendChild(h('a', { class: 'existing-project', href: '#/p/' + encodeURIComponent(p) + '/overview',
        text: 'Open existing project', onclick: function () { d.close(); } }));
    }
    function canOpen(p) {
      savedProject = p;
      busy(primary, false, 'Open the project');
      d.foot.firstElementChild.textContent = 'Close';
    }
    async function submit(close, btn) {
      if (btn.disabled) return;
      if (savedProject) { close(); done(savedProject); return; }
      CB.clear(err);
      var parsed;
      try { parsed = projectWebsite(site.value); }
      catch (error) { invalid(site, error.message); return; }
      var url = parsed.href, p = slugify(slug.value).replace(/-$/, '');
      var market = country.value === 'other' ? customCountry.value.trim().toLowerCase() : country.value;
      if (country.value === 'other' && !/^[a-z]{2}$/.test(market)) { invalid(customCountry, 'Enter the two-letter country code or choose a market.'); return; }
      if (!name.value.trim()) name.value = CB.host(url);
      if (language.value.trim() && !/^[a-z]{2,3}(?:-[a-z0-9]{2,4})?$/i.test(language.value.trim())) { invalid(language, 'Use a language code such as en or fr.'); return; }
      if (p.length < 3) { invalid(slug, 'The project name needs at least 3 letters or numbers.'); return; }
      var competitors = rivals.value.split(',').map(function (x) { return x.trim(); }).filter(Boolean);
      if (competitors.length > 20) { invalid(rivals, 'Enter up to 20 competitors.'); return; }
      var brand = { name: name.value.trim(), domain: parsed.hostname.replace(/^www\./, ''), site: url,
        competitors: competitors };
      var questions = lines(qs.value);
      if (questions.length > 60) { invalid(qs, 'Enter up to 60 buying questions.'); return; }
      var payload = { project: p, brand: brand, settings: { country: market, language: language.value.trim().toLowerCase() } };
      if (CB.hasProjectWork) payload.create_only = true;
      fields.disabled = true;
      busy(btn, true, 'Checking project name…');
      try {
        var directory = await CB.history(undefined, true);
        if (!active()) return;
        if ((directory.projects || []).some(function (item) { return item.project === p; })) {
          fields.disabled = false; busy(btn, false, 'Create and check the site'); existing(p); return;
        }
      } catch (error) {
        if (!active()) return;
        fields.disabled = false; busy(btn, false, 'Create and check the site'); errorIn(err, error); return;
      }
      busy(btn, true, 'Creating project…');
      var pr = progress(questions.length ? ['Save project', 'Save buying questions', 'Audit website'] : ['Save project', 'Audit website']);
      var auditStep = questions.length ? 2 : 1, step = 0, created = false;
      pr.el.setAttribute('aria-live', 'polite');
      fields.hidden = true; status.hidden = false; CB.clear(status).appendChild(pr.el);
      pr.set(0, 'doing');
      try {
        await CB.tool('save_results', payload);
        created = true; directoryChanged = true; refreshDirectory();
        if (!active()) return;
        pr.set(0, 'done', 'Project saved');
        if (questions.length) {
          step = 1; pr.set(step, 'doing');
          var saved = await CB.tool('save_results', { project: p, panel: questions.map(function (q, i) { return { prompt_id: 'q' + (i + 1), prompt: q, type: 'consideration' }; }) });
          if (!active()) return;
          pr.set(step, 'done', questions.length + (questions.length === 1 ? ' question saved' : ' questions saved'));
          if ((saved.warnings || []).length) status.appendChild(h('ul', { class: 'notes' }, saved.warnings.map(function (w) { return h('li', { text: w }); })));
        }
        step = auditStep; pr.set(step, 'doing', 'Reading public pages…'); busy(btn, true, 'Auditing site…');
        var audit = await runSiteAudit(p, url, 15);
        directoryChanged = true; refreshDirectory();
        if (!active()) return;
        pr.set(step, audit.status === 'unreadable' ? 'fail' : 'done', audit.status === 'unreadable' ? 'Site unreadable' : 'Site checked');
        status.appendChild(auditReceipt(audit)); canOpen(p);
      } catch (error) {
        if (!active()) return;
        pr.set(step, 'fail'); errorIn(err, error);
        if (created) { canOpen(p); return; }
        // The first save may have reached Apify even if the browser lost its reply.
        var found = false;
        try {
          var latest = await CB.history(undefined, true);
          found = (latest.projects || []).some(function (item) { return item.project === p; });
        } catch (_) { /* The next submission checks the directory again before making any write. */ }
        if (!active()) return;
        fields.hidden = false; fields.disabled = false; status.hidden = true;
        busy(btn, false, 'Create and check the site');
        if (found) { directoryChanged = true; existing(p); }
      }
    }
    form.addEventListener('submit', function (event) { event.preventDefault(); primary.click(); });
    site.focus();
    return d;
  };

  /* ---------- site check ---------- */
  F.checkSite = function (project, site, done) {
    if (sampleOnly()) return;
    var account = CB.sessionId(), completed = false, target = '';
    if (site) {
      try { target = projectWebsite(site).href; } catch (_) { /* Older projects can be missing a usable public address. */ }
    }
    var input = h('input', { type: 'text', inputmode: 'url', spellcheck: 'false', autocomplete: 'url', placeholder: 'yourbrand.com', value: target });
    var pages = h('input', { type: 'number', min: 1, max: 30, step: 1, value: 15, required: true, 'aria-label': 'Maximum pages' });
    var err = h('div', { class: 'form-err', role: 'alert' }), status = h('div', { class: 'project-create-status' });
    var fields = h('fieldset', { class: 'project-form-fields' },
      target ? h('p', { class: 'audit-target' }, h('b', { text: 'Website' }), h('span', { text: target })) : field('Website', input),
      field('Maximum pages', pages, 'Choose 1 to 30 public pages.'),
      h('p', { class: 'audit-intro', text: 'Citebase reads the HTML and saves the audit to this project. Apify platform usage applies.' }));
    var body = h('form', { class: 'form audit-run-form', novalidate: true }, fields, status, err,
      h('button', { type: 'submit', hidden: true, tabindex: '-1', text: 'Start audit' }));
    var dialog = F.dialog('Site audit', body, [{ label: 'Close', ghost: true }, { label: 'Start audit', onclick: async function (close, btn) {
      if (btn.disabled) return;
      if (completed) {
        close(); var address = '#/p/' + encodeURIComponent(project) + '/site';
        if (location.hash !== address) location.hash = address;
        return;
      }
      err.textContent = '';
      var url;
      try { url = projectWebsite(input.value).href; }
      catch (error) { err.textContent = error.message; if (!target) input.focus(); return; }
      var cap = pages.valueAsNumber;
      if (!Number.isInteger(cap) || cap < 1 || cap > 30) { err.textContent = 'Choose a whole number from 1 to 30.'; pages.focus(); return; }
      fields.disabled = true; fields.hidden = true; busy(btn, true, 'Auditing site…');
      var pr = progress(['Reading up to ' + cap + (cap === 1 ? ' page' : ' pages') + ' on ' + CB.host(url)]);
      pr.el.setAttribute('aria-live', 'polite'); pr.set(0, 'doing'); status.appendChild(pr.el);
      try {
        var result = await runSiteAudit(project, url, cap);
        if (account !== CB.sessionId()) return;
        if (dialog.el.isConnected) CB.clear(status).appendChild(auditReceipt(result));
      } catch (error) {
        if (account !== CB.sessionId()) return;
        pr.set(0, 'fail', 'Audit result unavailable'); errorIn(err, error);
      }
      completed = true; busy(btn, false, 'View site audit');
      if (done) done();
    } }]);
    body.addEventListener('submit', function (event) { event.preventDefault(); dialog.foot.lastElementChild.click(); });
  };

  /* ---------- paid AI check: plan, confirm, start, watch, import ---------- */
  function pending() { try { return JSON.parse(sessionStorage.getItem('cb.pending') || '[]'); } catch (e) { return []; } }
  function setPending(list) { sessionStorage.setItem('cb.pending', JSON.stringify(list)); }
  var starting = new Set(), watching = new Map();
  function watchKey(project) { return CB.sessionId() + '/' + project; }
  function rememberJob(job) {
    setPending(pending().filter(function (j) { return j.project !== job.project; }).concat([job]));
  }
  function matchingJob(a, b) { return a.project === b.project && a.at === b.at; }
  function clearJob(job) { setPending(pending().filter(function (j) { return !matchingJob(j, job); })); }
  function reviewStart(project, job, done) {
    var account = CB.sessionId(), key = watchKey(project);
    var unresolvedStart = job.startState && !starting.has(key), unresolvedImport = job.importState && !watching.has(key);
    var explanation = 'This project already has a check in progress. Its results appear here when the runs finish.';
    if (unresolvedStart) explanation = 'A previous start has an unknown outcome. Review the account activity and import its finished results before clearing this notice.';
    if (job.startState === 'partial') explanation = 'Apify accepted the runs listed below and declined the next start for billing. Review their results in Activity before clearing this notice.';
    if (job.importState) explanation = unresolvedImport
      ? 'An earlier import needs review. Compare the saved round with the finished runs in Activity before clearing this notice.'
      : 'Citebase is importing the finished runs into the saved round.';
    var controls = [{label:'Close', ghost:true}];
    if (unresolvedStart || unresolvedImport) controls.push({label:unresolvedImport ? 'I reviewed this import in Activity' : 'I reconciled these starts in Activity', onclick:function (close) {
      close();
      if (account !== CB.sessionId()) return;
      clearJob(job);
      if (done) done();
    }});
    F.dialog('Previous AI check', h('div',{},
      h('p',{text:explanation}),
      job.runs.length ? h('ul',{}, job.runs.map(function(id){return h('li',{},h('a',{class:'ext',href:'https://console.apify.com/view/runs/'+encodeURIComponent(id),target:'_blank',rel:'noopener noreferrer',text:id}));})) : null,
      h('a',{class:'ext',href:'#/activity',text:'Review Activity',onclick:function(){ var dlg=this.closest('dialog'); dlg.close(); dlg.remove(); }})),controls);
  }
  F.pending = pending;
  F.aiCheck = function (project, d, done) {
    if (sampleOnly()) return;
    var account = CB.sessionId(), key = watchKey(project);
    var prior = pending().find(function (j) {return j.project === project;});
    if (prior) {reviewStart(project, prior, done); return;}
    var body = h('div', {}, h('p', { class: 'muted', text: 'Getting the plan…' }));
    var dlg = F.dialog('AI recommendation check', body, [{ label: 'Cancel', ghost: true }], { wide: true });
    CB.tool('quote_cost', { pack: 'ai_check_pilot', project: project }).then(function (q) {
      CB.clear(body);
      var runs = q.ready_runs || [];
      if (!runs.length) { body.appendChild(h('p', { text: 'This project needs buying questions first. Add them from the Questions tab.' })); return; }
      if (runs.some(function (r) { return !Number.isFinite(r.max_cost_per_run_usd) || r.max_cost_per_run_usd <= 0 ||
          (r.times != null && (!Number.isSafeInteger(r.times) || r.times <= 0)); })) {
        body.appendChild(h('p',{role:'alert',text:'The quote is missing a spending cap or run count. Request a new quote before starting.'})); return;
      }
      var cap = runs.reduce(function (n,r) { return n + r.max_cost_per_run_usd * (r.times || 1); },0);
      var usage = CB.usage.guard(cap), submitting = false;
      var snaps = d.snapshots || [], now = new Date();
      var round = snaps.length ? now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') : 'baseline';
      var exists = snaps.some(function (s) { return s.snapshot === round; });
      body.appendChild(h('p', { class: 'lead-s', text: 'This is a paid check billed to your own Apify account. It asks the AI engines your questions and saves the answers as round "' + round + '".' }));
      body.appendChild(h('ul', { class: 'runlist' }, runs.map(function (r) { return h('li', {}, h('b', { text: r.name }), h('span', { text: r.actor })); })));
      body.appendChild(usage.node);
      var costLine = h('div', { class: 'cost', 'aria-live':'polite' });
      body.appendChild(costLine);
      CB.clear(dlg.foot);
      var ask = h('button', { type: 'button', class: 'btn ghost', text: 'What does it cost?' });
      ask.addEventListener('click', function () {
        var estimate = q.runnable_total_usd ?? q.total_usd;
        costLine.textContent = Number.isFinite(estimate) ? 'Citebase estimates ' + CB.usage.usd(estimate) + ' for the runs shown.' : 'The individual run caps are included in the total above.';
      });
      var go = h('button', { type: 'button', class: 'btn', text: 'Yes, start the paid check' });
      usage.bind(go);
      go.addEventListener('click', async function () {
        if (submitting || go.disabled) return;
        if (account !== CB.sessionId()) { dlg.close(); return; }
        var current = pending().find(function (j) { return j.project === project; });
        if (current) { dlg.close(); reviewStart(project,current,done); return; }
        submitting = true;
        busy(go, true, 'Checking usage…');
        try { await usage.verify(); }
        catch (error) {
          submitting = false;
          if (account === CB.sessionId()) {
            costLine.textContent = error.message; go.textContent = 'Yes, start the paid check'; usage.bind(go);
          }
          return;
        }
        if (account !== CB.sessionId() || !dlg.el.open) return;
        current = pending().find(function (j) { return j.project === project; });
        if (current) { dlg.close(); reviewStart(project,current,done); return; }
        usage.bind(null);
        busy(go, true, 'Starting…');
        var job = {project:project, round:round, append:exists, runs:[], startState:'starting', at:new Date().toISOString()};
        var starts = [];
        runs.forEach(function (r) { for (var i = 0; i < (r.times || 1); i++) starts.push(r); });
        try {
          // Persist before the first POST. A lost response requires reconciliation, never an automatic paid retry.
          rememberJob(job);
        } catch (_) {
          costLine.textContent = 'Your browser could not record the confirmation. Enable tab storage before starting.';
          submitting = false; busy(go,false,'Yes, start the paid check'); usage.bind(go); return;
        }
        starting.add(key);
        try {
          for (var item of starts) {
            if (account !== CB.sessionId()) return;
            var child = await CB.apify('POST',actorPath(item.actor)+'/runs?maxTotalChargeUsd='+encodeURIComponent(item.max_cost_per_run_usd),item.input);
            if (account !== CB.sessionId()) return;
            if (!child || !child.id) throw new Error('The start returned no run ID.');
            job.runs.push(child.id); rememberJob(job);
          }
          delete job.startState;
          rememberJob(job); dlg.close(); CB.toast('Started '+job.runs.length+' runs'); if (done) done();
        } catch (e) {
          if (account !== CB.sessionId()) return;
          var billingError = CB.usage.errorDetails(e);
          if (billingError) {
            try {
              if (job.runs.length) { job.startState = 'partial'; rememberJob(job); }
              else clearJob(job);
            } catch (_) { /* The original receipt remains available for manual reconciliation. */ }
            CB.clear(costLine).appendChild(billingError);
            costLine.appendChild(h('p',{text:job.runs.length ? 'Apify accepted ' + job.runs.length + (job.runs.length === 1 ? ' run' : ' runs') + ' before declining the next start. Review Activity for results.' : 'No runs were started.'}));
            if (job.runs.length) costLine.appendChild(h('a',{class:'ext',href:'#/activity',text:'Review accepted runs',onclick:dlg.close}));
            go.textContent = 'Start declined';
            return;
          }
          job.startState = 'uncertain';
          try { rememberJob(job); } catch (_) { /* The original pending receipt still prevents a direct retry. */ }
          costLine.textContent = 'Start interrupted. Review Activity before starting another check. Confirmed run IDs: '+(job.runs.join(', ') || 'none received')+'. '+e.message;
        } finally { starting.delete(key); }
      });
      dlg.foot.appendChild(ask); dlg.foot.appendChild(h('button', { type: 'button', class: 'btn ghost', text: 'Cancel', onclick: dlg.close })); dlg.foot.appendChild(go);
    }, function (e) { errorIn(body, e); });
  };
  function currentJob(account, job) {
    return account === CB.sessionId() && pending().some(function (j) { return matchingJob(j, job); });
  }
  async function checkRuns(job, account) {
    var runs = await Promise.all(job.runs.map(function (id) { return CB.apify('GET', 'actor-runs/' + id); }));
    if (!currentJob(account, job)) return null;
    var finished = runs.filter(function (r) { return ['SUCCEEDED','FAILED','ABORTED','TIMED-OUT'].includes(r.status); });
    var status = {job:job, runs:runs, done:finished.length, total:runs.length};
    if (finished.length !== runs.length) return status;
    var accepted = runs.filter(function (r) { return r.status === 'SUCCEEDED'; });
    if (!accepted.length) {
      clearJob(job);
      status.error = 'No runs succeeded, so there are no results to import.';
      return status;
    }
    // Record the attempt before sending it. A reloaded tab can reconcile these IDs and the saved round.
    job.importState = 'submitted';
    rememberJob(job);
    try {
      status.imported = await CB.tool('import_ai_results', { project:job.project, dataset_ids:accepted.map(function (r) { return r.defaultDatasetId; }),
        save:true, snapshot:job.round, append:!!job.append });
    } catch (e) {
      if (!currentJob(account, job)) return null;
      status.error = 'Review the saved round and Activity before importing again. ' + e.message;
      return status;
    }
    if (!currentJob(account, job)) return null;
    clearJob(job);
    CB.refresh();
    return status;
  }
  // Project views can ask about the same run while its poll or import is still outstanding.
  F.watch = function (project) {
    var key = watchKey(project);
    if (watching.has(key)) return watching.get(key);
    var job = pending().find(function (j) { return j.project === project; });
    if (!job) return Promise.resolve(null);
    if (job.importState) return Promise.resolve({job:job, error:'An earlier import needs review. Compare the saved round with Activity, then open Run AI check to clear the notice.'});
    if (job.startState) {
      if (starting.has(key)) return Promise.resolve({job:job, runs:[], done:0, total:1});
      if (job.startState === 'partial') return Promise.resolve({job:job, error:'Apify declined part of the check for billing. Open Run AI check to review the accepted runs in Activity.'});
      return Promise.resolve({job:job, error:'A previous start needs review. Open Run AI check to reconcile it against Activity.'});
    }
    var poll = checkRuns(job, CB.sessionId()).finally(function () { watching.delete(key); });
    watching.set(key, poll);
    return poll;
  };
  F.importRuns = function (runs, projects, done) {
    if (sampleOnly()) return;
    var sel = h('select', {}, projects.map(function (p) { return h('option', { value: p.project, text: p.brand || p.project }); }));
    var round = h('input', { type: 'text', value: new Date().toISOString().slice(0, 7) });
    var add = h('input', { type: 'checkbox' });
    var err = h('p', { class: 'form-err', role: 'alert' });
    F.dialog('Import results', h('div', { class: 'form' },
      h('p', { class: 'muted', text: runs.length + ' finished run' + (runs.length > 1 ? 's' : '') + ' will be read from your Apify account and saved as one round.' }),
      field('Project', sel), field('Round name', round, 'For example baseline or 2026-11.'), h('label', { class: 'check' }, add, ' Add to this round if it already exists'), err),
      [{ label: 'Cancel', ghost: true }, { label: 'Import', onclick: function (close, btn) {
        busy(btn, true, 'Importing…');
        CB.tool('import_ai_results', { project: sel.value, dataset_ids: runs.map(function (r) { return r.defaultDatasetId; }), save: true, snapshot: round.value.trim(), append: add.checked })
          .then(function (r) { close(); CB.refresh(); CB.toast('Imported ' + ((r.summary && r.summary.rows) || '') + ' answers'); if (done) done(sel.value); },
            function (e) { busy(btn, false, 'Import'); err.textContent = e.message; });
      } }]);
  };

  F.schedule = function (project, done) {
    return CB.hasProjectWork ? CB.workUI.schedule(project, done) : CB.historyUI.schedule(project, done);
  };

  /* ---------- next steps, report, questions ---------- */
  F.nextSteps = function (project, done) {
    var body = h('div', {}, h('p', { class: 'muted', text: 'Working out the best next steps…' }));
    F.dialog('Next steps', body, [{ label: 'Close', ghost: true }], { wide: true });
    CB.tool('next_steps', { project: project, max_steps: 6 }).then(function (r) {
      CB.clear(body);
      if (r.tip) body.appendChild(h('p', { class: 'lead-s', text: r.tip }));
      body.appendChild(h('ol', { class: 'steplist' }, (r.steps || []).map(function (st) {
        var add = h('button', { type: 'button', class: 'btn tiny', text: 'Create action' });
        add.addEventListener('click', function () {
          add.disabled = true;
          var title = st.step.slice(0, 200);
          var save = CB.hasProjectWork ? CB.work(project, 'action_save', { title: title, finding_id: 'next-step/' + st.step.slice(0, 250), evidence: st.why || '', owner: st.who || '', status: 'open' })
            : CB.saveTodo(project, [{step: title, status: 'open'}]);
          save.then(function () { add.textContent = 'Added'; if (done) done(); },
            function (e) { add.disabled = false; CB.toast(e.message, true); });
        });
        return h('li', {}, h('div', {}, h('b', { text: st.step }), h('p', { text: st.why }), h('small', { text: [st.urgency, st.effort, st.who].filter(Boolean).join(' · ') })), add);
      })));
    }, function (e) { errorIn(body, e); });
  };
  F.factChecks = function (project, snapshot) {
    var body = h('div', {});
    F.dialog('Answer fact checks', body, [{ label: 'Close', ghost: true }], { wide: true });
    function load(offset) {
      CB.clear(body).appendChild(h('p', { class: 'muted', text: 'Reading saved answers…' }));
      CB.tool('get_history', { project: project, answer_review: { snapshot: snapshot, offset: offset } }).then(function (r) {
        var review = r.answer_review;
        CB.clear(body);
        body.appendChild(h('p', { class: 'note', text: review.note }));
        if (review.missing_text) body.appendChild(h('p', { class: 'note', text: review.missing_text + ' answers have no saved wording.' }));
        review.answers.forEach(function (answer) {
          var claims = review.claims.filter(function (claim) { return claim.answer_id === answer.answer_id; });
          var details = h('details', {},
            h('summary', { text: CB.engine(answer.engine) + ' · ' + answer.question }),
            h('p', { class: 'saved-answer', text: answer.text }),
            answer.truncated ? h('p', { class: 'note', text: 'Only part of this answer was available.' }) : null);
          if (!claims.length) details.appendChild(h('p', { class: 'note', text: 'No claims reviewed yet.' }));
          claims.forEach(function (claim) {
            var label = { 'true': 'True', 'false': 'False', unverified: 'Unverified' }[claim.verdict];
            details.appendChild(h('p', {}, h('strong', { text: label + ' · ' }), claim.quote));
            if (claim.evidence) details.appendChild(h('p', { text: claim.evidence }));
            if (claim.source_url && /^https:\/\//.test(claim.source_url)) details.appendChild(h('p', {},
              h('a', { href: claim.source_url, target: '_blank', rel: 'noopener noreferrer', text: 'Read the source' })));
          });
          body.appendChild(details);
        });
        if (!review.answers.length) body.appendChild(h('p', { class: 'note', text: 'No answer text is available in this round.' }));
        if (review.next_offset != null) body.appendChild(h('button', { class: 'btn', type: 'button', text: 'Next answers',
          onclick: function () { load(review.next_offset); } }));
      }).catch(function (e) { errorIn(body, e); });
    }
    load(0);
  };

  F.report = function (project, prospect) {
    var body = h('div', {});
    var title = prospect ? 'Prospect audit' : 'Shareable report';
    var closeBtn = { label: 'Close', ghost: true };
    function create(btn) {
      busy(btn, true, 'Creating…');
      CB.clear(body).appendChild(h('p', { class: 'muted', text: 'Building the report page…' }));
      var args = prospect ? { project: project, prospect: true } : { project: project };
      CB.tool('make_report', args).then(function (r) {
        CB.clear(body);
        var shareUrl = CB.safeUrl(r.share_url);
        if (shareUrl) {
          body.appendChild(h('p', { text: 'Anyone with this link can open the report.' }));
          body.appendChild(F.copyBox(shareUrl));
          body.appendChild(h('p', {}, h('a', { class: 'btn', href: shareUrl, target: '_blank',
            rel: 'noopener noreferrer', text: 'Preview report ↗' })));
        } else body.appendChild(h('p', { text: 'The report was saved, but no sharing link could be made.' }));
        if (r.note) body.appendChild(h('p', { class: 'muted', text: r.note }));
        if (btn) btn.remove();
      }, function (e) { busy(btn, false, 'Create link'); errorIn(body, e); });
    }
    if (prospect) {
      body.appendChild(h('p', { text: 'Create a shareable page with the brand name and aggregate AI results. Anyone with the link can open it.' }));
      F.dialog(title, body, [closeBtn, { label: 'Create link', onclick: function (close, btn) { create(btn); } }]);
    } else {
      F.dialog(title, body, [closeBtn]);
      create();
    }
  };
  F.addQuestions = function (project, done, suggestions) {
    if (sampleOnly()) return;
    var qs = h('textarea', { rows: '10', placeholder: 'One buying question per line' });
    var ideas = (suggestions || []).length ? h('div', { class: 'ideas' }, h('p', { class: 'muted', text: 'Ideas from what people search (Search Console). Click to add:' }),
      h('div', { class: 'chipline' }, suggestions.map(function (q) {
        var c = h('button', { type: 'button', class: 'chip-btn', text: q });
        c.addEventListener('click', function () { qs.value = (qs.value.trim() ? qs.value.trim() + '\n' : '') + q; c.disabled = true; });
        return c; }))) : null;
    var err = h('p', { class: 'form-err', role: 'alert' }), review = h('div', {});
    var ready = false;
    F.dialog('Add test questions', h('div', { class: 'form' },
      h('p', { class: 'muted', text: 'Write them as a buyer would ask an AI, without your brand name. 20 or more gives a reliable number. The list is frozen once saved, so every round stays comparable.' }),
      ideas, qs, review, err), [{ label: 'Cancel', ghost: true }, { label: 'Check the list', onclick: function (close, btn) {
        var list = lines(qs.value).slice(0, 60);
        if (!list.length) { err.textContent = 'Add at least one question.'; return; }
        var panel = list.map(function (q, i) { return { prompt_id: 'q' + (i + 1), prompt: q, type: 'consideration' }; });
        err.textContent = '';
        if (ready) {
          busy(btn, true, 'Saving…');
          CB.tool('save_results', { project: project, panel: panel }).then(function () { close(); CB.refresh(); CB.toast('Questions saved'); if (done) done(); },
            function (e) { busy(btn, false, 'Save'); err.textContent = e.message; });
          return;
        }
        busy(btn, true, 'Checking…');
        CB.tool('save_results', { project: project, panel: panel, check_only: true }).then(function (r) {
          CB.clear(review);
          var notes = (r.warnings || []).slice(0, 6);
          review.appendChild(notes.length ? h('ul', { class: 'notes' }, notes.map(function (w) { return h('li', { text: w }); })) : h('p', { class: 'ok', text: 'Looks good.' }));
          ready = true; busy(btn, false, notes.length ? 'Save anyway' : 'Save');
        }, function (e) { busy(btn, false, 'Check the list'); err.textContent = e.message; });
      } }], { wide: true });
  };
})();
