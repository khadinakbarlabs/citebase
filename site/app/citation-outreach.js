/* A cited article, one credited recipient and one reviewed email per handoff. */
(function () {
  'use strict';
  const CB = window.CB, h = CB.h;
  CB.citationOutreach = {open, review:(project,p) => open(project,{url:p.sourceUrl,term:p.readerFit},p)};
  function open(project, citation, saved) {
    const {url, term} = citation;
    const account = CB.sessionId();
    const dialog = h('dialog', {class:'dlg card'}), main = h('div'), status = h('p', {role:'status'});
    const active = () => account === CB.sessionId() && dialog.isConnected && dialog.open;
    async function guarded(fn) {
      if (!active()) throw Error('Session closed.');
      const result = await fn();
      if (!active()) throw Error('Session closed.');
      return result;
    }
    const call = (operation, data) => guarded(() => CB.work(project, operation, data));
    function action(label, fn) {
      const b = h('button', {type:'button', class:'btn small', text:label, onclick:async () => {
        if (!active()) return;
        b.disabled = true;
        try { status.textContent = ''; await fn(); }
        catch (err) { status.textContent = err.message || 'The request failed.'; }
        finally { b.disabled = false; }
      }});
      return b;
    }
    const field = (label, node) => h('label', {class:'field'}, h('span',{text:label}), node);
    const source = link => h('a', {href:CB.safeUrl(link), rel:'noopener noreferrer',target:'_blank',text:link});
    dialog.append(h('h3',{text:'Contact the cited publisher'}), h('p',{text:term}), source(url), main, status,
      action('Close', () => dialog.close()));
    document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove(), {once:true});
    dialog.showModal();
    async function reviewApproved(p, draft) {
      const selector = {prospectId:p.id,version:draft.version};
      const preview = h('section',{},h('p',{text:'To ' + draft.to}),h('strong',{text:draft.subject}),
        h('p',{class:'work-preview',text:draft.body}));
      const controls = h('div');
      main.replaceChildren(preview,controls);
      function accepted(result) {
        controls.replaceChildren(h('p',{text:'Gmail accepted this message. Message ID ' + result.messageId +
          (result.receiptSaved === false ? '. Save this ID because the project receipt could not be stored.' : '.')}));
      }
      async function reconcile() {
        const state = await call('outreach_status',selector);
        if (state.status === 'provider_accepted') { accepted(state); return true; }
        if (state.status === 'claimed') {
          controls.replaceChildren(h('p',{text:'This draft already has a handoff. Check your Gmail Sent folder before following up.'}),
            action('Check for a receipt',reconcile));
          return true;
        }
        return false;
      }
      if (await reconcile()) return;
      const prepared = await call('outreach_prepare',selector);
      const exact = {...selector,to:prepared.to,subject:prepared.subject,body:prepared.body,confirm:true};
      const gmail = CB.googleUI?.gmail;
      let state;
      if (gmail) {
        try { state = await guarded(() => gmail.status(project)); }
        catch { status.textContent = 'Gmail connection status is unavailable.'; }
      }
      if (!active()) return;
      async function attempt(send) {
        controls.replaceChildren(h('p',{text:'Preparing your Gmail handoff…'}));
        try { await send(); }
        catch (err) {
          controls.replaceChildren(h('p',{text:'Check Gmail Sent and the project receipt before taking further action.'}),
            action('Check handoff status',async () => {
              if (!await reconcile()) status.textContent = 'No saved handoff was found. Reopen the draft to review it again.';
            }));
          status.textContent = err.message || 'The Gmail response could not be verified.';
        }
      }
      if (state?.connected) {
        controls.append(action('Send this email to ' + prepared.to,() => attempt(async () => {
          const result = await guarded(() => gmail.send(project,exact));
          if (result.status !== 'provider_accepted' || !result.messageId) throw Error('Gmail acceptance could not be verified.');
          accepted(result);
        })));
      } else if (state?.configured) {
        controls.append(action('Connect Gmail for this project',() => gmail.connect(project,active)));
      }
      controls.append(action('Review in Gmail compose',() => attempt(async () => {
        const message = await call('outreach_claim',exact);
        const params = new URLSearchParams({view:'cm',fs:'1',to:message.to,su:message.subject,body:message.body});
        location.assign('https://mail.google.com/mail/?' + params);
      })),h('p',{text:'Opening Gmail compose uses the one-time handoff. Review the sender and send there.'}));
    }
    async function approve(p, draft) {
      if (draft.approved) return reviewApproved(p,draft);
      main.replaceChildren(h('p',{text:'To ' + draft.to}), h('strong',{text:draft.subject}),
        h('p',{class:'work-preview',text:draft.body}), action('Approve this exact draft', async () => {
          const result = await call('draft_approve',{prospectId:p.id,version:draft.version,expected_revision:draft.revision});
          await reviewApproved(p,result.draft);
        }));
    }
    function compose(p, c) {
      const subject = h('input'), body = h('textarea');
      subject.value = p.draft?.subject || 'A source for your readers';
      body.value = p.draft?.body || 'Hello ' + (c.kind === 'author' ? c.name : 'editorial team') +
        ',\n\nI read your article at ' + url + '. Readers asking “' + term + '” may find this useful: ' + p.asset +
        ".\n\nWould it be useful to review for the article? If this isn't relevant, just tell me and I won't write again.\n\n[Your name]\n[Your organization]";
      main.replaceChildren(h('p',{text:'To ' + p.email}),field('Subject',subject),field('Email, including your name and organization',body),
        action('Save and review draft',async () => {
          const {draft} = await call('draft_save',{prospectId:p.id,expected_revision:p.draft?.revision || 0,
            subject:subject.value,body:body.value});
          await approve(p,draft);
        }));
    }
    if (saved?.draft) {
      reviewApproved(saved,saved.draft).catch(err => {status.textContent = err.message;});
      return;
    }
    status.textContent = 'Checking the article and credited authors…';
    call('citation_contact',{url,term}).then(found => {
      if (!active()) return;
      status.textContent = found.contacts.length ? '' : 'No attributable public contact address was found.';
      if (found.authors.length) main.append(h('p',{text:'By ' + found.authors.join(', ')}));
      found.contacts.forEach(c => {
        const asset = h('input');
        main.append(h('section',{},h('strong',{text:c.name + ' · ' + c.email}),source(c.sourceUrl),
          field('What evidence can you offer these readers?',asset), action('Save prospect and draft',async () => {
            const {prospect} = await call('citation_prospect_save',{url,term,email:c.email,asset:asset.value});
            compose(prospect,c);
          })));
      });
    }).catch(err => {status.textContent = err.message;});
  }
})();
