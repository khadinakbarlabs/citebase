const {test}=require('node:test');
const assert=require('node:assert/strict');
const {covers,report}=require('../../site/api/_lib/google-reporting');
test('domain and prefix ownership exclude sibling sites and paths',()=>{
 assert.equal(covers('sc-domain:example.com','https://a.example.com/'),true);
 assert.equal(covers('sc-domain:example.com','https://badexample.com/'),false);
 assert.equal(covers('https://example.com/a/','https://example.com/b/'),false);
});
test('partial Analytics totals never become saved history',async()=>{
 await assert.rejects(report('ga4','properties/12',async()=>({rows:[],rowCount:10}),'https://example.com/',['123']));
});
test('query filters isolate the exact authority and path',async()=>{
 let query;
 const api=async(_,payload)=>{query=payload;return {rows:[]};};
 const site='https://app.example.test/project';
 await report('gsc','sc-domain:example.test',api,site);
 const scope=new RegExp(query.dimensionFilterGroups[0].filters[0].expression);
 for(const url of [site,site+'?q=1',site+'/robots.txt'])assert.ok(scope.test(url));
 for(const url of [site+'-two',site.replace('app.','www.'),site.replace('https:','http:')])assert.ok(!scope.test(url));
 await report('ga4','properties/12',api,site,['123']);
 const filters=query.dimensionFilter.andGroup.expressions.map(x=>x.filter);
 assert.equal(filters[0].stringFilter.value,'app.example.test');
 assert.ok(new RegExp(filters[1].stringFilter.value).test('/project/robots.txt'));
 assert.ok(!new RegExp(filters[1].stringFilter.value).test('/project-two'));
 assert.deepEqual(filters[2].inListFilter.values,['123']);
});
test('only a matching web stream qualifies its property',async()=>{
 const {properties}=require('../../site/api/_lib/google-reporting');
 const api=async url=>url.includes('accountSummaries')?{accountSummaries:[{propertySummaries:[{property:'properties/12',displayName:'A'},{property:'properties/13',displayName:'B'}]}]}:{dataStreams:[{name:url.includes('/12/')?'properties/12/dataStreams/123':'properties/13/dataStreams/456',type:'WEB_DATA_STREAM',webStreamData:{defaultUri:url.includes('/12/')?'https://x.test':'https://elsewhere.test'}}]};
 const result=await properties('ga4',api,'https://x.test/project');
 assert.deepEqual(result.map(x=>x.id),['properties/12']);
});
test('an empty Search Console scan names the website and what the account can open',async()=>{
 const {scan}=require('../../site/api/_lib/google-reporting');
 const api=async()=>({siteEntry:[
  {siteUrl:'sc-domain:featuredforge.com',permissionLevel:'siteOwner'},
  {siteUrl:'https://featuredforge.vercel.app/',permissionLevel:'siteUnverifiedUser'},
  {siteUrl:'https://other.test/',permissionLevel:'siteUnverifiedUser'}]});
 const found=await scan('gsc',api,'https://featuredforge.vercel.app/');
 assert.equal(found.website,'featuredforge.vercel.app');
 assert.equal(found.checked,3);
 assert.deepEqual(found.choices,[]);
 assert.deepEqual(found.unverified,['https://featuredforge.vercel.app/']);
 assert.deepEqual(found.others,['sc-domain:featuredforge.com'],'unverified sites for other addresses stay hidden');
});
test('an Analytics scan lists other web streams only when none covers the website',async()=>{
 const {scan}=require('../../site/api/_lib/google-reporting');
 const api=async url=>url.includes('accountSummaries')?{accountSummaries:[{propertySummaries:[{property:'properties/12',displayName:'A'}]}]}
  :{dataStreams:[{name:'properties/12/dataStreams/9',type:'WEB_DATA_STREAM',webStreamData:{defaultUri:'https://featuredforge.com'}}]};
 const empty=await scan('ga4',api,'featuredforge.vercel.app');
 assert.deepEqual({...empty,choices:empty.choices.length},{website:'featuredforge.vercel.app',checked:1,choices:0,unverified:[],others:['https://featuredforge.com']});
 const match=await scan('ga4',api,'https://featuredforge.com/');
 assert.deepEqual(match.choices.map(c=>c.id),['properties/12']);
 assert.deepEqual(match.others,[]);
});
test('a Search Console sync adds daily, page, country, device and previous-period lists',async()=>{
 const asked=[];
 const api=async(_,payload)=>{
  asked.push(payload);
  const dimension=payload.dimensions[0];
  const key={query:'crm tool',date:payload.endDate,page:'https://x.test/blog',country:'usa',device:'MOBILE'}[dimension];
  const rows=dimension==='date'?[{keys:[payload.endDate],clicks:10,impressions:200,position:4.256},{keys:[payload.startDate],clicks:5,impressions:100,position:7}]
   :Array.from({length:dimension==='device'?9:2000},(_,i)=>({keys:[key+i],clicks:3,impressions:30,position:2.5}));
  return {rows};
 };
 const result=await report('gsc','sc-domain:x.test',api,'https://x.test/');
 assert.equal(asked.length,8,'5 lists now and 3 for the previous 28 days');
 assert.ok(asked.every(p=>p.dimensionFilterGroups[0].filters[0].expression===asked[0].dimensionFilterGroups[0].filters[0].expression));
 assert.equal(result.observations.length,1000);
 assert.equal(result.count,1000);
 const {extra}=result;
 assert.deepEqual(extra.daily.map(d=>d.date),[result.startDate,result.endDate],'days sorted oldest first');
 assert.deepEqual(extra.totals,{clicks:15,impressions:300,ctr:0.05,position:5.17});
 assert.equal(extra.pages.length,100);
 assert.equal(extra.countries.length,30);
 assert.equal(extra.devices.length,5);
 assert.deepEqual(Object.keys(extra.pages[0]),['page','clicks','impressions','position']);
 assert.equal(extra.previous.rows.length,1000);
 assert.equal(extra.previous.pages.length,100);
 assert.ok(extra.previous.end_date<result.startDate);
 const span=(a,b)=>(Date.parse(b)-Date.parse(a))/86400000;
 assert.equal(span(extra.previous.start_date,extra.previous.end_date),span(result.startDate,result.endDate),'equal length');
 assert.equal(span(extra.previous.end_date,result.startDate),1,'no gap and no overlap');
});
