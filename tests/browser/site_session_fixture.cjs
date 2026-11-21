/* A local site and fake token issuer for the persistent-browser regression. No upstream requests. */
'use strict';
const http = require('node:http');
const https = require('node:https');
const path = require('node:path');
const {readFileSync} = require('node:fs');
const {randomBytes} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const dir = process.argv[2];
let handle, relay, base;
let consents = 0, starts = 0;
const directories = new Map();
const billingStores = new Map();
function storageReply(url,init) {
  const owner = /^Bearer fixture-access-(\d+)$/.exec(init.headers.Authorization || '')?.[1];
  if (!owner) return Response.json({}, {status:401});
  const name='citebase-billing-balances', id='MockStore000'+owner, username='fixture-owner-'+owner;
  const path = new URL(url).pathname.slice(4);
  const data = value => Response.json({data:value});
  const missing = () => Response.json({}, {status:404});
  if (path==='users/me') return data({id:owner,username});
  if (!billingStores.has(owner)) billingStores.set(owner,{store:null,records:new Map()});
  const bucket=billingStores.get(owner);
  if (path==='key-value-stores/'+username+'~'+name) return bucket.store?.name ? data(bucket.store) : missing();
  if (path==='key-value-stores' && init.method==='POST') {
    bucket.store={id,userId:owner};
    return data(bucket.store);
  }
  if (path==='key-value-stores/'+id && init.method==='PUT') {
    Object.assign(bucket.store,JSON.parse(init.body));
    return data(bucket.store);
  }
  if (bucket.store?.generalAccess!=='RESTRICTED') return missing();
  if (path==='key-value-stores/'+id+'/keys') return data({items:[...bucket.records.keys()].sort().slice(0,1).map(key=>({key}))});
  const key = path.split('key-value-stores/'+id+'/records/')[1];
  if (key && init.method==='PUT') {
    bucket.records.set(key,JSON.parse(init.body));
    return new Response(null,{status:201});
  }
  return key && bucket.records.has(key) ? Response.json(bucket.records.get(key)) : missing();
}
function actorReply(init) {
  const applied = init.headers['X-Citebase-Authorization'];
  if (!/^Bearer fixture-access-\d+$/.test(applied) || applied !== init.headers['X-Apify-Authorization']) {
    return Response.json({error:'unauthorized'}, {status:401});
  }
  if (!directories.has(applied)) directories.set(applied, new Map());
  const projects = directories.get(applied), {tool, arguments:args} = JSON.parse(init.body);
  let result;
  if (tool === 'get_history') {
    result = args.project ? projects.get(args.project) || {} : {projects:[...projects.values()]};
  } else if (tool === 'save_results' && args.create_only) {
    if (projects.has(args.project)) return Response.json({ok:false,error:'Project already exists'}, {status:400});
    projects.set(args.project, {project:args.project, brand:args.brand.name, site:args.brand.site, rounds:0, due:[]});
    result = {created:true};
  } else if (tool === 'audit_site' && projects.has(args.project)) {
    Object.assign(projects.get(args.project), {last_site_check:'2026-11-20', health_score:78});
    result = {status:'complete',saved:true,health_score:78,pages_checked:1,problems:[],counts:{fail:0,warn:0,pass:2}};
  } else if (tool === 'project_work') result = {result:{}};
  else return Response.json({ok:false,error:'Unsupported fixture operation'}, {status:400});
  return Response.json({ok:true, tool, result});
}
process.env.CITEBASE_SESSION_KEY = randomBytes(32).toString('base64');
global.fetch = async (url, init) => {
  if (url.startsWith('https://api.apify.com/v2/')) return storageReply(url,init);
  if (url === 'https://khadinakbar--citebase.apify.actor/run' && init.method === 'POST') return actorReply(init);
  if (url !== 'https://console-backend.apify.com/oauth/apps/token') throw Error('Unexpected outbound request');
  const body = new URLSearchParams(init.body);
  const login = /^local-consent-(\d+)$/.exec(body.get('code'));
  if (body.get('grant_type') !== 'authorization_code' || !body.get('code_verifier')
      || !login || Number(login[1]) !== consents || body.get('redirect_uri') !== base + '/app/') {
    return Response.json({error:'invalid_grant'}, {status:400});
  }
  return Response.json({access_token:'fixture-access-' + login[1], refresh_token:'fixture-refresh-' + login[1], expires_in:3600});
};
const mime = {'.js':'text/javascript', '.css':'text/css', '.html':'text/html', '.json':'application/json', '.svg':'image/svg+xml'};
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, base);
  if (url.pathname === '/api/actor/') return relay(req, res);
  if (url.pathname === '/api/session/') {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    req.body = Buffer.concat(chunks).toString();
    return handle(req, res);
  }
  if (url.pathname === '/fixture-count') return res.end(JSON.stringify({consents, starts}));
  const file = path.resolve(dir, '.' + url.pathname + (url.pathname.endsWith('/') ? 'index.html' : ''));
  if (!file.startsWith(dir + path.sep) || file.startsWith(path.join(dir,'api') + path.sep) || path.extname(file) === '.pem') {
    res.writeHead(404); return res.end();
  }
  try { const data = readFileSync(file); res.writeHead(200, {'Content-Type':mime[path.extname(file)] || 'application/octet-stream'}); res.end(data); }
  catch { res.writeHead(404); res.end(); }
});
const certificate = path.join(dir, 'fixture-cert.pem'), privateKey = path.join(dir, 'fixture-key.pem');
execFileSync('openssl', ['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=console.apify.com',
  '-out', certificate, '-keyout', privateKey], {stdio:'ignore'});
const apify = https.createServer({cert:readFileSync(certificate), key:readFileSync(privateKey)}, (req, res) => {
  const url = new URL(req.url, 'https://' + req.headers.host);
  if (url.hostname === 'console.apify.com' && url.pathname === '/authorize/oauth') {
    consents++;
    const back = new URL('/app/', base);
    back.search = new URLSearchParams({code:'local-consent-' + consents, state:url.searchParams.get('state')});
    res.writeHead(200, {'Content-Type':'text/html', 'Referrer-Policy':'no-referrer'});
    return res.end('<a href="' + back.href + '">Allow fixture</a>');
  }
  const paid = url.pathname === '/v2/acts/fixture~offline/runs';
  if (url.hostname === 'api.apify.com' && (paid || ['/v2/users/me', '/v2/users/me/limits', '/v2/users/me/usage/monthly', '/v2/actor-runs'].includes(url.pathname))) {
    res.setHeader('Access-Control-Allow-Origin', base);
    res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
    const owner = /^Bearer fixture-access-(\d+)$/.exec(req.headers.authorization || '');
    if (paid && req.method === 'POST') starts++;
    res.writeHead(owner ? 200 : 401, {'Content-Type':'application/json'});
    const data = url.pathname === '/v2/users/me' ? {username:'fixture-owner-' + owner?.[1]}
      : url.pathname === '/v2/actor-runs' ? {items:[],total:0} : {};
    return res.end(JSON.stringify({data}));
  }
  res.writeHead(404); res.end();
});
apify.listen(0, '127.0.0.1', () => server.listen(0, '127.0.0.1', () => {
  base = 'http://127.0.0.1:' + server.address().port;
  execFileSync(process.env.PYTHON || 'python3', ['scripts/build_site.py', '--site', base, '--out', dir],
    {cwd:path.resolve(__dirname, '../..')});
  handle = require(path.join(dir,'api/session.js'));
  relay = require(path.join(dir,'api/actor.js'));
  process.stdout.write(JSON.stringify([base, apify.address().port]) + '\n');
}));
