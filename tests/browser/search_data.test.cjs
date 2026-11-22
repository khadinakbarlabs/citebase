const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {runInNewContext}=require('node:vm');
const {join}=require('node:path');

function load(){
 const CB={};
 runInNewContext(readFileSync(join(__dirname,'../../site/app/search-data.js'),'utf8'),{window:{CB},URL,Intl,Date,Math,Object,Array,String,isFinite});
 return CB.searchData;
}
const D=load();
const plain=x=>JSON.parse(JSON.stringify(x));
const day=i=>new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10);
function days(from,count,clicks){return Array.from({length:count},(_,i)=>({date:day(from+i),clicks,impressions:clicks*20,position:5}));}
function record(extra){
 return {start_date:day(28),end_date:day(55),provenance:'google_sync',
  rows:[{term:'acme crm',clicks:30,impressions:100,position:1.2},{term:'crm for teams',clicks:2,impressions:400,position:8},
   {term:'best crm',clicks:1,impressions:900,position:12},{term:'cheap crm',clicks:0,impressions:30,position:25}],
  ...extra};
}
const full=()=>record({daily:days(28,28,10),totals:{clicks:280,impressions:5600,ctr:0.05,position:5},
 pages:[{page:'https://acme.test/blog',clicks:150,impressions:900,position:4},{page:'https://acme.test/',clicks:130,impressions:800,position:2}],
 countries:[{country:'usa',clicks:200,impressions:3000,position:4},{country:'gbr',clicks:80,impressions:2000,position:6}],
 devices:[{device:'MOBILE',clicks:210,impressions:4000,position:5},{device:'DESKTOP',clicks:70,impressions:1600,position:4}],
 previous:{start_date:day(0),end_date:day(27),daily:days(0,28,12),totals:{clicks:340,impressions:6800,ctr:0.05,position:5},
  rows:[{term:'crm for teams',clicks:1,impressions:300,position:14},{term:'best crm',clicks:3,impressions:800,position:9}],
  pages:[{page:'https://acme.test/blog',clicks:210,impressions:1000,position:3},{page:'https://acme.test/',clicks:130,impressions:800,position:2}]}});
const brand={name:'Acme',domain:'acme.test'};

test('a full sync says what changed, where from, and only what the numbers show',()=>{
 const says=D.insights(D.prepare(full(),brand)).map(i=>i.tone+': '+i.text);
 assert.equal(says[0],'bad: Clicks down 18% vs the previous 28 days (340 → 280), mostly from /blog.');
 assert.equal(says[1],'bad: Google showed your site 18% less often (6,800 → 5,600 impressions).');
 assert.ok(says.includes('good: 1 search moved into the top 10: “crm for teams”.'),says.join('\n'));
 assert.ok(says.includes('bad: 1 search fell out of the top 10: “best crm”.'),says.join('\n'));
 assert.ok(says.some(s=>s.startsWith('info: 2 searches show your site on page one or two but rarely get a click, led by “best crm”')),says.join('\n'));
 assert.ok(says.includes('info: 91% of search clicks come from people who searched your name. Most visitors already knew you before searching.'),says.join('\n'));
 assert.equal(says.length,6,'capped at six sentences');
});

test('an older query-only record makes no comparison or trend claims',()=>{
 const model=D.prepare(record({}),brand);
 assert.deepEqual(plain(model.daily),[]);
 assert.equal(model.previous,null);
 assert.deepEqual(plain(D.ranges(model)),[]);
 assert.equal(model.totals.clicks,33,'totals fall back to the query rows');
 const says=D.insights(model).map(i=>i.text).join('\n');
 assert.doesNotMatch(says,/previous|top 10|moved|fell|mostly from|phones|Most clicks come from/);
 assert.match(says,/searched your name/);
});

test('devices and countries are named only when one clearly leads',()=>{
 const r=full();r.rows=r.rows.map(x=>({...x,clicks:0}));r.previous=null;
 const says=D.insights(D.prepare(r,brand)).map(i=>i.text);
 assert.deepEqual(plain(says.slice(-2)),['75% of clicks come from phones.','Most clicks come from United States (71%).']);
 r.devices=[{device:'MOBILE',clicks:50},{device:'DESKTOP',clicks:50}];
 assert.ok(!D.insights(D.prepare(r,brand)).some(i=>/phones|computers/.test(i.text)));
});

test('no page is blamed when none explains 40% of the change, or when a full top list hides it',()=>{
 const r=full();
 r.pages=[{page:'https://acme.test/a',clicks:190},{page:'https://acme.test/b',clicks:90}];
 r.previous.pages=[{page:'https://acme.test/a',clicks:210},{page:'https://acme.test/b',clicks:110},{page:'https://acme.test/c',clicks:20}];
 assert.doesNotMatch(D.insights(D.prepare(r,brand))[0].text,/mostly from/,'each page lost 20 of 60 clicks');
 const missing=full();
 missing.pages=Array.from({length:100},(_,i)=>({page:'https://acme.test/p'+i,clicks:1,impressions:10,position:9}));
 assert.doesNotMatch(D.insights(D.prepare(missing,brand))[0].text,/mostly from \/blog/,'a page absent from a full top-100 list is unknown, not zero');
});

test('small changes and a start from zero are worded plainly',()=>{
 const steady=full();steady.previous.totals={clicks:275,impressions:5600};
 assert.equal(D.insights(D.prepare(steady,brand))[0].text,'Clicks held steady: 280, against 275 in the previous 28 days.');
 const fresh=full();fresh.previous.totals={clicks:0,impressions:0};
 assert.equal(D.insights(D.prepare(fresh,brand))[0].text,'Clicks went from 0 to 280 compared with the previous 28 days.');
});

test('the 7-day range compares with the 7 days before it and fills missing days with zero',()=>{
 const r=full();
 r.daily=r.daily.filter(d=>d.date!==day(50));
 const model=D.prepare(r,brand);
 assert.equal(model.daily.length,28);
 assert.deepEqual(plain(model.daily.find(d=>d.date===day(50))),{date:day(50),clicks:0,impressions:0,position:null});
 assert.deepEqual(plain(D.ranges(model)),[7,28]);
 const week=D.range(model,7);
 assert.equal(week.daily.length,7);
 assert.equal(week.totals.clicks,60);
 assert.equal(week.prevTotals.clicks,70);
 const month=D.range(model,28);
 assert.equal(month.totals.clicks,280);
 assert.equal(month.prevTotals.clicks,340);
});

test('position bands, brand words and country names',()=>{
 assert.deepEqual(plain(D.bands(full().rows).map(b=>[b.key,b.count])),[['top3',1],['top10',1],['top20',1],['rest',1]]);
 assert.deepEqual(plain(D.brandTerms({name:'Text Humanizer Pro',domain:'texthumanizer.pro'})),['text humanizer pro','texthumanizer','texthumanizerpro']);
 const terms=D.brandTerms({name:'Text Humanizer Pro',site:'https://texthumanizer.pro/'});
 assert.equal(D.isBranded('texthumanizer.pro review',terms),true);
 assert.equal(D.isBranded('Text Humanizer Pro free',terms),true);
 assert.equal(D.isBranded('text humanizer',terms),false,'a generic phrase is not the brand');
 assert.equal(D.countryName('usa'),'United States');
 assert.equal(D.countryName('zzz'),'Unknown region');
 assert.equal(D.countryName('xyz'),'XYZ');
 assert.equal(D.pathOf('https://acme.test/blog?a=1'),'/blog?a=1');
});

test('clicks Google does not list are counted so the gap can be explained',()=>{
 const gap=plain(D.hiddenClicks(D.prepare(full(),brand)));
 assert.deepEqual(gap,{all:280,listed:33,hidden:247,capped:false});
 assert.equal(D.hiddenClicks(D.prepare(record({totals:{clicks:33,impressions:1430}}),brand)),null);
 assert.equal(D.hiddenClicks(D.prepare(record({}),brand)),null);
 const many=Array.from({length:1000},(_,i)=>({term:'q'+i,clicks:1,impressions:10,position:9}));
 assert.equal(D.hiddenClicks(D.prepare(record({rows:many,totals:{clicks:1200,impressions:20000}}),brand)).capped,true);
});
