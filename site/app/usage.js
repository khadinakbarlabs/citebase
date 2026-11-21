/* Account usage comes directly from Apify, including when the Citebase Actor cannot start. */
(function () {
  'use strict';
  const CB = window.CB;
  const h = (...args) => CB.h(...args);
  const billingUrl = 'https://console.apify.com/billing';
  const dollars = new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:6});
  const cents = new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'});
  const unavailable = 'Unavailable';
  let cached = null;
  function usd(value) {
    if (value == null) return unavailable;
    if (value > 0 && value < 0.01) return '<' + cents.format(0.01);
    return cents.format(value);
  }
  function amount(value) { return Number.isFinite(value) && value >= 0 ? value : null; }
  function profile(me) {
    const plan = me?.plan || {};
    return {username:typeof me?.username === 'string' ? me.username : null,plan:typeof plan.id === 'string' ? plan.id : null,retention:amount(plan.dataRetentionDays),
      included:amount(plan.monthlyUsageCreditsUsd),annual:plan.forceBillingInterval === 'ANNUAL'};
  }
  function limits(data) {
    return {limit:amount(data?.limits?.maxMonthlyUsageUsd),spent:amount(data?.current?.monthlyUsageUsd),cycle:data?.monthlyUsageCycle};
  }
  function monthly(data) { return {spent:amount(data?.totalUsageCreditsUsdAfterVolumeDiscount),cycle:data?.usageCycle}; }
  async function report(session) {
    // Keep only these fields. The account profile may also contain proxy credentials.
    const part = (path, select) => CB.apify('GET',path).then(select, error => ({restricted:error.status === 403}));
    const [me,lim,saved] = await Promise.all([part('users/me',profile), part('users/me/limits',limits),CB.prepaid?.read()]);
    if (session !== CB.sessionId()) throw new Error('signed out');
    // The monthly endpoint includes a full daily breakdown. Read it only when the smaller limits response lacks spending.
    const usage = lim.spent == null ? await part('users/me/usage/monthly',monthly) : {};
    if (session !== CB.sessionId()) throw new Error('signed out');
    const used = lim.spent ?? usage.spent ?? null, included = me.included ?? null;
    const cycle = lim.cycle || usage.cycle || {};
    return {username:me.username || null,plan:me.plan || null,retention:me.retention ?? null,
      included, used, limit:lim.limit ?? null, annual:me.annual === true,
      includedLeft:used != null && included != null && !me.annual ? Math.max(0,included-used) : null,
      room:lim.limit === 0 ? 0 : (lim.limit != null && lim.spent != null ? Math.max(0,lim.limit-lim.spent) : null),
      start:cycle.startAt || null,end:cycle.endAt || null,restricted:!!(lim.restricted || usage.restricted || me.restricted),
      prepaid:saved?.balance || null,prepaidUnavailable:saved?.unavailable === true};
  }
  function read(fresh) {
    const session = CB.sessionId();
    if (cached && cached.session === session && (cached.pending || (!fresh && Date.now() < cached.expires))) return cached.promise;
    const entry = {session, pending:true}; cached = entry;
    entry.promise = report(session).then(snapshot => {
      entry.pending = false;
      entry.expires = Date.now() + 30000;
      if (entry === cached && typeof CB.usage.onUpdate === 'function') CB.usage.onUpdate(snapshot);
      return snapshot;
    }, error => { if (entry === cached) cached = null; throw error; });
    return entry.promise;
  }
  function billingLink() {
    return h('a', {class:'ext',href:billingUrl,target:'_blank',rel:'noopener noreferrer',text:'Open Apify Billing ↗'});
  }
  function compact(a) {
    if (a.room === 0) return 'Apify limit reached' + (a.used == null ? '' : ' · ' + usd(a.used) + ' used');
    if (a.prepaid && CB.prepaid.current(a.prepaid)) return 'Apify · ' + usd(a.prepaid.amount_usd) + ' prepaid at last check';
    if (a.used == null) return 'Apify usage unavailable';
    const used = 'Apify · ' + usd(a.used) + ' used';
    if (a.room != null && (a.includedLeft == null || a.room < a.includedLeft)) return used + ' · ' + usd(a.room) + ' before hard limit';
    return used + (a.includedLeft != null ? ' · ' + usd(a.includedLeft) + ' est. plan allowance left' : '');
  }
  function summary(a) {
    const rows = [['Used this cycle',usd(a.used)], ['Included per month',usd(a.included)]];
    if (!a.annual) rows.push(['Est. monthly allowance left',usd(a.includedLeft)]);
    rows.push(['Monthly hard limit',usd(a.limit)], ['Room before hard limit',usd(a.room)]);
    const text = a.room === 0 ? 'Your monthly spending limit has been reached.' : a.includedLeft === 0
      ? 'Usage has reached the monthly plan allowance. Annual or promotional credit may still cover additional checks.' : '';
    return h('div',{class:'billing-summary'},
      text ? h('p',{class:'billing-notice',text}) : null,
      h('dl',{class:'facts billing-figures'},rows.map(([label,value])=>h('div',{},h('dt',{text:label}),h('dd',{text:value})))),
      h('p',{class:'muted',text:a.annual ? 'Annual plans pool prepaid usage across the year. Apify Billing shows your available credit.'
        : 'The estimate subtracts this cycle’s usage from the monthly plan allowance. Annual billing and credits can change your available balance.'}),
      a.restricted ? h('p',{class:'muted',text:'This sign-in has limited access to billing details.'}) : null,
      billingLink());
  }
  function refusal(error) {
    if (!error || !Number.isInteger(error.status) || error.status < 400 || error.status >= 500) return null;
    const type = error.type || '';
    const detail = error.message || '';
    if (type === 'not-enough-usage-to-run-paid-actor') return 'Apify declined the start because available usage is insufficient for this Actor.';
    if (type === 'apify-plan-required-to-use-paid-actor') return 'Apify requires an eligible billing plan to start this Actor.';
    if (['failed-to-charge-user','no-payment-method-available','user-problem-with-card','missing-billing-info','stripe-generic-decline'].includes(type))
      return 'Apify declined this request because of a billing or payment issue.';
    const spending = /(?:monthly|platform) usage|spend(?:ing)? limit|platform spend|usage credits?|prepaid usage|insufficient (?:credit|funds)/i.test(detail);
    if (['limit-reached','platform-feature-disabled','actor-run-failed',''].includes(type) &&
        spending && /exceed|reach|exhaust|insufficient|hard limit/i.test(detail))
      return 'Apify declined this request because of an account usage limit. Check your available usage in Apify Billing.';
    return error.status === 402 ? 'Apify requires a billing action before this request can proceed.' : null;
  }
  function errorDetails(error) {
    const message = refusal(error);
    if (!message) return null;
    const figures = h('p',{class:'muted','aria-live':'polite',text:'Checking current Apify usage…'});
    read(true).then(a => {
      const values = [];
      if (a.prepaid && CB.prepaid.current(a.prepaid)) values.push(usd(a.prepaid.amount_usd) + ' prepaid at the last balance check');
      if (a.used != null) values.push(usd(a.used) + ' used this cycle');
      if (a.includedLeft != null) values.push(usd(a.includedLeft) + ' est. monthly allowance left');
      if (a.room != null) values.push(usd(a.room) + ' before the hard limit');
      figures.textContent = values.length ? values.join(' · ') : 'Apify Billing has the current balance for this account.';
    }, () => { figures.textContent = 'Open Apify Billing to check the current balance.'; });
    return h('div',{class:'billing-error',role:'alert'},h('p',{text:message}),figures,billingLink());
  }
  function decision(a, cap, recurring) {
    if (amount(cap) == null || cap === 0) return {kind:'blocked',message:'A positive data charge cap is required to approve paid checks.'};
    const slack = Number.EPSILON * Math.max(1, cap, a.limit || 0) * 8;
    if (a.room == null && a.limit != null && (a.limit === 0 || cap-a.limit > slack))
      return {kind:'blocked',message:'The data charge cap exceeds your entire monthly Apify limit of ' + usd(a.limit) + '.'};
    if (a.room != null && (a.room === 0 || cap-a.room > slack)) {
      return {kind:'blocked',message: a.room === 0
        ? 'Your monthly Apify spending limit has been reached. Review your billing or wait for the next cycle.'
        : 'The data charge cap exceeds the ' + usd(a.room) + ' available before your monthly spending limit.'};
    }
    if (a.prepaid && CB.prepaid.current(a.prepaid) && cap-a.prepaid.amount_usd > slack) {
      return {kind:'overage',message:'The data charge cap exceeds the last recorded prepaid balance of '+
        usd(a.prepaid.amount_usd)+'. Check Apify Billing before approving possible overage.'};
    }
    if (a.room == null || a.includedLeft == null) return {kind:'unknown',message: a.annual
      ? 'Apify pools annual credits across the year. Check your available balance in Apify Billing.'
      : 'Citebase could not verify all of your available usage. Check your balance in Apify Billing.'};
    if (a.includedLeft === 0 || cap-a.includedLeft > slack) return {kind:'overage',message:
      'This ' + (recurring ? 'scheduled check' : 'check') + ' could exceed your monthly plan allowance. Apify may bill overage.'};
    return {kind:'covered',message:recurring ? 'Your balance can change before future checks run.' : ''};
  }
  function scheduleTerms(schedule) {
    if (Number.isInteger(schedule.monthlyAllowance) && Number.isInteger(schedule.checksPerOccurrence)) {
      return 'Project allowance of ' + schedule.monthlyAllowance + ' checks per month, with ' +
        schedule.checksPerOccurrence + ' checks each time.';
    }
    const calendar = {monthly:'once per calendar month',weekly:'4–5 times per calendar month',daily:'28–31 times per calendar month'};
    if (calendar[schedule.frequency] && Number.isInteger(schedule.paidRuns)) {
      return 'Normally runs ' + calendar[schedule.frequency] + ', with ' + schedule.paidRuns +
        (schedule.paidRuns === 1 ? ' paid Actor run' : ' paid Actor runs') + ' each time. This schedule has no project monthly allowance.';
    }
    return 'Check the schedule frequency and monthly allowance before confirming.';
  }
  function guard(cap, schedule) {
    const recurring = !!schedule;
    const session = CB.sessionId();
    const detail = h('p',{class:'billing-guard-detail',text:'Checking Apify usage…'});
    const ack = h('input',{type:'checkbox'});
    const label = h('label',{class:'check'},ack,recurring
      ? 'I approve recurring paid checks, including future overage if my credits run out, plus separate Apify compute and platform charges.'
      : 'I approve possible Apify overage within the displayed data charge cap, plus platform usage.');
    const actions = h('div',{class:'billing-links'},billingLink(),h('button',{type:'button',class:'btn tiny ghost',text:'Refresh usage',onclick:()=>update(true).catch(()=>{})}));
    label.hidden = true;
    const node = h('div',{class:'billing-guard'},h('p',{class:'billing-cap',text:'Data charge cap ' + (amount(cap) == null ? unavailable : dollars.format(cap)) + (recurring ? ' per scheduled check' : ' for this check') + '. Apify bills platform usage separately.'}),
      recurring ? h('p',{text:scheduleTerms(schedule)}) : null,detail,label,actions);
    let state, control = null;
    function allow() { return state && state.kind !== 'blocked' && ((!recurring && state.kind === 'covered') || ack.checked); }
    function sync() { if (control) control.disabled = !allow(); }
    ack.addEventListener('change',sync);
    async function update(fresh) {
      const a = await read(fresh);
      if (session !== CB.sessionId()) throw new Error('signed out');
      const next = decision(a,cap,recurring);
      if (next.kind !== state?.kind) ack.checked = false;
      state = next;
      label.hidden = next.kind === 'blocked' || (!recurring && next.kind === 'covered');
      const metrics = a.used == null ? '' : usd(a.used) + ' used this cycle' +
        (a.includedLeft == null ? '' : ' · ' + usd(a.includedLeft) + ' est. monthly allowance left') + '. ';
      detail.textContent = metrics + next.message;
      sync();
    }
    const ready = update(false);
    ready.catch(()=>{});
    return {node, bind(button) {control = button; sync();},async verify() {
      await ready;
      // The quote may have stayed open while another run spent this account's allowance.
      await update(true);
      if (!allow()) throw new Error(state.kind === 'blocked' ? state.message : 'Review and approve possible Apify overage to continue.');
    }};
  }
  CB.usage = {read,billingLink,compact,summary,guard,decision,refusal,errorDetails,usd,
    reset() {cached = null; this.onUpdate = null;}};
})();
