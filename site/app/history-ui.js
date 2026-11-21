/* Signed-in project workflows for the published Actor that stores actions in get_history. */
(function () {
  'use strict';
  const CB = window.CB, h = CB.h;
  const scheduleConsole = 'https://console.apify.com/schedules';
  const button = (text, onclick) => h('button', {class: 'btn small', type: 'button', text, onclick});
  const consoleLink = (id, label) => h('a', {class: 'ext', href: scheduleConsole + (id ? '/' + encodeURIComponent(id) : ''),
    target: '_blank', rel: 'noopener noreferrer', text: label});
  function card(title, ...children) { return h('section', {class: 'card'}, h('h2', {text: title}), ...children); }

  function focus(body, data, project) {
    const open = (data.todo || []).filter(item => item.status === 'open');
    const due = data.due || [];
    body.appendChild(card('What needs attention',
      h('p', {text: open.length ? open[0].step : due[0] || 'Choose a next step based on your latest checks.'}),
      h('div', {class: 'tools'}, h('a', {class: 'btn', href: '#/p/' + encodeURIComponent(project) + '/todo',
        text: open.length ? 'View open actions (' + open.length + ')' : 'View actions'}),
        button('Get recommendations', () => CB.flows.nextSteps(project, () => { if (body.isConnected) location.reload(); })))));
  }

  function actions(body, data, project, reload) {
    const items = data.todo || [];
    const form = h('form', {class: 'addtodo'});
    const input = h('input', {type: 'text', maxlength: '200', required: true, 'aria-label': 'New action', placeholder: 'What will you change?'});
    const add = h('button', {class: 'btn', type: 'submit', text: 'Add action'});
    const message = h('p', {class: 'form-err', role: 'alert'});
    form.append(input, add);
    async function save(step, status, control) {
      const address = location.hash;
      control.disabled = true;
      try {
        await CB.saveTodo(project, [{step, status}]);
        if (body.isConnected && location.hash === address) reload();
      } catch (error) { if (body.isConnected) { control.disabled = false; message.textContent = error.message; } }
    }
    form.addEventListener('submit', event => {
      event.preventDefault();
      const step = input.value.trim();
      if (!step) return;
      if (items.some(item => item.step.toLowerCase() === step.toLowerCase())) {
        message.textContent = 'This action is already on the list.'; return;
      }
      save(step, 'open', add);
    });
    const list = h('ul', {class: 'todos'});
    for (const item of items) {
      const row = h('li', {class: 'todo-row'}, h('strong', {text: item.step}), h('span', {class: 'pill', text: item.status}));
      const change = (label, status) => button(label, event => save(item.step, status, event.currentTarget));
      if (item.status === 'open') row.append(change('Mark done', 'done'), change('Skip', 'skipped'));
      else row.append(change('Reopen', 'open'));
      list.append(row);
    }
    body.appendChild(card('Project actions', items.length ? list : h('p', {text: 'Add your first action or get a recommendation from your latest checks.'}),
      form, message, button('Get recommendations', () => CB.flows.nextSteps(project, reload))));
    if ((data.due || []).length) body.appendChild(card('Checks due', h('ul', {}, data.due.map(text => h('li', {text})))));
    if ((data.experiments || []).length) body.appendChild(card('Logged changes', h('ul', {}, data.experiments.slice().reverse()
      .map(item => h('li', {}, h('b', {text: item.action}), ' · ' + CB.day(item.date))))));
  }

  async function schedulesFor(projects) {
    const names = new Set(projects.map(project => 'citebase-' + project.project));
    const rows = [];
    if (!names.size) return rows;
    for (let offset = 0; ; ) {
      const page = await CB.apify('GET', 'schedules?limit=100&desc=1&offset=' + offset);
      const batch = page.items || [];
      rows.push(...batch.filter(item => names.has(item.name)));
      offset += batch.length;
      if (!batch.length || (Number.isFinite(page.total) ? offset >= page.total : batch.length < 100)) return rows;
    }
  }

  function schedules(body, projects) {
    const status = h('div', {'aria-live': 'polite'}), select = h('select', {'aria-label': 'Project to schedule'},
      projects.map(p => h('option', {value: p.project, text: p.brand || p.project})));
    async function load() {
      CB.clear(status).append(h('p', {text: 'Reading project schedules…'}));
      try {
        const rows = await schedulesFor(projects);
        if (!status.isConnected) return;
        CB.clear(status);
        if (!rows.length) status.append(h('p', {text: 'No Citebase schedules for these projects yet.'}));
        for (const row of rows) status.append(h('article', {class: 'sched'}, h('div', {class: 'sched-main'},
          h('h3', {text: row.title || row.name}), h('p', {text: (row.isEnabled ? 'Active' : 'Paused') +
            (row.isEnabled && row.nextRunAt ? ' · Next check ' + new Date(row.nextRunAt).toLocaleString() : '')})),
          consoleLink(row.id, 'Manage schedule ↗')));
      } catch (error) { CB.clear(status).append(h('p', {role: 'alert', text: error.message}), button('Try again', load)); }
    }
    body.append(card('Schedules', status, projects.length ? h('div', {class: 'tools'}, select,
      button('Set a schedule', () => schedule(select.value, load))) : h('p', {text: 'Add a project to schedule its first recheck.'}),
      consoleLink('', 'All schedules in Apify ↗')));
    load();
  }

  function schedule(project, done) {
    const frequency = h('select', {'aria-label': 'Frequency'}, ['monthly', 'weekly', 'daily'].map(value => h('option', {value, text: value})));
    const paid = h('input', {type: 'checkbox'});
    const status = h('div', {'aria-live': 'polite'});
    const controls = h('div', {class: 'form'}, h('label', {class: 'field'}, 'Repeat', frequency),
      h('label', {class: 'check'}, paid, ' Include paid AI checks each time'), status);
    const dlg = CB.flows.dialog('Schedule project rechecks', controls, [{label: 'Close', ghost: true}]);
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const confirm = button('Enable schedule', enable);
    dlg.foot.append(confirm);
    let plan, revision = 0;
    const existing = schedulesFor([{project}]);
    async function preview() {
      const version = ++revision;
      if (plan && plan.usage) plan.usage.bind(null);
      plan = null; confirm.disabled = true;
      CB.clear(status).append(h('p', {text: 'Preparing your schedule…'}));
      try {
        const rows = await existing;
        if (version !== revision || !dlg.el.open) return;
        if (rows.length) {
          CB.clear(status).append(h('p', {text: 'This project already has a schedule.'}), consoleLink(rows[0].id, 'Manage existing schedule ↗'));
          return;
        }
        const result = await CB.tool('schedule_checks', {project, frequency: frequency.value});
        if (version !== revision || !dlg.el.open) return;
        const extra = paid.checked ? (result.ai_checks || {}).runs || [] : [];
        CB.clear(status).append(h('p', {text: result.when + ' · ' + timezone + '. Apify bills platform usage to your account.'}));
        if (paid.checked && (!extra.length || extra.some(r => !(Number.isFinite(r.suggested_max_cost_usd) && r.suggested_max_cost_usd > 0 && Number.isInteger(r.times) && r.times > 0)))) {
          status.append(h('p', {text: 'A paid plan needs saved buying questions and a spending cap for each run. You can schedule just the site check.'}));
          return;
        }
        const cap = extra.reduce((sum,run) => sum + run.times * run.suggested_max_cost_usd,0);
        const usage = extra.length ? CB.usage.guard(cap,{
          frequency:frequency.value, paidRuns:extra.reduce((count,run) => count + run.times,0)
        }) : null;
        plan = {cron: result.cron, runs: [result.free_site_check, ...extra], usage}; confirm.disabled = false;
        if (usage) {status.append(usage.node); usage.bind(confirm);}
      } catch (error) { if (version === revision && dlg.el.open) CB.clear(status).append(CB.usage.errorDetails(error) || h('p', {role: 'alert', text: error.message})); }
    }
    async function enable() {
      if (!plan || confirm.disabled) return;
      const approved = plan;
      confirm.disabled = frequency.disabled = paid.disabled = true;
      let submitted = false;
      try {
        if (approved.usage) {
          approved.usage.bind(null);
          try { await approved.usage.verify(); }
          catch (error) {
            if (dlg.el.open) {
              frequency.disabled = paid.disabled = false;
              approved.usage.bind(confirm);
            }
            return;
          }
          confirm.disabled = true;
        }
        if (!dlg.el.open) return;
        const actions = [];
        for (const run of approved.runs) {
          const actor = await CB.apify('GET', 'acts/' + encodeURIComponent(run.actor.replace('/', '~')));
          const action = {type: 'RUN_ACTOR', actorId: actor.id, runInput: {body: JSON.stringify(run.input), contentType: 'application/json; charset=utf-8'}};
          if (run.suggested_max_cost_usd) action.runOptions = {maxTotalChargeUsd: run.suggested_max_cost_usd};
          for (let i = 0; i < (run.times || 1); i++) actions.push(action);
        }
        if (!dlg.el.open) return;
        submitted = true;
        await CB.apify('POST', 'schedules', {name: 'citebase-' + project, title: 'Citebase: ' + project, cronExpression: approved.cron,
          timezone, isEnabled: true, isExclusive: true, actions});
        if (dlg.el.open) { dlg.close(); CB.toast('Schedule enabled'); if (done) done(); }
      } catch (error) {
        if (!dlg.el.open) return;
        const billing = CB.usage.errorDetails(error);
        if (billing) { CB.clear(status).append(billing); return; }
        CB.clear(status).append(h('p', {role: 'alert', text: submitted ? 'Check your Apify schedules to see whether this schedule was created.' : error.message}));
        if (submitted) status.append(consoleLink('', 'Review schedules ↗'));
        else confirm.disabled = frequency.disabled = paid.disabled = false;
      }
    }
    frequency.addEventListener('change', preview); paid.addEventListener('change', preview);
    preview();
  }

  CB.historyUI = {focus, actions, schedulesFor, schedules, schedule};
})();
