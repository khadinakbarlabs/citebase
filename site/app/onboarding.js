(function () {
  'use strict';
  const CB = window.CB, h = CB.h;
  function number(value) {
    return typeof value === 'number' ? value.toLocaleString(undefined, {maximumFractionDigits:2}) : 'Unmeasured';
  }
  function metric(label, value) {
    return h('div', {}, h('dt', {text:label}), h('dd', {text:value}));
  }
  // One connected Google report: totals, a top-rows chart, quick wins and a searchable table.
  function sum(rows, key) { return rows.reduce((n, r) => n + (typeof r[key] === 'number' ? r[key] : 0), 0); }
  function googleLogo(service) {
    if (!CB.s) return null;
    return CB.s('svg', {class:'g-logo', 'aria-hidden':'true', focusable:'false'},
      CB.s('use', {href:'../assets/icons.svg#' + (service === 'ga4' ? 'logo-ga' : 'logo-gsc')}));
  }
  function tile(label, value, hint) {
    return h('div', {class:'gr-kpi'}, h('span', {class:'gr-k', text:label}), h('b', {class:'gr-v', text:value}), hint ? h('span', {class:'gr-hint', text:hint}) : null);
  }
  // Searches seen often on page one or two but rarely clicked: a better title or answer can win clicks.
  function quickWin(row) {
    return typeof row.impressions === 'number' && row.impressions >= 50 && typeof row.position === 'number' &&
      row.position > 3 && row.position <= 20 && (row.clicks || 0) / row.impressions < 0.02;
  }
  CB.renderGoogleReports = function (container, reports, nativeOnly) {
    for (const [service, report] of Object.entries(reports || {})) {
      if (!report || (nativeOnly && report.provenance !== 'google_sync')) continue;
      const analytics = service === 'ga4';
      const title = analytics ? 'Your website traffic' : 'Your Google Search performance';
      const heading = h('h3', {class:'gr-title', text:title});
      const logo = googleLogo(service);
      if (logo) heading.append(logo);
      const card = h('section', {class:'setup-card gr-card'}, heading);
      const period = report.start_date && report.end_date ? report.start_date+' – '+report.end_date : 'Measurement period unavailable';
      const description = [report.source, report.property, report.observed_at, period,
        report.provenance === 'google_sync' ? 'Synced from Google' : 'Imported report'];
      card.append(h('p', {class:'gr-meta', text:description.filter(Boolean).join(' · ')}));
      const rows = report.rows || [];
      const label = row => String(analytics ? row.source : row.term);
      const valueKey = analytics ? 'sessions' : 'clicks';
      // Headline numbers.
      if (rows.length || report.clicks != null || report.all_visits != null) {
        const kpis = h('div', {class:'gr-kpis'});
        if (analytics) {
          const sessions = sum(rows, 'sessions');
          kpis.append(...[tile('Sessions', number(rows.length ? sessions : report.all_visits)),
            tile('Traffic sources', number(rows.length)),
            report.ai_visits != null ? tile('Visits from AI', number(report.ai_visits)) : null,
            rows.length ? tile('Top source', label(rows.slice().sort((a, b) => (b.sessions || 0) - (a.sessions || 0))[0])) : null].filter(Boolean));
        } else {
          const clicks = report.clicks != null ? report.clicks : sum(rows, 'clicks');
          const views = report.impressions != null ? report.impressions : sum(rows, 'impressions');
          const weighted = rows.filter(r => typeof r.position === 'number' && typeof r.impressions === 'number');
          const shown = sum(weighted, 'impressions');
          const position = shown ? weighted.reduce((n, r) => n + r.position * r.impressions, 0) / shown : null;
          kpis.append(tile('Total clicks', number(clicks)), tile('Total impressions', number(views), 'Times your site was shown'),
            tile('Click rate', views ? (clicks / views * 100).toFixed(1) + '%' : 'Unmeasured'),
            tile('Average position', position == null ? 'Unmeasured' : position.toFixed(1), '1 is the top result'));
        }
        card.append(kpis);
      }
      // Top rows as a chart.
      const top = rows.filter(r => typeof r[valueKey] === 'number' && r[valueKey] > 0)
        .sort((a, b) => b[valueKey] - a[valueKey]).slice(0, 8);
      if (top.length > 1 && CB.barChart) {
        card.append(h('div', {class:'gr-chart'}, h('h4', {text:analytics ? 'Top traffic sources' : 'Top searches by clicks'}),
          CB.barChart({aria:analytics ? 'Sessions by traffic source' : 'Clicks by search', width:640, labelWidth:200,
            items:top.map(r => ({label:label(r), value:r[valueKey], tip:analytics ? [number(r.sessions)+' sessions'] :
              [number(r.clicks)+' clicks', number(r.impressions)+' impressions', 'Average position '+number(r.position)]}))})));
      }
      // Quick wins for Search Console.
      const wins = analytics ? [] : rows.filter(quickWin).sort((a, b) => b.impressions - a.impressions).slice(0, 5);
      if (wins.length) {
        card.append(h('div', {class:'gr-wins'}, h('h4', {text:'Quick wins'}),
          h('p', {text:'People see you for these searches but rarely click. A clearer page title or a page that answers the search can win those clicks.'}),
          h('ul', {}, wins.map(r => h('li', {}, h('b', {text:label(r)}),
            h('span', {text:number(r.impressions)+' views · '+number(r.clicks)+' clicks · position '+number(r.position)}))))));
      }
      // Searchable table.
      const records = h('div', {class:'gr-rows'});
      const filter = h('input', {type:'search', 'aria-label':analytics ? 'Filter traffic sources' : 'Filter Google queries',
        placeholder:analytics ? 'Find a traffic source' : 'Find a search query'});
      function renderRows() {
        records.replaceChildren();
        const query = filter.value.trim().toLowerCase();
        const matches = rows.filter(row => label(row).toLowerCase().includes(query))
          .sort((x, y) => (Number(y[valueKey]) || 0) - (Number(x[valueKey]) || 0));
        if (matches.length > 10 || query) {
          records.append(h('small', {text:'Showing '+Math.min(10, matches.length)+' of '+matches.length+' matching rows'}));
        }
        if (!matches.length) return;
        const head = analytics ? ['Source', 'Sessions'] : ['Search', 'Clicks', 'Impressions', 'Click rate', 'Average position'];
        const table = h('table', {class:'gr-table'}, h('thead', {}, h('tr', {}, head.map((t, i) => h('th', {scope:'col', class:i ? 'n' : null, text:t})))));
        const body = h('tbody', {});
        for (const row of matches.slice(0,10)) {
          const name = h('td', {}, h('span', {text:label(row)}), !analytics && quickWin(row) ? h('span', {class:'gr-tag', text:'Quick win'}) : null);
          body.append(h('tr', {}, name, ...(analytics ? [h('td', {class:'n', text:number(row.sessions)})] : [
            h('td', {class:'n', text:number(row.clicks)}), h('td', {class:'n', text:number(row.impressions)}),
            h('td', {class:'n', text:typeof row.impressions === 'number' && row.impressions ? ((row.clicks || 0) / row.impressions * 100).toFixed(1) + '%' : 'Unmeasured'}),
            h('td', {class:'n', text:number(row.position)})])));
        }
        table.append(body);
        records.append(h('div', {class:'scroll'}, table));
      }
      filter.addEventListener('input', renderRows);
      if (rows.length > 10) card.append(filter);
      card.append(records);
      renderRows();
      if (!rows.length) {
        const msg = analytics && report.all_visits != null ?
          number(report.all_visits)+' reported visits · '+number(report.ai_visits)+' AI visits' : 'No individual measurements available.';
        card.append(h('p', {text:msg}));
      }
      container.append(card);
    }
  };
  CB.onboarding = function (body, project, slug) {
    const root = h('section', {class:'setup-work'}), status = h('p',{role:'status'}), content = h('div',{class:'setup-work'});
    body.appendChild(root);
    let state, step, sequence = 0, practice=false;
    const stages = ['competitors','terms','research'];
    const names = ['Competitors','Search terms','Questions and plan'];
    // What Citebase read about the business: summary, buyer groups and markets, each with its source.
    function profileCard() {
      const p = state.profile;
      if (!p || !(p.summary || (p.audiences || []).length || (p.markets || []).length)) return null;
      const chips = (title, rows) => rows && rows.length ? h('div',{class:'profile-row'},h('b',{text:title}),
        h('ul',{class:'chips'},rows.map(r=>h('li',{title:r.reason || '',text:r.name})))) : null;
      const card = h('section',{class:'setup-card profile-card'},h('h3',{text:'What Citebase learned about your business'}),
        p.summary ? h('p',{class:'profile-summary',text:p.summary}) : null,
        chips('Buyer groups',p.audiences), chips('Markets',p.markets),
        h('p',{class:'small-note',text:'Read from your website and project settings. Questions and competitor suggestions use this context.'}));
      if (!CB.demo) card.append(button('Save to project brief',async e=>{
        const b=e.currentTarget;b.disabled=true;
        try{const {brief}=await work('brief_get');
          await work('brief_save',{expected_revision:brief.revision,offer:brief.offer || p.summary || '',
            audience:brief.audience || (p.audiences || []).map(a=>a.name).join(', '),market:brief.market || (p.markets || []).map(m=>m.name).join(', ')});
          b.textContent='✓ Saved to the project brief';
        }catch(err){b.disabled=false;error(err);}
      }));
      return card;
    }
    // Tracked questions: remove any, add suggested ones or write your own.
    function questionsCard() {
      const card=h('section',{class:'setup-card questions-card'},h('h3',{text:'Questions AI assistants are asked'}),
        h('p',{class:'small-note',text:'Citebase asks these in each AI check. Reports compare only the questions two rounds share, so changes stay fair.'}));
      const tracked=state.questions || [], ideas=state.question_ideas || [];
      async function update(change){
        if(CB.demo){
          const removed=new Set(change.remove || []), added=(change.add || []).map(x=>typeof x==='string'?x:x.prompt);
          state.questions=tracked.filter(q=>!removed.has(q.prompt_id)).concat(added.map((prompt,i)=>({prompt,prompt_id:'practice-'+Date.now()+i,type:'consideration'})));
          state.question_ideas=ideas.filter(q=>!added.includes(q.prompt));
          draw();status.textContent='Practice only: sign in to save your questions.';return;
        }
        state=await work('questions_update',{revision:state.revision,...change});draw();status.textContent='Tracked questions updated.';
      }
      const run=fn=>async e=>{const b=e.currentTarget;b.disabled=true;try{await fn();}catch(err){b.disabled=false;error(err);}};
      card.append(h('ul',{class:'question-list'},tracked.map(q=>h('li',{},h('span',{text:q.prompt || q.question}),
        tracked.length>1?h('button',{type:'button',class:'btn tiny',text:'Remove','aria-label':'Remove question: '+(q.prompt || q.question),
          onclick:run(()=>update({remove:[q.prompt_id]}))}):null))));
      if(ideas.length)card.append(h('h4',{text:'Suggested from your business profile'}),h('ul',{class:'question-list ideas'},ideas.map(q=>h('li',{},
        h('span',{},q.prompt,q.reason?h('small',{text:' · '+q.reason}):null),
        h('button',{type:'button',class:'btn tiny',text:'Add','aria-label':'Add question: '+q.prompt,onclick:run(()=>update({add:[{prompt:q.prompt,type:q.type,topic:q.topic}]}))})))));
      const own=h('input',{type:'text',placeholder:'Write a question a buyer would ask','aria-label':'Your own question'});
      card.append(h('div',{class:'question-add'},own,h('button',{type:'button',class:'btn small',text:'Add question',onclick:run(async()=>{
        if(own.value.trim().length<8)throw Error('Write a full question of at least 8 characters.');await update({add:[own.value.trim()]});})})));
      return card;
    }
    function button(text, action) { return h('button',{type:'button',class:'btn ghost',text,onclick:action}); }
    function work(op, data) { return CB.work(slug, op, data || {}); }
    function error(e) { status.textContent = e.message || 'Could not load this project.'; }
    async function load() {
      try {
        state = await work('onboarding_get');
        if(CB.newSetupProject===slug && !CB.demo){
          CB.newSetupProject=null;
          if(state.stage==='competitors' && state.pages_checked===undefined){
            status.textContent='Reading your website to suggest competitors and search terms…';
            try{state=await work('onboarding_suggest',{revision:state.revision});}
            catch(e){step='competitors';draw();error(e);return;}
          }
        }
        step = stages.includes(state.stage) ? state.stage : 'competitors';
        draw();
      } catch(e) {error(e); content.replaceChildren(button('Retry setup',load));}
    }
    root.append(h('h2',{text:'Project setup'}),h('p',{text:project.brand && project.brand.site || slug}),status,content);
    function draw() {
      const token = ++sequence;
      status.textContent='';
      const nav=h('nav',{class:'setup-steps','aria-label':'Project setup steps'});
      stages.forEach((s,i)=>{const b=button(names[i],()=>{step=s;draw();});if(step===s)b.setAttribute('aria-current','step');nav.append(b);});
      const panel=h('section',{class:'setup-card',tabindex:'-1'});
      content.replaceChildren(nav,panel);
      if(CB.demo)nav.append(button(practice?'Reset practice':'Practice setup',async()=>{
        practice=!practice;state=structuredClone(await work('onboarding_get'));step='competitors';draw();
      }));
      if(step==='research'){research(panel,token);return;}
      const terms=step==='terms', key=step;
      panel.append(h('h3',{text:terms?'Choose search terms':'Choose competitors'}),h('p',{text:terms?'Choose the searches you want to track.':'Choose the businesses buyers compare with yours.'}));
      if(state.stage==='website'){const site=h('input',{type:'text',placeholder:'example.com','aria-label':'Project website'});
        panel.append(site,button('Save website and continue',async e=>{
          const b=e.currentTarget;b.disabled=true;
          try{const url=CB.flows.projectWebsite(site.value);
            await CB.tool('save_results',{project:slug,brand:{...project.brand,site:url.href,domain:url.hostname,name:project.brand?.name || slug}});
            state=await work('onboarding_get');if(!state.website)throw Error('The saved website could not be confirmed.');
            state=await work('onboarding_suggest',{revision:state.revision});step='competitors';draw();
          }catch(err){error(err);}finally{b.disabled=false;}
        }));return;}
      if(!terms){const profile=profileCard();if(profile)content.insertBefore(profile,panel);}
      if(!terms && state.competitor_help)panel.append(h('p',{text:state.competitor_help}));
      const inputs=[],domains=new Map();
      for(const row of state[key] || []) {
        const value=terms?row.term:row.name || row.domain;
        const input=h('input',{type:'checkbox',value});input.checked=row.selected!==false;inputs.push(input);
        panel.append(h('label',{},input,h('span',{},value,row.reason?h('small',{text:' · '+row.reason}):null,row.ai_checked?h('small',{text:row.recommended?' · Recommended for your website':' · Checked against your website'}):null)));
        if(row.url && CB.safeUrl(row.url))panel.append(h('a',{href:CB.safeUrl(row.url),target:'_blank',rel:'noopener noreferrer',text:'Source for '+value}));
        if(!terms && !CB.demo){const field=h('input',{value:row.domain || '',placeholder:'rival.example','aria-label':'Website domain for '+value});domains.set(value,field);panel.append(h('label',{},'Website domain for '+value+' (enables traffic estimates)',field));}
      }
      if((CB.demo && !practice) || stages.indexOf(step)>stages.indexOf(state.stage)){
        inputs.forEach(input=>input.disabled=true);
        panel.append(h('p',{text:CB.demo?'This sample is read-only. Sign in to save your project choices.':stages.indexOf(step)<stages.indexOf(state.stage)?'These selections are saved to your project.':'Finish the previous step to save these choices.'}),button(terms?'View research':'View search terms',()=>{step=terms?'research':'terms';draw();}));
        return;
      }
      const custom=h('textarea',{id:'setup-custom',name:key});
      panel.append(h('label',{for:'setup-custom',text:terms?'Additional search terms (one per line)':'Additional competitors (one per line)'}),custom);
      async function save(defaults) {
        const payload={revision:state.revision,step:key};
        if(defaults)payload.use_recommended=true;
        else payload[key]=Array.from(new Set(inputs.filter(i=>i.checked).map(i=>i.value).concat(custom.value.split(/\n/).map(v=>v.trim()).filter(Boolean))));
        if(practice){if(payload[key])state[key]=payload[key].map(v=>terms?{term:v,selected:true}:{name:v,selected:true});step=state.stage=terms?'research':'terms';draw();return;}
        if(!terms){const selected=payload[key] || [];payload.competitor_domains=Object.fromEntries([...domains].filter(([v,f])=>selected.includes(v)&&f.value.trim()).map(([v,f])=>[v,f.value.trim()]));}
        await work('onboarding_save',payload);state=await work('onboarding_get');step=terms?'research':'terms';draw();
      }
      function action(text, fn, primary) {
        const b=button(text,async()=>{
          const buttons=Array.from(content.querySelectorAll('button:not(:disabled)'));
          buttons.forEach(x=>x.disabled=true);
          try{await fn();}catch(e){error(e);}finally{buttons.forEach(x=>x.disabled=false);}
        });
        if(primary)b.classList.remove('ghost');
        panel.append(b);
      }
      action('Save and continue',()=>save(false),true);
      if(terms && state.terms.some(row=>row.selected))action('Use recommended terms',()=>save(true));
      if(!CB.demo && !terms && CB.researchCollection && state.pages_checked!==undefined){
        const holder=h('details',{},h('summary',{text:'Optional competitor search check'})); panel.append(holder);
        holder.addEventListener('toggle',async()=>{
          if(!holder.open || holder.children.length>1)return;
          const area=h('div',{text:'Loading collection plan…'});holder.append(area);
          let refreshing=false;
          const current=()=>root.isConnected && sequence===token;
          async function refresh(){
            if(refreshing || !current())return;refreshing=true;panel.inert=true;
            try{const latest=await work('onboarding_get');if(!current())return;
              const result=await work('onboarding_suggest',{revision:latest.revision});
              if(current()){state=result;draw();status.textContent='Review the Google search competitors and confirm which are business rivals.';}
            }catch(err){if(current())error(err);}finally{refreshing=false;panel.inert=false;}
          }
          try{const plan=await work('research_plan');if(current())area.replaceChildren(CB.researchCollection.panel(slug,plan,refresh,{discovery:true}));}
          catch(e){area.textContent=e.message || 'Could not load the collection plan.';}
        });
      }
      if(!CB.demo && !terms)action('Analyze website for suggestions',async()=>{status.textContent='Reading website pages and saved project evidence…';state=await work('onboarding_suggest',{revision:state.revision});draw();status.textContent=(state.pages_checked || 0)+' website pages reviewed.';});
    }
    async function research(panel,token) {
      panel.append(h('h3',{text:'Questions, plan and research'}));
      if(CB.demo)panel.append(h('p',{text:'Fictional sample research. Sign in to collect evidence for your own project.'}));
      if(state.tracking_note)panel.append(h('p',{text:state.tracking_note}));
      content.insertBefore(questionsCard(),panel);
      if(CB.seoPlan)CB.seoPlan.render(content,slug);
      if(CB.googleUI){
        const google=h('details',{},h('summary',{text:'Connect Google Search Console or Analytics (optional)'}));
        google.addEventListener('toggle',()=>{if(google.open && google.children.length===1)google.append(CB.googleUI.panel(slug));});
        panel.append(google);
      }
      try {
        const [data,plan]=await Promise.all([work('research_get'),work('research_plan')]);
        if(token!==sequence)return;
        if(CB.researchCollection)panel.append(CB.researchCollection.panel(slug,plan,draw));
        CB.renderGoogleReports(content,data.first_party);
        const sections={
          keywords:['Search traffic','Import a search report or collect monthly search volumes.'],
          competitors:['Competitor research','Collect or import a traffic estimate for a confirmed rival.'],
          pages:['Ranking pages','Collect search results for a selected term to see which pages rank.'],
          ai:['AI rank by engine','Run an AI check to measure answers for your tracked questions.'],
          citations:['Citations and outreach','Import a measured citation or run an AI check with source links.']
        };
        const coverage=h('section',{class:'setup-card'},h('h3',{text:'Research coverage'}),h('div',{class:'setup-metrics'},
          Object.entries(sections).map(([key,[title]])=>h('div',{},h('b',{text:String((data[key] || []).length)}),h('small',{text:title})))));
        content.append(coverage);
        for(const [key,[title,emptyHelp]] of Object.entries(sections)){
          const list=data[key] || [],group=h('section',{class:'setup-card'},h('h3',{text:title}));
          if(key==='ai'){
            const missing=['ChatGPT','Claude','Gemini'].filter(engine=>!list.some(row=>row.engine===engine));
            if(missing.length)group.append(h('p',{text:'No saved answers from '+missing.join(', ')+'.'}));
          }
          if(!list.length)group.append(h('p',{text:emptyHelp}), key==='ai'||key==='citations'?
            h('a',{href:'#/p/'+encodeURIComponent(slug)+'/answers',text:'Open AI answers'}):
            button('View collection options',()=>{panel.scrollIntoView();panel.focus();}));
          const more=list.length>6?h('details',{},h('summary',{text:'Show '+(list.length-6)+' more records'})):null;
          for(const [index,row] of list.entries()){
            const record=h('article',{class:'setup-record'}),metrics=h('dl',{});
            record.append(h('h4',{text:row.term || row.name || row.domain}));
            if(key==='keywords'){
              if(row.impressions!=null)metrics.append(metric('Impressions',number(row.impressions)),metric('Clicks',number(row.clicks)));
              else metrics.append(metric('Monthly searches',number(row.search_volume)));
            }
            if(key==='competitors')metrics.append(metric('Domain',row.domain || 'Unknown'),metric('Estimated organic visits',number(row.estimated_organic_traffic)));
            if(key==='pages')metrics.append(metric('Search position',number(row.position)),metric('Estimated page visits',number(row.estimated_traffic)));
            if(key==='ai')metrics.append(metric('AI engine',row.engine),metric('Brand',row.brand || state.brand),metric('Observed rank',number(row.position)),metric('Mentioned in',row.answers==null?(row.mentions==null?'Unknown':number(row.mentions)+' observed mentions')+' · total answers unknown':number(row.mentions)+' of '+number(row.answers)+' answers'),
              metric('Cited pages',String((data.citations || []).filter(c=>c.term===row.term && c.engine===row.engine && (!row.snapshot || c.snapshot===row.snapshot)).length)));
            if(key==='ai' && row.position_samples!=null)metrics.append(metric('Ranked answers',number(row.position_samples)));
            if(row.position_evidence?.length)record.append(h('details',{},h('summary',{text:'View ranking evidence'}),h('ul',{},row.position_evidence.map(line=>h('li',{text:line})))));
            if(key==='citations')metrics.append(metric('AI engine',row.engine));
            if(row.url && CB.safeUrl(row.url))record.append(h('a',{href:CB.safeUrl(row.url),target:'_blank',rel:'noopener noreferrer',text:row.url}));
            record.append(metrics);
            const source=h('small',{class:'setup-source'},h('span',{text:row.source || 'Source unavailable'}));
            [row.observed_at,row.country || row.market || (row.location_code===2840?'United States':row.location_code),row.language].filter(Boolean).forEach(v=>source.append(' · '+v));
            record.append(source);
            if(key==='citations' && CB.citationOutreach)record.append(button('Review author and outreach',()=>CB.citationOutreach.open(slug,{url:row.url,term:row.term})));
            (index>=6 && more?more:group).append(record);
          }
          if(more)group.append(more);
          content.append(group);
        }
      } catch(e){if(token===sequence){error(e);panel.append(button('Retry research',draw));}}
    }
    load();
  };
})();
