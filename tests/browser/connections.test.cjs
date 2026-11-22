'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const {join} = require('node:path');

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function load(extra = {}) {
  const CB = {day: d => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d || ''); return m ? MONTHS[+m[2] - 1] + ' ' + (+m[3]) + ', ' + m[1] : d; }, ...extra};
  runInNewContext(readFileSync(join(__dirname, '../../site/app/connections.js'), 'utf8'), {window: {CB}});
  return CB.connectionsUI.status;
}
const status = load();

test('Google: not switched on for this website reads as not available, never as connected', () => {
  const s = status.google({configured: false, error: 'Google connections are unavailable on this deployment.'});
  assert.equal(s.tone, 'off');
  assert.equal(s.label, 'Not available');
});

test('Google: no sign-in yet is Not set up', () => {
  const s = status.google({configured: true, connected: false, property: null});
  assert.equal(s.tone, 'off');
  assert.equal(s.label, 'Not set up');
});

test('Google: signed in without a property needs action and says what to do', () => {
  const s = status.google({configured: true, connected: true, property: null});
  assert.equal(s.tone, 'action');
  assert.equal(s.label, 'Needs action');
  assert.match(s.detail, /Choose property/);
});

test('Google: connected shows the property and the last import date', () => {
  const s = status.google({configured: true, connected: true, property: 'sc-domain:example.com',
    last_import: {start_date: '2026-10-21', end_date: '2026-11-17', observed_at: '2026-11-18', count: 12}});
  assert.equal(s.tone, 'good');
  assert.equal(s.label, 'Connected');
  assert.equal(s.account, 'sc-domain:example.com');
  assert.equal(s.sync, 'Last import Nov 18, 2026 · covers Oct 21, 2026 to Nov 17, 2026 · 12 rows');
});

test('Google: connected but never imported asks for the first import', () => {
  const s = status.google({configured: true, connected: true, property: 'properties/123'});
  assert.equal(s.tone, 'good');
  assert.match(s.sync, /No import yet/);
});

test('Google: a failed check or a refused sign-in needs action with Reconnect', () => {
  const s = status.google({error: 'Could not confirm this Google operation. Check project history before retrying an import, or reconnect Google.'});
  assert.equal(s.tone, 'action');
  assert.match(s.detail, /Reconnect/);
});

test('Google: unknown state while loading is Checking, not a guess', () => {
  assert.equal(status.google(null).tone, 'checking');
});

test('Gmail: connected, not set up and unavailable', () => {
  assert.equal(status.gmail({configured: true, connected: true}).label, 'Connected');
  assert.equal(status.gmail({configured: true, connected: false}).label, 'Not set up');
  assert.equal(status.gmail({configured: false}).label, 'Not available');
  assert.equal(status.gmail({error: 'Gmail is unavailable.'}).tone, 'action');
});

test('Pasted data: saved shows the last saved date, missing shows how to add it', () => {
  const saved = status.saved('bots', {date: '2026-11-20', period: {from: '2026-11-13', to: '2026-11-19'}});
  assert.equal(saved.tone, 'good');
  assert.equal(saved.label, 'Saved');
  assert.equal(saved.sync, 'Last saved Nov 20, 2026 · covers Nov 13, 2026 to Nov 19, 2026');
  const missing = status.saved('traffic', null);
  assert.equal(missing.tone, 'off');
  assert.equal(missing.label, 'Not set up');
  assert.match(missing.detail, /paste/i);
  assert.match(status.saved('bots', null).detail, /access log/);
});

test('Pasted data without a saved date says what it covers, never repeats the badge', () => {
  assert.equal(status.saved('traffic', {ai_visits: 10, by_month: [{month: '2026-09'}, {month: '2027-02'}]}).sync, 'Covers Sep 2026 to Feb 2027');
  assert.equal(status.saved('traffic', {date: '2026-11-02', by_month: [{month: '2026-10'}]}).sync, 'Last saved Nov 2, 2026 · covers Oct 2026');
  assert.equal(status.saved('bots', {bots: []}).sync, '');
});

test('Summary counts ready and needs-action cards, ignoring coming soon', () => {
  assert.equal(status.summary(['good', 'good', 'action', 'off', 'soon', 'soon']), '2 ready · 1 needs action · 1 not set up');
  assert.equal(status.summary(['off', 'off']), 'Nothing connected yet');
  assert.equal(status.summary(['checking', 'good']), '1 ready · checking the rest…');
  assert.equal(status.summary(['action', 'action', 'off']), '2 need action · 1 not set up');
});
