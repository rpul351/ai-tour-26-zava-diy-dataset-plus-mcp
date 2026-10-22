// Run with: node tests/test_transcript.js   (any Node 18 or later)
const assert = require('assert');
const { buildTranscript, fileName } = require('../src/shared/static/transcript.js');

const now = new Date(2026, 9, 22, 9, 5);
const md = buildTranscript([
    { role: 'user', text: 'hi' },
    { role: 'assistant', text: 'Hello! I am the Zava Inventory Advisor.' },
    { role: 'user', text: 'top 5 products' },
    { role: 'assistant', text: '| Product | Units |\n|:---|---:|\n| Cedar 2x4x8 | 449 |\n\n![chart](/charts/c0123456789abcdef012.png)' },
], { now, user: 'Kim' });

assert.ok(md.startsWith('# Zava Inventory Advisor chat'));
assert.ok(md.includes('Saved 2026-10-22 09:05 for Kim.'));
assert.ok(md.indexOf('## Question 1') < md.indexOf('### Answer 1') && md.indexOf('### Answer 1') < md.indexOf('## Question 2'));
assert.ok(md.includes('| Cedar 2x4x8 | 449 |'), 'tables must be kept exactly');
assert.ok(md.includes('![chart](/charts/c0123456789abcdef012.png)'), 'chart links must be kept');
assert.ok(!md.includes('undefined') && !md.includes('[object'));

assert.ok(buildTranscript([], { now }).includes('_No questions yet._'));
assert.ok(!buildTranscript([{ role: 'user', text: '   ' }, { role: 'assistant', text: '' }], { now }).includes('Question 1'), 'blank entries are skipped');
assert.ok(buildTranscript([{ role: 'assistant', text: 'Welcome' }], { now }).includes('### Answer 1'), 'an answer before any question still gets a heading');
assert.strictEqual(fileName(now), 'zava-chat-2026-10-22-0905.md');
console.log('transcript tests passed');
