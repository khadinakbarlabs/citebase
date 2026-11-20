/* Read-only project work for the two fictional dashboard projects. */
(function () {
  'use strict';
  const CB = window.CB;
  const section = (d, tab) => '#/p/'+encodeURIComponent(d.project)+'/'+tab;
  const last = list => (list || []).slice(-1)[0] || {};
  function opportunities(d, filter) {
    const find = [], round = last(d.snapshots), audit = last(d.audits);
    for (const q of d.questions || []) {
      if (!q.answers || q.recommended) continue;
      find.push({id:'sample/'+q.prompt_id, title:'Review a buyer question', channel:'answers', question:q.question,
        source:'Sample AI answers', observed_on:round.saved_on, observations:q.answers, coverage:'0 recommendations in '+q.answers+' sample answers.',
        suggested_action:'Read the page a buyer would use to answer this question. Check that it gives a specific, accurate answer.',
        manual_alternative:'Compare the question with the current page.', evidence_url:section(d,'questions')});
    }
    for (const site of (d.citation_gap || {}).sites || []) {
      find.push({id:'sample/publisher/'+site.site,title:'Review coverage on '+site.site,channel:'off_page',
        source:'Cited domains',observed_on:round.saved_on,observations:site.answers_for_rivals_without_you,coverage:site.answers_for_rivals_without_you+' answers cited this site and named a competitor without naming you.',
        suggested_action:'Find the article behind the citation and see whether it would help its readers to include your business.',
        manual_alternative:'Review the cited domains in AI answers.',evidence_url:section(d,'answers')});
    }
    for (const check of [...((d.site_changes || {}).new || []), ...((d.site_changes || {}).still_open || [])]) {
      find.push({id:'sample/site/'+check,title:check,channel:'technical',source:'Site audit',observed_on:audit.date,
        coverage:'The latest saved site audit lists this issue.',suggested_action:'Review the issue on the Site page and record what needs to change.',
        manual_alternative:'Open the affected page and check it yourself.',evidence_url:section(d,'site')});
    }
    for (const gap of (d.search_demand || {}).gaps || []) {
      find.push({id:'sample/search/'+gap.query,title:'Review a low-click search',channel:'search',question:gap.query,
        source:'Sample Search Console export',observations:gap.impressions,coverage:CB.num(gap.impressions)+' impressions and '+CB.num(gap.clicks)+' clicks in the export.',
        suggested_action:'Compare the title and opening paragraph with what this searcher wants to know.',
        manual_alternative:'Open the query in your Search Console export.',evidence_url:section(d,'traffic')});
    }
    return find.filter(o => (!filter.channel || o.channel === filter.channel)
      && (!filter.since || (o.observed_on && o.observed_on >= filter.since))
      && ['page','question'].every(key => !filter[key] || String(o[key] || '').toLowerCase().includes(filter[key].toLowerCase())));
  }
  function changes(d, since) {
    const rounds = d.snapshots || [], latest = last(rounds);
    const current = latest.saved_on && (!since || latest.saved_on >= since) ? latest : {};
    const previous = current.snapshot ? last(rounds.slice(0,-1).filter(r=>!since || r.saved_on<=since)) : {};
    const audit = last(d.audits), observed = [];
    if (audit.date && (!since || audit.date >= since) && d.site_changes) {
      for (const key of ['fixed','new']) for (const title of d.site_changes[key] || []) {
        observed.push({title,detail:key === 'fixed' ? 'Passed at the latest site recheck.' : 'Found at the latest site recheck.',observed_on:audit.date,source:'Sample site audit'});
      }
    }
    const interval = previous.saved_on ? (Date.parse(current.saved_on)-Date.parse(previous.saved_on))/86400000 : null;
    return {current_round:current.snapshot,previous_round:previous.snapshot,from_date:previous.saved_on,to_date:current.saved_on,
      interval_days:interval,comparison:interval === null ? 'baseline_needed' : 'round_to_round',
      questions:[],changes:observed,coverage:{engines:current.engines || [],note:'This example includes round totals. Open AI answers to compare the sample engines.'}};
  }
  function prospect(project) {
    const local = project === 'northwind-cafe';
    const to = local ? 'editor@stationguide.example' : 'editor@teamfinance.example';
    return {id:'sample-editor',revision:1,recipientType:'editor',email:to,outcome:'new',
      sourceUrl:local ? 'https://stationguide.example/brunch' : 'https://teamfinance.example/payroll',
      readerFit:local ? 'Visitors planning brunch near the station need menus and opening hours.' : 'Small teams comparing providers need a list of payroll questions to ask.',
      asset:local ? 'A menu and opening hours.' : 'A payroll switching checklist.',
      contactProvenance:'Fictional editorial contact in the sample project.',
      draft:{version:'sample-v1',revision:1,approved:false,to,subject:local ? 'Menu details for your station brunch guide' : 'Checklist for your payroll comparison',
        body:local ? 'Hello, I saw your guide to brunch near the station. Would a current menu and weekday opening hours help your readers plan their visit?\n\nNorthwind Café' :
          'Hello, your payroll comparison covers prices and features. Would a checklist of questions to ask before switching help your readers?\n\nAcme Payroll'}};
  }
  // Only explicitly modelled reads resolve in the sample. Writes and public-page checks require a signed-in project.
  CB.demoWork = function (project, operation, data) {
    const d = window.CB_DEMO.call('get_history',{project});
    if (['onboarding_get','research_get','research_plan'].includes(operation)) {
      const questions=d.questions || [], sites=d.citation_gap?.sites || [], round=last(d.snapshots);
      const rivals=Array.from(new Set(sites.flatMap(row=>row.rivals_named || [])));
      const queries=d.search_demand?.gaps || [];
      if(operation==='onboarding_get'){
        const local=project==='northwind-cafe', term=(queries[0]||{}).query || (local?'brunch near the station':'payroll software');
        const audience=local?'commuters and families':'small businesses', market=local?'United Kingdom':'United States';
        const ideas=[`What is the best ${term} in the ${market}?`,`Which ${term} would you recommend for ${audience}?`,`How do I choose the right ${term}?`,
          ...rivals.slice(0,2).map(r=>`What are the best alternatives to ${r}?`)]
          .filter(p=>!questions.some(q=>q.question===p)).map((prompt,i)=>({prompt,prompt_id:'idea-'+i,type:'consideration',reason:'Built from the sample business profile.'}));
        return {website:d.brand.site,brand:d.brand.name,revision:0,stage:'competitors',
          competitors:rivals.map(name=>({name,selected:true,reason:'Named in fictional comparison answers.'})),
          terms:queries.map(q=>({term:q.query,selected:true,reason:'Appears in the sample search report.'})),
          questions:questions.map(q=>({prompt:q.question,prompt_id:q.prompt_id,type:q.type})),question_ideas:ideas,
          profile:{summary:local?'Neighbourhood café serving brunch and coffee by the station.':'Payroll, HR and time-off software for small teams.',
            audiences:[{name:audience,source:'website',reason:'Named as a customer group on the sample home page.'}],
            markets:[{name:market,source:'project',reason:'Saved project country.'}]}};
      }
      if(operation==='research_plan')return {jobs:[],terms:queries.map(q=>q.query),rivals};
      const ai=questions.flatMap(q=>Object.entries(q.engines || {}).map(([engine,answer])=>({
        term:q.question,engine:engine==='chatgpt'?'ChatGPT':engine,brand:d.brand.name,
        answers:answer.answers,mentions:answer.named,position:null,source:'Fictional sample answers',observed_at:round.saved_on})));
      const keywords=queries.map(q=>({term:q.query,clicks:q.clicks,impressions:q.impressions,source:'Fictional Search Console export'}));
      const competitors=rivals.map(name=>({name,source:'Fictional comparison answers',observed_at:round.saved_on}));
      return {keywords,competitors,ai,pages:[],citations:[],coverage:{keywords:keywords.length,competitors:competitors.length,ai:ai.length,pages:0,citations:0}};
    }
    if (operation === 'project_focus') return CB.focusUI.demo(project,data);
    if (operation === 'seo_plan' && !CB.seoPlan) throw new Error('The plan is still loading.');
    if (operation === 'seo_plan') return CB.seoPlan.demo({...d,project});
    if (operation === 'brief_get') {
      const local = project === 'northwind-cafe';
      return {brief:{revision:1,language:'English',key_pages:[],business_type:local ? 'Café' : 'Payroll software',
        goal:local ? 'Help people near the station find our brunch menu.' : 'Help small teams choose a payroll service.',
        audience:local ? 'People choosing where to eat near the station' : 'Small-business owners comparing payroll providers'}};
    }
    if (operation === 'actions_list') return {actions:(d.todo || []).map((t,i)=>({...t,title:t.step,id:'sample-'+i,revision:0}))};
    if (operation === 'opportunities_list') return {opportunities:opportunities(d,data)};
    if (operation === 'changes_list') return changes(d,data.since);
    if (operation === 'runs_list') return {runs:(d.snapshots || []).slice().reverse().map(r => ({id:'round-'+r.snapshot,
      snapshot:r.snapshot,kind:'saved_round',status:'saved',observed_on:r.saved_on,evidence_url:section(d,'answers')}))};
    if (operation === 'offers_list') return {offer:null};
    if (operation === 'schedule_list') return {schedules:project === 'acme-payroll' ? [{
      schedule_id:'sc1',enabled:true,check_status:'active',scope:'site_only',site:d.brand.site,max_pages:3,
      frequency:'weekly',weekday:0,local_time:'09:00',timezone:'UTC',checks_per_occurrence:1,
      monthly_allowance:4,checks_remaining:2,stop_date:'2027-02-28',planned_next_check:'2027-02-15T09:00:00Z',
      last_occurrence:{scheduled_at:'2027-02-08T09:00:00Z',status:'completed'}
    }] : []};
    if (operation === 'schedule_preview' && !data.include_ai) return {...data,project,scope:'site_only',site:(d.brand || {}).site,
      engines:[],checks_per_occurrence:1,plan_id:'sample',cap_per_occurrence_usd:0,platform_usage:'Sample preview. A real schedule incurs Apify platform usage.'};
    if (operation === 'prospects_list') return {prospects:[prospect(project)],recipientTypes:['customer','editor','partner','creator','directory'],
      outcomes:['new','contacted','declined','replied','opted_out','hard_bounce','complaint','placement_verified'],guidance:{}};
    if (operation === 'digest_get') return {enabled:false,recipients:[],muteUnchanged:true,preview:{whatChanged:'No dated activity in this sample week.',
      needsDecision:'Review open actions in the sample project.',nextCheck:'Choose a date when you set up the project.'},handoff:'Review and share through your own email account.'};
    throw new Error('Sign in with Apify to use this operation. The sample is read-only.');
  };
})();
