/* The public tour navigates the same project screens as a signed-in workspace. */
(function () {
  'use strict';
  const CB = window.CB, h = CB.h, F = CB.flows;
  const project = '#/p/acme-payroll/';
  const $ = selector => document.querySelector('#main ' + selector);
  const fire = (el, type) => el.dispatchEvent(new Event(type, {bubbles:true}));
  // Each step points at one real control, notices when the visitor uses it, and can do it for them.
  // [route, title, instruction, find target, event that completes it, check, "Show me" action, result]
  const steps = [
    [project + 'overview', 'Read your visibility snapshot', 'Click the highlighted Site health card. The chart switches and explains how the number was measured.',
      () => [...document.querySelectorAll('#main .snapshot-metric')].find(b => /Site health/.test(b.textContent)), 'click', () => true,
      el => el.click(), 'The chart now shows site health. Every card works the same way.'],
    [project + 'setup', 'Choose the competitors to track', 'Choose Practice setup, then tick a competitor. Citebase suggests rivals from your site and public sources, and you decide which ones count.',
      () => $('input[type=checkbox]:not([disabled])') || [...document.querySelectorAll('#main button')].find(b => b.textContent === 'Practice setup'),
      'change', () => true,
      el => { if (el.tagName === 'BUTTON') { el.click(); setTimeout(() => { const box = $('input[type=checkbox]:not([disabled])'); if (box) box.click(); }, 300); } else el.click(); },
      'Citebase now compares answers against your pick. In your workspace it also suggests search terms, markets, buyer types and the questions to track.'],
    [project + 'questions', 'Follow a buyer question', 'Type “10 person” in the highlighted search box. Read across the row to see which assistants recommended Acme.',
      () => $('input.search'), 'input', el => el.value.trim().length >= 2,
      el => { el.value = '10 person'; fire(el, 'input'); }, 'Each row is one buyer question, checked in every assistant.'],
    [project + 'site', 'Inspect a website finding', 'Filter the audit to high-priority findings, then open one to see the page and evidence.',
      () => $('select[aria-label="Filter findings"]'), 'change', el => /high/i.test(el.value + el.selectedOptions[0]?.textContent),
      el => { const option = [...el.options].find(o => /high/i.test(o.textContent)); if (option) el.value = option.value; fire(el, 'change');
        setTimeout(() => { const finding = $('details.audit-finding'); if (finding) finding.open = true; }, 150); },
      'Findings are grouped as on-page, technical and off-page, with the evidence behind each.'],
    [project + 'todo', 'Choose the next action', 'Open the highlighted evidence. See the suggested fix, who owns it and how the team will check the change.',
      () => $('details.work-details'), 'toggle', el => el.open, el => { el.open = true; },
      'Actions link back to the finding or AI answer that justified them.'],
    ['#/schedules', 'Review a schedule', 'Open the scope of the sample schedule. In your workspace you set limits and an end date before a check runs.',
      () => $('details.work-details'), 'toggle', el => el.open, el => { el.open = true; },
      'Schedules repeat a check you already approved, within the limits you set.']
  ].map(([path, title, text, find, event, check, show, result]) => ({path, title, text, find, event, check, show, result}));
  const tourUrl = './?demo=1&tour=1' + steps[0].path;
  const host = document.getElementById('workspace-guide');
  const completed = new Set();
  let previousStep = 0, moveFocus = false, target = null, watcher = null;
  function clearTarget() {
    if (target) target.classList.remove('tour-target');
    target = null;
  }
  // The dashboard re-renders sections asynchronously, so keep looking for the step's control.
  function attachTarget(index) {
    clearTarget();
    if (watcher) watcher.disconnect();
    if (index < 0) return;
    const step = steps[index], main = document.getElementById('main');
    const bind = () => {
      const el = step.find();
      if (!el || el === target) return;
      clearTarget();
      target = el;
      if (!completed.has(index)) el.classList.add('tour-target');
      el.addEventListener(step.event, () => {
        if (!step.check(el) || completed.has(index)) return;
        completed.add(index);
        renderTour();
      });
      if (!completed.has(index)) el.scrollIntoView({block:'center', behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    };
    watcher = new MutationObserver(bind);
    watcher.observe(main, {childList:true, subtree:true});
    bind();
  }
  function tourState(value) {
    const address = new URL(location.href);
    if (value) address.searchParams.set('tour',value);
    else address.searchParams.delete('tour');
    history.replaceState(null,'',address.pathname + address.search + address.hash);
    moveFocus = true;
    renderTour();
    if (host.hidden) document.getElementById('main').focus({preventScroll:true});
  }
  function nav(label, target, primary) {
    return h('a',{class:primary ? 'btn' : 'btn ghost',href:target,text:label,onclick:() => {moveFocus=true;}});
  }
  function renderTour() {
    const state = new URLSearchParams(location.search).get('tour');
    CB.clear(host);
    host.hidden = !CB.demo || !['1','done'].includes(state);
    if (host.hidden) { attachTarget(-1); return; }
    const path = location.hash.split('?')[0] || '#/';
    const index = steps.findIndex(step=>step.path===path), active = index >= 0;
    if (active) previousStep = index;
    const done = state === 'done', finished = active && completed.has(index);
    const title = h('h2',{tabindex:'-1',text:done ? 'Ready to try your website?' : active ? steps[index].title : 'Explore the sample project'});
    const actions = h('div',{class:'guide-actions'});
    const text = done ? 'Sign in with Apify and add your website. Citebase audits it, suggests competitors, search terms and buyer questions, and turns the results into on-page, off-page and technical actions.' :
      active ? (finished ? '✓ ' + steps[index].result : steps[index].text) : 'You can explore any section and return to the walkthrough when you’re ready.';
    const eyebrow = done ? 'Tour complete' : active ? 'Step '+(index+1)+' of '+steps.length + (finished ? ' · done' : ' · your turn') : 'Dashboard tour';
    if (done) {
      actions.append(h('a',{class:'btn',href:'/api/session/?start',text:'Add my website'}),
        h('button',{class:'btn ghost',type:'button',text:'Explore on my own',onclick:()=>tourState(null)}));
    } else {
      if (active && index > 0) actions.append(nav('Back',steps[index-1].path));
      if (active && !finished) actions.append(h('button',{class:'btn ghost',type:'button',text:'Show me',onclick:()=>{
        const el = steps[index].find(); if (el) steps[index].show(el);
      }}));
      if (!active) actions.append(nav('Resume tour',steps[previousStep].path,true));
      else if (index < steps.length-1) actions.append(nav(finished ? 'Next step' : 'Skip',steps[index+1].path,finished));
      else actions.append(h('button',{class:finished ? 'btn' : 'btn ghost',type:'button',text:'Finish tour',onclick:()=>tourState('done')}));
      actions.append(h('button',{class:'guide-exit',type:'button',text:'Exit tour',onclick:()=>tourState(null)}));
    }
    host.classList.toggle('step-done', finished);
    host.append(h('div',{class:'guide-copy','aria-live':'polite'},h('span',{class:'guide-label',text:eyebrow}),title,h('p',{text})),actions);
    if (active && !done) host.append(h('div',{class:'tour-progress','aria-hidden':'true'},steps.map((_,i)=>h('i',{class:completed.has(i)?'filled':i===index?'current':''}))));
    attachTarget(active && !done ? index : -1);
    if (moveFocus) {title.focus({preventScroll:true});moveFocus=false;}
  }

  function assistantRoute(slug) {return '#/assistants' + (slug ? '?project='+encodeURIComponent(slug) : '');}
  function workspaceGuide(projects, fresh) {
    const box=h('section',{class:'welcome-guide','aria-label':'Workspace guide'});
    const name = fresh ? 'Signed in with Apify' : 'Workspace guide';
    const next = projects.find(p=>p.last_site_check);
    box.append(h('div',{class:'guide-copy'},h('span',{class:'guide-label',text:name}),
      h('h2',{text:projects.length ? 'Put your latest audit to work' : 'Start with your website'}),
      h('p',{text:projects.length ? 'Review a saved finding here, or ask your assistant to explain the same result.' :
        'Add a website to save its first audit. You can connect an assistant now or after you have a result.'})),
      h('div',{class:'guide-actions'},
        next ? h('a',{class:'btn ghost',href:'#/p/'+encodeURIComponent(next.project)+'/site',text:'Read a saved audit'}) : null,
        h('a',{class:'btn ghost',href:assistantRoute(next?.project || projects[0]?.project),text:'Connect an AI assistant'})));
    return box;
  }

  const address = F.setupAddress;
  const guides = {
    ChatGPT:{steps:['Open Settings → Apps → Advanced settings. Enable developer mode if your workspace offers it.',
      'Create an app named Citebase. Paste the connector address and choose OAuth.','Connect with the Apify account that owns your project, then select the app in a chat.'],
      docs:'https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt'},
    Claude:{steps:['Open Customize → Connectors and add a custom web connector named Citebase.',
      'Paste the connector address and continue with sign-in.','Choose your Apify account, then enable Citebase in a conversation.'],
      docs:'https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp'},
    Codex:{steps:['Run the setup command in your terminal.','If Codex asks for authentication, follow the Apify sign-in link. You can also run codex mcp login citebase.',
      'Open a new Codex chat and use the question below.'],command:'codex mcp add citebase --url "'+address+'"',docs:'https://developers.openai.com/codex/mcp/'},
    Hermes:{steps:['Run the setup command where Hermes is installed.','Use hermes mcp login citebase to authorize your Apify account if prompted.',
      'Start a new Hermes session or use /reload-mcp, then ask about a saved project.'],command:'hermes mcp add citebase --url "'+address+'" --auth oauth',
      docs:'https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp'},
    'Claude Code':{steps:['Run the command in your terminal.','Enter /mcp in Claude Code, choose citebase and authenticate with Apify.','Ask Claude Code to read your saved audit.'],
      command:'claude mcp add --transport http citebase "'+address+'"',docs:'https://code.claude.com/docs/en/mcp'},
    Cursor:{steps:['Open Cursor settings and find Tools & MCP.','Add the remote server configuration below.','Connect with Apify, then select the tools in Agent.'],
      command:JSON.stringify({mcpServers:{citebase:{url:address}}},null,2),docs:'https://cursor.com/docs/context/mcp'},
    Other:{steps:['Choose a client that supports remote MCP over HTTP and OAuth.','Add Citebase as a server using the connector address.',
      'Sign in with the same Apify account, then ask the assistant to read your saved results.'],docs:'https://docs.apify.com/platform/integrations/mcp'}
  };
  function assistantPage(container, slug) {
    const select=h('select',{'aria-label':'Your assistant'},Object.keys(guides).map(name=>h('option',{value:name,text:name})));
    const instructions=h('section',{class:'connection-card','aria-label':'Connection instructions'});
    const prompt=slug ? 'Open Citebase project '+slug+' in my Apify account. From its latest saved website audit, give me the date, site health score and highest-priority finding. Use saved results only.' :
      'List my saved Citebase projects in this Apify account. Ask which one to open, then summarize its latest saved website audit. Use saved results only.';
    function show() {
      const name=select.value, client=guides[name];
      CB.clear(instructions).append(h('h2',{text:'Set up '+name}),h('ol',{class:'connection-steps'},client.steps.map(s=>h('li',{text:s}))),
        h('div',{class:'guide-code-label',text:client.command ? name==='Cursor'?'Server configuration':'Terminal command':'Connector address'}),
        F.copyBox(client.command || address,'Copy setup'),
        h('a',{class:'ext',href:client.docs,target:'_blank',rel:'noopener noreferrer',text:name==='Other'?'Apify MCP guide ↗':name+' setup guide ↗'}));
    }
    select.addEventListener('change',show);show();
    container.append(h('a',{class:'ext',href:'#/',text:'Back to projects'}),
      h('header',{class:'connection-head'},h('h1',{text:'Connect an AI assistant'}),
        h('p',{text:'Use the same Apify account in both places. Your assistant can open the audit and findings you see in Citebase.'})),
      h('div',{class:'connection-layout'},h('div',{},h('label',{class:'assistant-picker'},h('span',{text:'Your assistant'}),select),instructions),
        h('section',{class:'connection-card prompt-card'},h('span',{class:'guide-label',text:'Check the connection'}),
          h('h2',{text:'Ask about a saved result'}),h('p',{text:'Paste this into a new chat with the connector enabled. Compare the answer with your Site tab. Reading saved results can incur ordinary Apify compute.'}),
          F.copyBox(prompt,'Copy first question'),slug?h('a',{class:'ext',href:'#/p/'+encodeURIComponent(slug)+'/site',text:'Open this project’s audit →'}):null)));
  }
  CB.guide={tourUrl,renderTour,assistantRoute,workspaceGuide,assistantPage};
})();
