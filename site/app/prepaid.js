/* Apify reports monthly usage through its API. Account owners can separately record the prepaid pool from Billing. */
(function () {
  'use strict';
  const CB = window.CB, h = CB.h;
  const available = () => !CB.demo && CB.hasProjectWork && CB.cfg.oauth?.session !== false &&
    CB.api === 'https://khadinakbar--citebase.apify.actor';
  const current = row => row.period_end >= new Date().toISOString().slice(0,10);
  const observed = value => new Intl.DateTimeFormat(undefined, {dateStyle:'medium',timeStyle:'short'}).format(new Date(value));
  async function read() {
    if (!available()) return null;
    try { return await CB.tool('dashboard_balance_read',{}); }
    catch { return {unavailable:true}; }
  }
  function card(account) {
    const box = h('section',{class:'card prepaid-card','aria-label':'Remaining prepaid credits'});
    const body = h('div',{'aria-live':'polite'});
    box.append(h('h3',{text:'Remaining prepaid credits'}),body);
    let row = account.prepaid, failed = account.prepaidUnavailable;
    function show() {
      CB.clear(body);
      if (row) {
        body.append(h('p',{class:'prepaid-amount',text:CB.usage.usd(row.amount_usd)}),
          h('p',{class:'prepaid-asof'},'Checked ',h('time',{datetime:row.observed_at,text:observed(row.observed_at)}),
            ' · Period ends '+CB.day(row.period_end)+' UTC.'));
        if (!current(row)) body.append(h('p',{class:'billing-notice',text:'That billing period has ended. Check the current period in Apify Billing.'}));
        else if (row.amount_usd === 0) body.append(h('p',{class:'billing-notice',text:'Prepaid balance was zero at the last check. Review billing before your next paid run.'}));
      } else {
        body.append(h('p',{class:'prepaid-empty',text:failed ? 'Saved balance unavailable' : 'No balance recorded'}));
      }
      body.append(h('p',{class:'muted',text:'Apify Billing shows your current prepaid usage. Record the amount here to keep a dated reference in your private Apify storage.'}),
        h('div',{class:'billing-links'},CB.usage.billingLink(),h('button',{type:'button',class:'btn tiny ghost',
          text:row ? 'Update balance' : 'Record a balance',onclick:edit})));
    }
    function edit() {
      const amount = h('input',{type:'number',inputmode:'decimal',min:'0',max:'1000000000',step:'0.01',required:true});
      const end = h('input',{type:'date',required:true,min:new Date().toISOString().slice(0,10),
        value:row && current(row) ? row.period_end : ''});
      const error = h('p',{class:'billing-notice',role:'alert',hidden:true});
      const save = h('button',{type:'submit',class:'btn tiny',text:'Save checked balance'});
      const cancel = h('button',{type:'button',class:'btn tiny ghost',text:'Cancel',onclick:show});
      const form = h('form',{class:'prepaid-form'},
        h('p',{class:'muted'},'Open Billing → Current period. Enter “Remaining prepaid usage” and the end date shown there.'),
        CB.usage.billingLink(),h('label',{},'Remaining prepaid usage (USD)',amount),
        h('label',{},'Billing period ends',end),error,h('div',{class:'billing-links'},save,cancel));
      form.addEventListener('submit',async event => {
        event.preventDefault();
        if (save.disabled || !form.reportValidity()) return;
        save.disabled = true; cancel.disabled = true; error.hidden = true;
        try {
          const result = await CB.tool('dashboard_balance_save',{amount_usd:amount.valueAsNumber,period_end:end.value,confirmed:true});
          row = result.balance; failed = false;
          show();
          CB.usage.read(true).catch(()=>{});
        } catch (e) {
          error.textContent = e.message || 'Could not save. Open Account again to check the last recorded balance.';
          error.hidden = false; save.disabled = false; cancel.disabled = false;
        }
      });
      CB.clear(body).appendChild(form);
      amount.focus();
    }
    show();
    return box;
  }
  CB.prepaid = {available,current,read,card};
})();
