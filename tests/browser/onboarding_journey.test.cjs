const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
test('setup exposes competitor and term saves plus research collection', () => {
 const src = fs.readFileSync(require.resolve('../../site/app/onboarding.js'),'utf8');
 for (const op of ['onboarding_save','research_get','researchCollection.panel','citationOutreach.open']) assert.ok(src.includes(op),op);
});
