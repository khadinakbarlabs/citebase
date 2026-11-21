'use strict';
const scopes={gmail:'https://www.googleapis.com/auth/gmail.send',gsc:'https://www.googleapis.com/auth/webmasters.readonly',ga4:'https://www.googleapis.com/auth/analytics.readonly'};
function siteUrl(site){
 const url=new URL(site.includes('://')?site:'https://'+site);
 if(!['https:','http:'].includes(url.protocol)||url.username||url.password)throw Error('Invalid website');
 return url;
}
function pathOf(url){return url.pathname.replace(/\/+$/,'');}
function ancestor(prefix,site){
 return prefix.origin===site.origin && (pathOf(prefix)===pathOf(site)||site.pathname.startsWith(pathOf(prefix)+'/'));
}
const escapeRegex=value=>Array.from(value,c=>'\\^$.*+?()[]{}|'.includes(c)?'\\'+c:c).join('');
function covers(property,site){
 try{
  const url=siteUrl(site);
  if(property.startsWith('sc-domain:')){
   const domain=property.slice(10).toLowerCase();
   return url.hostname===domain||url.hostname.endsWith('.'+domain);
  }
  const prefix=new URL(property);
  return ancestor(prefix,url);
 }catch{return false;}
}
// Shown only to the signed-in owner of the grant, so an empty result can explain itself.
const MAX_OTHERS=5;
function website(site){const url=siteUrl(site);return url.host+pathOf(url);}
async function scan(service,api,site){
 if(service==='gsc'){
  const data=await api('https://www.googleapis.com/webmasters/v3/sites');
  const entries=data.siteEntry||[];
  const matching=entries.filter(p=>covers(p.siteUrl,site));
  return {website:website(site),checked:entries.length,
   choices:matching.filter(p=>p.permissionLevel!=='siteUnverifiedUser').map(p=>({id:p.siteUrl,label:p.siteUrl})),
   unverified:matching.filter(p=>p.permissionLevel==='siteUnverifiedUser').map(p=>p.siteUrl).slice(0,MAX_OTHERS),
   others:entries.filter(p=>!covers(p.siteUrl,site)&&p.permissionLevel!=='siteUnverifiedUser').map(p=>p.siteUrl).slice(0,MAX_OTHERS)};
 }
 const others=new Set();
 const list=[]; let cursor='', inspected=0, pages=0;
 do{
  if(++pages>100)throw Error('Account list too large');
  const data=await api('https://analyticsadmin.googleapis.com/v1beta/accountSummaries?'+new URLSearchParams({pageSize:'200',pageToken:cursor}));
  for(const account of data.accountSummaries||[])for(const p of account.propertySummaries||[]){
   if(++inspected>200)throw Error('Too many accessible properties');
   if(!/^properties\/\d+$/.test(p.property))continue;
   const streams=[];
   let page='',streamPages=0;
   do{
    if(++streamPages>100)throw Error('Stream list too large');
    const reply=await api('https://analyticsadmin.googleapis.com/v1beta/'+p.property+'/dataStreams?'+new URLSearchParams({pageSize:'200',pageToken:page}));
    for(const stream of reply.dataStreams||[]){
     const parts=(stream.name||'').split('/dataStreams/');
     if(parts[0]!==p.property||!/^\d+$/.test(parts[1])||stream.type!=='WEB_DATA_STREAM')continue;
     const uri=stream.webStreamData?.defaultUri;
     if(uri && covers(uri,site))streams.push(parts[1]);
     else if(uri && others.size<MAX_OTHERS)others.add(uri);
    }
    page=reply.nextPageToken;
   }while(page);
   if(streams.length)list.push({id:p.property,label:p.displayName+' ('+p.property+')',streams});
  }
  cursor=data.nextPageToken;
  if(cursor && list.length>5000)throw Error('Property list too large');
 }while(cursor);
 return {website:website(site),checked:inspected,choices:list,unverified:[],others:[...others]};
}
async function properties(service,api,site){return (await scan(service,api,site)).choices;}
async function report(service,id,api,site,streams){
 const url=siteUrl(site),path=escapeRegex(pathOf(url));
 const day=offset=>new Date(Date.now()-offset*86400000).toISOString().slice(0,10);
 const startDate=day(30),endDate=day(3);
 if(service==='gsc'){
  const data=await api('https://www.googleapis.com/webmasters/v3/sites/'+encodeURIComponent(id)+'/searchAnalytics/query',{startDate,endDate,dimensions:['query'],dimensionFilterGroups:[{filters:[{dimension:'page',operator:'includingRegex',expression:'^'+escapeRegex(url.origin)+path+'(/|[?]|$)'}]}],rowLimit:1000,dataState:'final'});
  const rows=data.rows||[];
  const observations=rows.map(r=>({term:r.keys[0],clicks:r.clicks,impressions:r.impressions,position:r.position}));
  return {startDate,endDate,count:rows.length,observations,measure:'Up to 1,000 Google Search queries by clicks'};
 }
 const host=url.hostname;
 if(!streams?.length||url.port)throw Error('Cannot establish exact Analytics stream');
 const filters=[{fieldName:'hostName',stringFilter:{matchType:'EXACT',value:host,caseSensitive:false}},
  {fieldName:'pagePath',stringFilter:{matchType:'FULL_REGEXP',value:'^'+path+'(/.*|$)',caseSensitive:true}},
  {fieldName:'streamId',inListFilter:{values:streams}}];
 const data=await api('https://analyticsdata.googleapis.com/v1beta/'+id+':runReport',{dateRanges:[{startDate,endDate}],dimensions:[{name:'sessionSource'}],metrics:[{name:'sessions'}],dimensionFilter:{andGroup:{expressions:filters.map(filter=>({filter}))}},limit:'5000'});
 const rows=data.rows||[];
 if(rows.length!==(data.rowCount||0))throw Error('Partial report');
 const observations=rows.map(r=>({source:r.dimensionValues[0].value,sessions:Number(r.metricValues[0].value)}));
 return {startDate,endDate,count:rows.length,observations,measure:'Sessions by source on '+host};
}
module.exports={scopes,covers,scan,properties,report};
