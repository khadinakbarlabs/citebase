/* Citebase dashboard actions: dialogs, new project, site check, paid AI check (start, watch, import), schedules,
   next steps, report, questions. Everything goes through Citebase's own tools or Apify's API with the visitor's
   own token. Price rule: paid work is named as paid and capped per run; an amount appears only when the visitor
   presses "What does it cost?". */
(function () {
  'use strict';
  var CB = window.CB, h = CB.h;
  var F = CB.flows = {};
  var CITEBASE = 'khadinakbar/citebase';
  F.setupAddress = 'https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run';

  /* ---------- dialog and small helpers ---------- */
  F.dialog = function (title, body, buttons, opts) {
    opts = opts || {};
    var dlg = h('dialog', { class: 'dlg' + (opts.wide ? ' wide' : ''), 'aria-label': title });
    var foot = h('div', { class: 'dlg-foot' });
    function close() { if (dlg.open) dlg.close(); dlg.remove(); }
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
  F.copyBox = function (text) {
    var b = h('button', { type: 'button', class: 'btn tiny', text: 'Copy' });
    b.addEventListener('click', function () { F.copy(text, b); });
    return h('div', { class: 'copybox' }, h('code', { text: text }), b);
  };
  function errorIn(body, e) { CB.clear(body).appendChild(h('p', { class: 'form-err', text: e.message })); }

  /* ---------- new project ---------- */
  F.newProject = function (done) {
    var site = h('input', { type: 'url', placeholder: 'https://yourbrand.com', autocomplete: 'url' });
    var name = h('input', { type: 'text', placeholder: 'Your brand' });
    var slug = h('input', { type: 'text', placeholder: 'yourbrand-com' });
    var rivals = h('input', { type: 'text', placeholder: 'Rival One, Rival Two' });
    var country = h('select', {}, ['us', 'gb', 'ca', 'au', 'de', 'fr', 'es', 'it', 'nl', 'in', 'br', 'mx', 'jp', 'sg', 'ae', 'za', 'ie', 'nz', 'se', 'pl']
      .map(function (c) { return h('option', { value: c, text: c.toUpperCase() }); }));
    var qs = h('textarea', { rows: '6', placeholder: 'best payroll software for a 10 person company\ncheapest payroll service for startups' });
    var touched = false;
    slug.addEventListener('input', function () { touched = true; });
    site.addEventListener('input', function () { if (!touched) slug.value = slugify((site.value.split('/')[2] || site.value)); });
    var err = h('p', { class: 'form-err', role: 'alert' });
    var form = h('div', { class: 'form' },
      field('Website', site),
      h('div', { class: 'two' }, field('Brand name', name), field('Project name', slug, '3 to 40 letters, numbers or dashes.')),
      h('div', { class: 'two' }, field('Competitors', rivals, 'Optional, separated by commas.'), field('Country', country)),
      field('Buying questions', qs, 'Optional now. One per line, as a buyer would ask an AI, without your brand name. 20 or more gives a reliable number.'),
      err);
    var d = F.dialog('New project', form, [{ label: 'Cancel', ghost: true }, { label: 'Create and check the site', onclick: function (close, btn) {
      if (btn.dataset.open) { close(); done(btn.dataset.open); return; }
      err.textContent = '';
      var url = site.value.trim(), p = slugify(slug.value);
      if (!/^https?:\/\/[^ /]+\.[^ ]+/.test(url)) { err.textContent = 'Enter the full website address, starting with https://'; return; }
      if (!name.value.trim()) { err.textContent = 'Enter the brand name.'; return; }
      if (p.length < 3) { err.textContent = 'The project name needs at least 3 letters or numbers.'; return; }
      var brand = { name: name.value.trim(), domain: url.split('/')[2].replace(/^www\./, ''), site: url,
        competitors: rivals.value.split(',').map(function (x) { return x.trim(); }).filter(Boolean).slice(0, 20) };
      var questions = lines(qs.value).slice(0, 60);
      busy(btn, true, 'Working…');
      var pr = progress(['Save the project', questions.length ? 'Save ' + questions.length + ' questions' : 'Questions: add them later', 'Check the site (about a minute)']);
      CB.clear(form).appendChild(pr.el); form.appendChild(err);
      pr.set(0, 'doing');
      CB.tool('save_results', { project: p, brand: brand, settings: { country: country.value, language: 'en' } }).then(function () {
        pr.set(0, 'done');
        if (!questions.length) { pr.set(1, 'skip'); return null; }
        pr.set(1, 'doing');
        return CB.tool('save_results', { project: p, panel: questions.map(function (q, i) { return { prompt_id: 'q' + (i + 1), prompt: q, type: 'consideration' }; }) })
          .then(function (r) { pr.set(1, 'done', 'Saved ' + questions.length + ' questions' + ((r.warnings || []).length ? ' (see notes in the project)' : '')); });
      }).then(function () {
        pr.set(2, 'doing');
        return CB.tool('audit_site', { url: url, project: p, max_pages: 15 });
      }).then(function (a) {
        pr.set(2, 'done', a.status === 'unreadable' ? 'The site could not be read: ' + (a.headline || 'blocked') : 'Site checked: ' + (a.health_score != null ? a.health_score + ' of 100' : 'done'));
        CB.refresh(); btn.dataset.open = p; busy(btn, false, 'Open the project');
      }).catch(function (e) { busy(btn, false, 'Try again'); err.textContent = e.message; });
    } }], { wide: true });
    return d;
  };

  /* ---------- site check ---------- */
  F.checkSite = function (project, site, done) {
    if (!site) { CB.toast('This project has no website saved.', true); return; }
    var pr = progress(['Check ' + CB.host(site) + ' (about a minute)']);
    F.dialog('Check the site', h('div', {}, h('p', { class: 'muted', text: 'Citebase adds no fee for this. Apify bills its own small running cost to your account.' }), pr.el), [{ label: 'Close', ghost: true }]);
    pr.set(0, 'doing');
    CB.tool('audit_site', { url: site, project: project, max_pages: 15 }).then(function (a) {
      pr.set(0, 'done', a.status === 'unreadable' ? 'Could not read the site: ' + (a.headline || '') : 'Done: ' + a.health_score + ' of 100');
      CB.refresh(); if (done) done();
    }, function (e) { pr.set(0, 'fail', e.message); });
  };

  /* ---------- paid AI check: plan, confirm, start, watch, import ---------- */
  function pending() { try { return JSON.parse(sessionStorage.getItem('cb.pending') || '[]'); } catch (e) { return []; } }
  function setPending(list) { try { sessionStorage.setItem('cb.pending', JSON.stringify(list)); } catch (e) {} }
  F.pending = pending;
  F.aiCheck = function (project, d, done) {
    var body = h('div', {}, h('p', { class: 'muted', text: 'Getting the plan…' }));
    var dlg = F.dialog('AI recommendation check', body, [{ label: 'Cancel', ghost: true }], { wide: true });
    CB.tool('quote_cost', { pack: 'ai_check_pilot', project: project }).then(function (q) {
      CB.clear(body);
      var runs = q.ready_runs || [];
      if (!runs.length) { body.appendChild(h('p', { text: 'This project needs buying questions first. Add them from the Questions tab.' })); return; }
      var snaps = d.snapshots || [], now = new Date();
      var round = snaps.length ? now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') : 'baseline';
      var exists = snaps.some(function (s) { return s.snapshot === round; });
      body.appendChild(h('p', { class: 'lead-s', text: 'This is a paid check billed to your own Apify account. It asks the AI engines your questions and saves the answers as round "' + round + '".' }));
      body.appendChild(h('ul', { class: 'runlist' }, runs.map(function (r) { return h('li', {}, h('b', { text: r.name }), h('span', { text: r.actor })); })));
      body.appendChild(h('p', { class: 'muted', text: 'Each run has its own spending cap, so none can go over. It takes a few minutes; you can keep using the dashboard.' }));
      var costLine = h('p', { class: 'cost' });
      body.appendChild(costLine);
      CB.clear(dlg.foot);
      var ask = h('button', { type: 'button', class: 'btn ghost', text: 'What does it cost?' });
      ask.addEventListener('click', function () {
        var cap = runs.reduce(function (n, r) { return n + r.max_cost_per_run_usd * (r.times || 1); }, 0);
        costLine.textContent = 'About $' + Number(q.total_usd).toFixed(2) + ' for this check; at most $' + cap.toFixed(2) + ' with the caps.';
      });
      var go = h('button', { type: 'button', class: 'btn', text: 'Yes, start the paid check' });
      go.addEventListener('click', function () {
        busy(go, true, 'Starting…');
        var starts = [];
        runs.forEach(function (r) { for (var i = 0; i < (r.times || 1); i++) starts.push(r); });
        Promise.all(starts.map(function (r) {
          return CB.apify('POST', actorPath(r.actor) + '/runs?maxTotalChargeUsd=' + encodeURIComponent(r.max_cost_per_run_usd), r.input);
        })).then(function (started) {
          var list = pending().filter(function (x) { return x.project !== project; });
          list.push({ project: project, round: round, append: exists, runs: started.map(function (s) { return s.id; }), at: new Date().toISOString() });
          setPending(list); dlg.close(); CB.toast('Started ' + started.length + ' runs'); if (done) done();
        }, function (e) { busy(go, false, 'Try again'); costLine.textContent = 'Could not start: ' + e.message; });
      });
      dlg.foot.appendChild(ask); dlg.foot.appendChild(h('button', { type: 'button', class: 'btn ghost', text: 'Cancel', onclick: dlg.close })); dlg.foot.appendChild(go);
    }, function (e) { errorIn(body, e); });
  };
  // Checks a project's started runs and imports them into the round once all have finished.
  F.watch = function (project) {
    var job = pending().filter(function (x) { return x.project === project; })[0];
    if (!job) return Promise.resolve(null);
    return Promise.all(job.runs.map(function (id) { return CB.apify('GET', 'actor-runs/' + id); })).then(function (runs) {
      var finished = runs.filter(function (r) { return /SUCCEEDED|FAILED|ABORTED|TIMED-OUT/.test(r.status); });
      var status = { job: job, runs: runs, done: finished.length, total: runs.length };
      if (finished.length < runs.length) return status;
      setPending(pending().filter(function (x) { return x.project !== project; }));
      var ok = runs.filter(function (r) { return r.status === 'SUCCEEDED'; });
      if (!ok.length) { status.error = 'None of the runs finished, so nothing was imported.'; return status; }
      return CB.tool('import_ai_results', { project: project, dataset_ids: ok.map(function (r) { return r.defaultDatasetId; }), save: true, snapshot: job.round, append: !!job.append })
        .then(function (res) { status.imported = res; CB.refresh(); return status; },
          function (e) { status.error = 'The runs finished, but the import failed: ' + e.message + ' Import them from the Activity page.'; return status; });
    });
  };
  F.importRuns = function (runs, projects, done) {
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

  /* ---------- schedules: created by the visitor, in their own account ---------- */
  F.schedule = function (project, done) {
    var freq = h('select', {}, h('option', { value: 'monthly', text: 'Monthly' }), h('option', { value: 'weekly', text: 'Weekly' }), h('option', { value: 'daily', text: 'Daily' }));
    var withAi = h('input', { type: 'checkbox' });
    var plan = h('p', { class: 'muted', text: 'Getting the plan…' });
    var err = h('p', { class: 'form-err', role: 'alert' });
    var current = null, caps = null;
    function load() {
      plan.textContent = 'Getting the plan…'; current = null;
      var capsP = caps ? Promise.resolve(caps) : CB.tool('quote_cost', { pack: 'ai_check_pilot', project: project }).then(function (q) { caps = q.ready_runs || []; return caps; }, function () { caps = []; return caps; });
      Promise.all([CB.tool('schedule_checks', { project: project, frequency: freq.value }), capsP]).then(function (res) {
        current = res[0]; plan.textContent = 'Runs ' + current.when + ' (your time zone). The site check is always included.';
      }, function (e) { plan.textContent = e.message; });
    }
    freq.addEventListener('change', load); load();
    F.dialog('Re-check on a schedule', h('div', { class: 'form' }, field('How often', freq), plan,
      h('label', { class: 'check' }, withAi, ' Also run the AI recommendation check each time (paid on your Apify account, capped per run)'),
      h('p', { class: 'muted', text: 'The schedule lives in your Apify account. Turn it off or delete it any time from the Schedules page.' }), err),
      [{ label: 'Cancel', ghost: true }, { label: 'Create schedule', onclick: function (close, btn) {
        if (!current) return;
        busy(btn, true, 'Creating…');
        var aiRuns = withAi.checked ? ((current.ai_checks && current.ai_checks.runs) || []) : [];
        var actors = [CITEBASE].concat(aiRuns.map(function (r) { return r.actor; })).filter(function (a, i, all) { return all.indexOf(a) === i; });
        Promise.all(actors.map(function (a) { return CB.apify('GET', actorPath(a)).then(function (x) { return [a, x.id]; }); })).then(function (pairs) {
          var ids = {};
          pairs.forEach(function (p) { ids[p[0]] = p[1]; });
          var actions = [{ type: 'RUN_ACTOR', actorId: ids[CITEBASE], runInput: { body: JSON.stringify(current.free_site_check.input), contentType: 'application/json; charset=utf-8' } }];
          aiRuns.forEach(function (r) {
            var cap = (caps.filter(function (c) { return c.name === r.name; })[0] || {}).max_cost_per_run_usd;
            if (!cap) throw new Error('No spending cap was found for "' + r.name + '", so nothing was created. Try again without the AI check.');
            for (var t = 0; t < (r.times || 1); t++) actions.push({ type: 'RUN_ACTOR', actorId: ids[r.actor], runOptions: { maxTotalChargeUsd: cap },
              runInput: { body: JSON.stringify(r.input), contentType: 'application/json; charset=utf-8' } });
          });
          return CB.apify('POST', 'schedules', { name: ('citebase-' + project).slice(0, 63), title: 'Citebase: ' + project, cronExpression: current.cron,
            isEnabled: true, isExclusive: true, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
            description: 'Created from the Citebase dashboard.', actions: actions });
        }).then(function () { close(); CB.toast('Schedule created'); if (done) done(); },
          function (e) { busy(btn, false, 'Create schedule'); err.textContent = e.message; });
      } }], { wide: true });
  };
  F.toggleSchedule = function (s, on) { return CB.apify('PUT', 'schedules/' + s.id, { isEnabled: on }); };
  F.deleteSchedule = function (s, done) {
    F.dialog('Delete this schedule?', h('p', { text: '"' + (s.title || s.name) + '" will stop for good. Results it already saved stay in your projects.' }),
      [{ label: 'Keep it', ghost: true }, { label: 'Delete', danger: true, onclick: function (close, btn) {
        busy(btn, true, 'Deleting…');
        CB.apify('DELETE', 'schedules/' + s.id).then(function () { close(); CB.toast('Schedule deleted'); if (done) done(); },
          function (e) { busy(btn, false, 'Delete'); CB.toast(e.message, true); });
      } }]);
  };

  /* ---------- next steps, report, questions ---------- */
  F.nextSteps = function (project, done) {
    var body = h('div', {}, h('p', { class: 'muted', text: 'Working out the best next steps…' }));
    F.dialog('Next steps', body, [{ label: 'Close', ghost: true }], { wide: true });
    CB.tool('next_steps', { project: project, max_steps: 6 }).then(function (r) {
      CB.clear(body);
      if (r.tip) body.appendChild(h('p', { class: 'lead-s', text: r.tip }));
      body.appendChild(h('ol', { class: 'steplist' }, (r.steps || []).map(function (st) {
        var add = h('button', { type: 'button', class: 'btn tiny', text: 'Add to to-do' });
        add.addEventListener('click', function () {
          add.disabled = true;
          CB.saveTodo(project, [{ step: st.step.slice(0, 200), status: 'open' }]).then(function () { add.textContent = 'Added'; if (done) done(); },
            function (e) { add.disabled = false; CB.toast(e.message, true); });
        });
        return h('li', {}, h('div', {}, h('b', { text: st.step }), h('p', { text: st.why }), h('small', { text: [st.urgency, st.effort, st.who].filter(Boolean).join(' · ') })), add);
      })));
    }, function (e) { errorIn(body, e); });
  };
  F.report = function (project) {
    var body = h('div', {}, h('p', { class: 'muted', text: 'Building the report page…' }));
    F.dialog('Shareable report', body, [{ label: 'Close', ghost: true }]);
    CB.tool('make_report', { project: project }).then(function (r) {
      CB.clear(body);
      if (r.share_url) {
        body.appendChild(h('p', { text: 'Anyone with this link can open the one-page report.' }));
        body.appendChild(F.copyBox(r.share_url));
        body.appendChild(h('p', {}, h('a', { class: 'btn', href: r.share_url, target: '_blank', rel: 'noopener noreferrer', text: 'Open the report ↗' })));
      } else body.appendChild(h('p', { text: 'The report was saved, but no sharing link could be made.' }));
      if (r.note) body.appendChild(h('p', { class: 'muted', text: r.note }));
    }, function (e) { errorIn(body, e); });
  };
  F.addQuestions = function (project, done, suggestions) {
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
