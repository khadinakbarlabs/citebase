(function(){
 'use strict';
 const CB=window.CB,h=CB.h;
 const list=items=>items.join(', ');
 // Product logo placed before an element's text (CSS order), skipped where SVG helpers are unavailable.
 const withLogo=(el,name,cls)=>{if(CB.s)el.append(CB.s('svg',{class:cls||'g-logo','aria-hidden':'true',focusable:'false'},CB.s('use',{href:'../assets/icons.svg#'+name})));return el;};
 const LOGOS={gsc:'logo-gsc',ga4:'logo-ga'};
 // Plain-language explanation when no Google property covers the project's website.
 function emptyHelp(service,found){
  const site=found.website||'this project’s website',url='https://'+(found.website||'your-site')+'/';
  const n=Number(found.checked)||0,others=found.others||[],unverified=found.unverified||[];
  const lines=[];
  if(service==='gsc'){
   lines.push(n?'Citebase checked '+n+' Search Console '+(n===1?'property':'properties')+' this Google account can open. None of them covers '+site+'.'
    :'This Google account cannot open any Search Console properties, so nothing covers '+site+'.');
   if(unverified.length)lines.push(list(unverified)+' is added to this Google account but not verified yet. Finish verification in Search Console, then choose Check again.');
   else lines.push('What you need: in Search Console, add a URL-prefix property for '+url+' and verify it (an HTML tag or file works on any host), or ask the property owner to add this Google account as a user.');
   if(others.length)lines.push('Properties this account can open: '+list(others)+'. If one of them is the same site under another address, update the website in Setup first.');
  }else{
   lines.push(n?'Citebase checked '+n+' Google Analytics '+(n===1?'property':'properties')+' this Google account can open. None has a web data stream for '+site+'.'
    :'This Google account cannot open any Google Analytics properties, so no web data stream covers '+site+'.');
   lines.push('What you need: in Google Analytics, open Admin, then Data streams, and add a web stream for '+url+', or ask the property owner to give this Google account Viewer access to the property that already measures it.');
   if(others.length)lines.push('Web streams this account can see: '+list(others)+'. If one of them is the same site under another address, update the website in Setup first.');
  }
  lines.push('Signed in with a different Google account? Choose Reconnect.');
  return lines;
 }
 function panel(project){
  const box=h('section',{class:'card'},withLogo(h('h3',{class:'g-title',text:'Google reporting'}),'logo-google'));
  if(CB.demo){box.append(h('p',{text:'Sign in to connect your own Google properties.'}));return box;}
  for(const [service,label] of [['gsc','Search Console'],['ga4','Google Analytics 4']]){
   const section=h('div',{class:'google-service'}),status=h('p',{'aria-live':'polite'}),help=h('div',{class:'google-help'}),actions=h('div',{class:'actions'});
   section.append(withLogo(h('h4',{text:label}),LOGOS[service]),status,help,actions);box.append(section);
   async function call(action,extra){
    const response=await fetch('/api/google/',{method:'POST',credentials:'same-origin',headers:{'X-Citebase-Session':'1',Authorization:'Bearer '+CB.token,'Content-Type':'application/json'},body:JSON.stringify({action,project,service,...extra})});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'Google reporting is unavailable.');
    return result;
   }
   function button(text,fn,mark){
    const b=h('button',{type:'button',class:mark==='primary'?'btn':'btn ghost',text});
    if(mark)withLogo(b,mark==='primary'?LOGOS[service]:mark,'g-logo sm');
    b.onclick=async()=>{actions.inert=true;try{await fn();}catch(e){status.textContent=e.message;}finally{actions.inert=false;}};
    actions.append(b);
   }
   async function load(){
    const state=await call('status');actions.replaceChildren();help.replaceChildren();
    status.textContent=state.configured?(state.property|| (state.connected?'Choose a property.':'Connect to import a read-only report.')):state.error;
    if(state.last_import)status.textContent+=' · Last import covered '+state.last_import.start_date+' to '+state.last_import.end_date+' ('+state.last_import.count+' rows).';
    if(!state.configured)return;
    button(state.connected?'Reconnect':'Connect '+label,async()=>{location.assign((await call('connect')).url);},state.connected?'logo-google':'primary');
    if(!state.connected)return;
    async function choose(){
     const found=await call('properties'),{choices}=found;actions.replaceChildren();help.replaceChildren();
     if(!choices.length){
      status.textContent='No '+label+' property matches '+(found.website||'this project’s website')+' yet.';
      help.append(...emptyHelp(service,found).map(text=>h('p',{text})));
      button('Check again',choose);button('Reconnect',async()=>{location.assign((await call('connect')).url);});button('Back',load);
      return;
     }
     status.textContent=(choices.length===1?'One property covers ':choices.length+' properties cover ')+found.website+'. Choose the one to import from.';
     const select=h('select',{'aria-label':label+' property'});
     choices.forEach(p=>select.append(h('option',{value:p.id,text:p.label})));
     actions.append(select);button('Use selected property',async()=>{await call('select',{property:select.value});await load();});
    }
    button('Choose property',choose);
    if(state.property)button('Import 28 days',async()=>{
     const r=await call('sync');CB.refresh();
     status.textContent=r.measure+' · '+r.startDate+' to '+r.endDate+' · '+r.count+' rows'+(r.saved?' imported.':'. No data to import.');
    });
    button('Disconnect from project',async()=>{await call('disconnect');await load();status.textContent='Disconnected from this project. You can revoke Google’s permission in your Google Account.';});
   }
   load().catch(e=>{status.textContent=e.message;});
  }
  return box;
 }
 async function mail(project,action,draft){
  const response=await fetch('/api/google/',{method:'POST',credentials:'same-origin',headers:{'X-Citebase-Session':'1',Authorization:'Bearer '+CB.token,'Content-Type':'application/json'},body:JSON.stringify({project,service:'gmail',action,draft})});
  const data=await response.json();
  if(!response.ok)throw Error(data.error||'Gmail is unavailable.');
  return data;
 }
 CB.googleUI={panel,emptyHelp,gmail:{status:project=>mail(project,'status'),disconnect:project=>mail(project,'disconnect'),connect:async (project,active)=>{const account=CB.sessionId(),result=await mail(project,'connect');if(account===CB.sessionId()&&(!active||active()))location.assign(result.url);},send:(project,draft)=>mail(project,'send',draft)}};
})();
