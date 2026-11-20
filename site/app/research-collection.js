(function () {
  'use strict';
  const CB = window.CB;
  const h = (...args) => CB.h(...args);
  const serpActor = 'khadinakbar/scrape-google-serp';
  const aiActor = 'khadinakbar/ai-search-brand-monitor';
  const rankedActor = 'khadinakbar/ahrefs-alternative';
  const engines = {chatgpt:'ChatGPT', claude:'Claude', gemini:'Gemini'};
  const domain = /^(?:[a-z0-9-]+\.)+[a-z]{2,63}$/;
  const providers = new Map([
    ['khadinakbar/dataforseo-keyword-research', {input:'seedKeywords', output:'keywords', field:'term'}],
    [serpActor, {input:'queries', output:'pages', field:'term'}],
    ['khadinakbar/similarweb-traffic-rank-scraper', {input:'domains', output:'competitors', field:'domain'}],
    [aiActor, {input:'customQueries', output:'ai', field:'term'}],
    [rankedActor, {input:'target', output:'pages', field:'target'}]
  ]);
  const runId = /^[A-Za-z0-9]{17}$/;
  const terminalFailure = new Set(['ABORTED', 'FAILED', 'TIMED-OUT']);
  const exportFields = ['keywords', 'competitors', 'pages', 'ai', 'citations'];

  const button = (text, onclick, className = 'btn') => h('button', {type:'button', class:className, text, onclick});
  const note = text => h('p', {class:'muted', text});
  const field = (label, input) => h('label', {class:'field'}, h('span', {text:label}), input);

  function importDialog(save, mode, active) {
    const status = h('p', {'aria-live':'polite'});
    const id = h('input', {type:'text', autocomplete:'off', placeholder:'Paste an Apify run ID'});
    const source = h('input', {type:'text', placeholder:'For example, Search Console'});
    const observed = h('input', {type:'date'});
    const payload = h('textarea', {rows:6, placeholder:'{"keywords":[…], "competitors":[…]}'});
    const format = h('details', {}, h('summary', {text:'View export format'}),
      h('pre', {text:JSON.stringify({
        keywords:[{term:'office chairs',search_volume:1200}],
        competitors:[{name:'Example Retailer',domain:'example.com',estimated_organic_traffic:950}],
        pages:[{term:'office chairs',domain:'example.com',url:'https://example.com/chairs',position:4,estimated_traffic:32}],
        ai:[{term:'office chairs',engine:'ChatGPT',brand:'Example Retailer',mentions:1,answers:3,position:2}],
        citations:[{term:'office chairs',engine:'ChatGPT',url:'https://example.com/chairs'}]
      }, null, 2)}), note('Use your own observed values. Include only the measurement sections present in your export.'));
    const file = h('input', {type:'file', accept:'.json,application/json'});
    let reading = false;
    file.addEventListener('change', async () => {
      if (!file.files[0]) return;
      reading = true;
      try {
        if (file.files[0].size > 1000000) throw new Error('Choose a JSON file under 1 MB.');
        payload.value = await file.files[0].text();
        status.textContent = '';
      } catch (error) { status.textContent = error.message; }
      finally { reading = false; }
    });
    const body = mode === 'run'
      ? h('div', {}, note('Open a completed run in Apify Activity and copy its run ID. Citebase verifies supported Actors and reads the saved results.'), field('Apify run ID', id), status)
      : h('div', {}, note('Choose a JSON export or paste its contents. Use a JSON object with measurement rows under keywords, competitors, pages, ai, or citations.'),
        field('Evidence source', source), field('Measurement date', observed), field('Choose a JSON file', file),
        field('Evidence rows', payload), format, status);
    const dialog = CB.flows.dialog(mode === 'run' ? 'Import an Apify run' : 'Import a measurement export',
      body, [{label:'Cancel', ghost:true}]);
    const submit = button('Save measurements', async () => {
      if (submit.disabled || reading || !active()) return;
      submit.disabled = true;
      status.textContent = 'Checking and saving your measurements…';
      try {
        let args;
        if (mode === 'run') {
          if (!runId.test(id.value.trim())) throw new Error('Enter the run ID shown in Apify Activity.');
          args = {run_id:id.value.trim()};
        } else {
          if (!source.value.trim() || !observed.value) throw new Error('Enter the evidence source and measurement date.');
          let rows;
          try { rows = JSON.parse(payload.value); } catch (_) { throw new Error('The export must contain valid JSON.'); }
          if (!rows || Array.isArray(rows) || typeof rows !== 'object' ||
              !Object.keys(rows).every(key => exportFields.includes(key) && Array.isArray(rows[key])) ||
              !Object.values(rows).some(list => list.length)) throw new Error('Include measurement rows under keywords, competitors, pages, ai, or citations.');
          args = {...rows, source:source.value.trim(), observed_at:observed.value};
        }
        await save(args);
        dialog.close();
      } catch (error) {
        status.textContent = error.message;
      } finally { submit.disabled = false; }
    });
    dialog.foot.appendChild(submit);
  }

  function panel(project, plan, onImported, options = {}) {
    const session = CB.sessionId();
    const sameSession = () => session === CB.sessionId();
    const root = h('section', {'aria-label':'Collect competitor measurements'});
    const active = () => sameSession() && root.isConnected;
    const reported = h('p', {'aria-live':'polite'});
    let account = null;
    let accessStatus = 'Checking your Apify connection…';
    let importQueue = Promise.resolve();
    const save = args => {
      const verify = () => {
        if (!sameSession()) throw new Error('Sign in again to save measurements.');
      };
      const read = async () => {
        verify();
        const report = await CB.work(project,'research_get',{},true);
        verify();
        return report;
      };
      const saved = report => args.run_id && exportFields.some(field => report[field]?.some(row =>
        row.run_id === args.run_id && row.provenance === 'verified_actor_run'));
      const write = async () => {
        const current = await read();
        if (saved(current)) return current;
        const submit = report => CB.work(project,'research_import',{...args, expected_revision:report.revision});
        try { return await submit(current); }
        catch (error) {
          if (!args.run_id) throw error;
          // Reconcile a lost reply or a concurrent save using the same known run.
          const latest = await read();
          if (saved(latest)) return latest;
          if (latest.revision !== current.revision) return submit(latest);
          throw error;
        }
      };
      const next = importQueue.then(() => account && navigator.locks
        ? navigator.locks.request('cb.research.import/' + [account, project].map(encodeURIComponent).join('/'), write)
        : write());
      importQueue = next.catch(() => {});
      return next;
    };
    function notify(report) {
      if (!active()) return;
      reported.textContent = options.discovery
        ? 'Ranking evidence saved. Review the suggested competitors.'
        : 'Measurements saved. Open the report to see the evidence and remaining gaps.';
      if (onImported) onImported(report);
    }
    function jobCard(job) {
      const state = h('div', {'aria-live':'polite'});
      const card = h('div', {class:'card'}, h('h4', {text:job.purpose || 'Competitor measurement'}),
        job.source ? note('Source: ' + job.source) : null, state);
      const provider = providers.get(job.actor);
      const input = job.input || {};
      const ai = job.actor === aiActor;
      const ranked = job.actor === rankedActor;
      const engine = Array.isArray(input.platforms) && input.platforms.length === 1 &&
        Object.hasOwn(engines, input.platforms[0]) ? input.platforms[0] : '';
      const scope = provider && (ranked ? [input.target] : input[provider.input]);
      const withinScope = Array.isArray(scope) && scope.length > 0 && scope.length <= 10 &&
        scope.every(value => typeof value === 'string' && value.trim());
      const validAi = engine && input.querySelectionMode === 'custom_only' && input.maxQueriesPerPlatform === scope?.length &&
        typeof input.brandName === 'string' && input.brandName.trim() &&
        Array.isArray(input.competitors) && input.competitors.every(name => typeof name === 'string');
      const validRanked = input.mode === 'organic_keywords' && typeof input.target === 'string' && domain.test(input.target) &&
        input.maxResults === 10 && typeof input.locationName === 'string' && typeof input.languageCode === 'string';
      const allowed = withinScope && (!ai || validAi) && (!ranked || validRanked) &&
        Number.isFinite(job.maxTotalChargeUsd) && job.maxTotalChargeUsd > 0;
      const market = input.locationName || input.countryName || input.countryCode || input.locationCode;
      const language = input.languageCode;
      const slot = ai ? engine : ranked ? input.target : '';
      let timer;
      let watching = false;
      let storage;
      let missing = [];
      function get() { return storage.read(); }
      function put(receipt) { storage.write(receipt); }
      function locked(fn) { return navigator.locks.request(storage.key, fn); }
      function display(...nodes) { CB.clear(state); nodes.forEach(node => state.appendChild(node)); }
      async function check() {
        if (watching || !active()) return;
        watching = true;
        try {
          let report;
          await locked(async () => {
            if (!active()) return;
            const receipt = get();
            if (!receipt || !runId.test(receipt.id || '') || receipt.saved || terminalFailure.has(receipt.status)) return;
            const run = await CB.apify('GET', 'actor-runs/' + receipt.id);
            if (!active()) return;
            if (run?.id !== receipt.id) throw new Error('Apify did not return the recorded run.');
            receipt.status = run.status;
            put(receipt);
            if (run.status === 'SUCCEEDED') {
              display(note('Run completed. Verifying and saving evidence…'));
              report = await save({run_id:receipt.id});
              receipt.saved = true;
              const measured = new Set(report[provider.output]?.filter(row => row.run_id === receipt.id)
                .map(row => row[provider.field].toLowerCase()));
              if (receipt.signature === storage.signature)
                missing = scope.filter(term => !measured.has(term.toLowerCase()));
              put(receipt);
            }
          });
          if (!active()) return;
          render();
          if (report) notify(report);
        } catch (error) {
          if (active()) display(note('Could not check or save the run. ' + error.message),
            button('Check run again', check, 'btn ghost'));
        } finally { watching = false; }
      }
      function review() {
        if (!active()) return;
        const cap = job.maxTotalChargeUsd;
        const usage = CB.usage.guard(cap);
        const status = h('div', {'aria-live':'polite'});
        const scopeLabel = ai ? 'Questions' : ranked ? 'Domain' : provider.field === 'domain' ? 'Domains' : 'Search terms';
        const body = h('div', {}, note(job.purpose || 'Competitor measurement'),
          note(scopeLabel + ': ' + scope.join(', ')),
          ai ? note('AI engine: ' + engines[engine]) : null,
          ai ? note('Brand: ' + input.brandName) : null,
          ai && input.competitors.length ? note('Competitors: ' + input.competitors.join(', ')) : null,
          ai ? note('This samples one answer per question. The wording and rankings can vary across answers.') : null,
          ranked ? note('Checks up to ' + input.maxResults + ' organic ranking keywords and their ranking pages.') : null,
          market ? note('Market: ' + (input.locationName || input.countryName || input.countryCode || 'DataForSEO location ' + market)) : null,
          language ? note('Language: ' + language) : null,
          job.actor === serpActor ? note('The check reads the first Google results page for each search term.') : null,
          options.discovery ? note('Ranking sites are candidates. You choose which ones to track.') : null,
          note(job.platform_usage_separate===false ? 'Apify will bill your account up to this data charge cap. This Actor includes platform usage in its price.' :
            'Apify will bill your account. The data charge cap applies to this run. Apify bills compute and other platform usage separately.'),
          usage.node, status);
        const dialog = CB.flows.dialog('Review ' + (job.purpose || 'measurement'), body, [{label:'Cancel', ghost:true}], {wide:true});
        let submitting = false;
        const approve = button('Approve and start paid check', async () => {
          if (submitting || approve.disabled || !active() || !dialog.el.open) return;
          submitting = true;
          try {
            await locked(async () => {
              if (!active() || !dialog.el.open) return;
              if (get()) { dialog.close(); render(); return; }
              await usage.verify();
              if (!active() || !dialog.el.open) return;
              // Reserve the start before the POST so a lost response cannot trigger a second paid run.
              put({status:'starting'});
              try {
                const run = await CB.apify('POST', 'acts/' + job.actor.replace('/','~') + '/runs?maxTotalChargeUsd=' +
                  encodeURIComponent(cap), job.input);
                if (!sameSession()) return;
                if (!runId.test(run?.id || '')) throw new Error('Apify did not return a run ID.');
                put({id:run.id, status:run.status || 'READY'});
                dialog.close();
              } catch (error) {
                if (!active()) return;
                const billing = CB.usage.errorDetails(error);
                if (billing) {
                  storage.clearDeclined();
                  CB.clear(status).appendChild(billing);
                } else {
                  put({status:'uncertain'});
                  dialog.close();
                }
              }
            });
          } catch (error) { if (active()) status.textContent = error.message; }
          finally {
            submitting = false;
            if (active()) render();
          }
        });
        usage.bind(approve);
        dialog.foot.appendChild(approve);
      }
      function render() {
        clearTimeout(timer);
        if (!allowed) { display(note('This measurement can be imported from an existing source.')); return; }
        if (!account) { display(note(accessStatus)); return; }
        if (!navigator.locks) { display(note('Paid checks require a browser with cross-tab locks. You can import an existing result below.')); return; }
        try {
          if (!storage) { display(note('Checking receipt storage…')); return; }
          const receipt = get();
          if (receipt?.status === 'expired') {
            display(note('The saved receipt expired. Review Apify Activity and import the run ID below.'));
          } else if (!receipt) {
            display(note('Apify data charge cap ' + CB.usage.usd(job.maxTotalChargeUsd) +
              (job.platform_usage_separate===false ? ' · platform usage included.' : ' plus platform usage.')),
              button('Review paid check', review));
          } else if (!receipt.id) {
            display(note('Start could not be confirmed. Check Apify Activity and import the run ID below.'),
              h('a', {class:'ext', href:'https://console.apify.com/actors/runs', target:'_blank', rel:'noopener noreferrer', text:'Open Apify Activity'}));
          } else if (receipt.saved) {
            display(note('Measurements saved from run ' + receipt.id + '. See the report for evidence and gaps.'));
            if (missing.length) state.appendChild(note('No measurement returned for ' + missing.join(', ') + '.'));
          } else if (terminalFailure.has(receipt.status)) {
            display(note('Apify run ' + receipt.id + ' ended with status ' + receipt.status + '. This check added no evidence.'));
          } else {
            display(note('Checking Apify run ' + receipt.id + '…'), button('Check now', check, 'btn ghost'));
            timer = setTimeout(check, watching ? 5000 : 0);
          }
        } catch (_) { display(note('Browser storage is unavailable. Use an existing result below.')); }
      }
      render();
      return {card, render, async openStorage() {
        if (!allowed || !account || !navigator.locks) { render(); return; }
        try {
          storage = await window.CitebaseSession.researchReceipt(account, project, job.actor, slot, input,
            () => sameSession() && !CB.demo);
          if (sameSession()) render();
        } catch (_) {
          if (sameSession()) display(note('Browser storage is unavailable. Use an existing result below.'));
        }
      }};
    }

    const jobs = (plan?.jobs || []).filter(job => job && typeof job === 'object' &&
      (!options.discovery || job.actor === serpActor)).map(jobCard);
    root.appendChild(h('div', {}, jobs.map(job => job.card)));
    if (options.discovery) {
      root.appendChild(note(jobs.length
        ? 'Check which sites appear for your suggested searches to find potential competitors.'
        : 'No new search check is available. You can import a completed run or enter competitors directly.'));
    } else {
      root.appendChild(note('You can also import keyword volume, rankings, or traffic measurements from an existing source.'));
    }
    root.appendChild(h('div', {class:'actions'},
      button('Import an Apify run', () => importDialog(async args => notify(await save(args)), 'run', active), 'btn ghost'),
      button('Import a measurement export', () => importDialog(async args => notify(await save(args)), 'export', active), 'btn ghost')));
    root.appendChild(reported);
    if (CB.demo) {
      accessStatus = 'Sign in with Apify to start a paid measurement.';
      jobs.forEach(job => job.render());
    } else {
      CB.apify('GET','users/me').then(me => {
        if (!sameSession()) return;
        if (typeof me?.id === 'string' && me.id) account = me.id;
        accessStatus = 'Connect Apify to start a paid measurement or import an existing export.';
        jobs.forEach(job => job.openStorage());
      }).catch(() => {
        if (!sameSession()) return;
        accessStatus = 'Connect Apify to start a paid measurement or import an existing export.';
        jobs.forEach(job => job.render());
      });
    }
    return root;
  }

  CB.researchCollection = {panel};
})();
