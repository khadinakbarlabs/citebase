const test = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const {join} = require('node:path');

function element(tag, attributes, ...children) {
  return {tag, ...attributes, children,
    replaceChildren(...nodes) { this.children = nodes; },
    append(...nodes) { this.children.push(...nodes); },
    addEventListener() {}, showModal() { this.open=true; this.isConnected=true; }
  };
}
function nodes(root) { return [root,...root.children.flatMap(nodes)]; }
async function setup(send) {
  const body = element('body'), calls = [];
  const draft = {approved:true,to:'editor@example.org',subject:'Source',body:'Exact body',version:'abc'};
  const CB = {sessionId:()=>1,h:element, safeUrl:u=>u, work:async (_p,op) => op === 'outreach_status' ? {status:'unclaimed'} : draft,
    googleUI:{gmail:{status:async () => ({configured:true,connected:true}),
      send:async (project, message) => { calls.push([project,JSON.parse(JSON.stringify(message))]);return send(); }}}};
  runInNewContext(readFileSync(join(__dirname,'../site/app/citation-outreach.js'),'utf8'),{window:{CB},document:{body}});
  CB.citationOutreach.review('example',{sourceUrl:'https://example.org/article',readerFit:'Question',id:'pid',draft});
  await new Promise(resolve=>setImmediate(resolve));
  return {body,calls,draft,CB};
}

test('approved preview waits for explicit exact-address click, then shows provider ID', async () => {
  const {body,calls,draft} = await setup(() => ({status:'provider_accepted',messageId:'gmail001',receiptSaved:false}));
  assert.equal(calls.length,0);
  await nodes(body).find(n=>n.text==='Send this email to '+draft.to).onclick();
  assert.deepEqual(calls,[['example',{prospectId:'pid',version:'abc',to:draft.to,subject:'Source',body:'Exact body',confirm:true}]]);
  assert(nodes(body).some(n=>n.text?.includes('gmail001')));
  assert(!nodes(body).some(n=>n.text?.startsWith('Send this email')));
});

test('ambiguous delivery exposes reconciliation only', async () => {
  const {body,calls,draft} = await setup(()=>{throw Error('Connection interrupted');});
  await nodes(body).find(n=>n.text==='Send this email to '+draft.to).onclick();
  const check = nodes(body).find(n=>n.text==='Check handoff status');
  await check.onclick();
  assert.equal(calls.length,1);
  assert(!nodes(body).some(n=>n.text?.startsWith('Send this email') || n.text==='Review in Gmail compose'));
});

test('cross-tab session change invalidates detached Gmail controls and deferred callbacks', async () => {
  let resolveClaim;
  const {body,calls,CB} = await setup(()=>{throw Error('Unexpected send');});
  CB.work = async () => new Promise(resolve => {resolveClaim=resolve;});
  const dialog = body.children.find(n=>n.tag==='dialog' && n.class.split(' ').includes('dlg'));
  assert(dialog);
  const send = nodes(dialog).find(n=>n.text?.startsWith('Send this email'));
  const pending = nodes(dialog).find(n=>n.text==='Review in Gmail compose').onclick();
  // The shared signedOut handler removes every dialog.dlg after a storage event.
  CB.sessionId=()=>2;
  dialog.open=false; dialog.isConnected=false; body.replaceChildren();
  resolveClaim({to:'old@example.org',subject:'old',body:'private'});
  await pending;
  await send.onclick();
  assert.equal(calls.length,0);
  assert.equal(body.children.length,0);
});
