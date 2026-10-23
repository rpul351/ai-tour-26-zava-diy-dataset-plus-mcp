// Run: node tests/test_render.js  (uses the same markdown library the page loads)
const assert = require('assert');
const marked = require('../src/shared/static/marked.min.js');
const R = require('../src/shared/static/render.js');

let passed = 0;
const test = (name, fn) => { fn(); passed += 1; console.log('ok  ' + name); };

test('scope line is split off and labelled', () => {
    const s = R.splitScope('Scope: Zava Retail Kirkland\n\n**1,782** units');
    assert.strictEqual(s.scope, 'Zava Retail Kirkland');
    assert.strictEqual(s.body, '**1,782** units');
    assert.strictEqual(R.scopeLabel(s.scope).label, 'Kirkland');
    const all = 'Zava Retail Seattle, Zava Retail Bellevue, Zava Retail Tacoma, Zava Retail Spokane, Zava Retail Everett, Zava Retail Redmond, Zava Retail Kirkland, Zava Retail Online';
    assert.strictEqual(R.scopeLabel(all).label, 'All 8 stores');
    assert.strictEqual(R.scopeLabel('Zava Retail Seattle, Zava Retail Tacoma').label, 'Seattle, Tacoma');
    assert.strictEqual(R.scopeLabel('Zava Retail Seattle, Zava Retail Tacoma (all 8 stores)').label, 'All 8 stores');
});

test('a half-arrived scope line shows nothing yet', () => {
    for (const part of ['S', 'Sco', 'Scope', 'Scope:']) assert.strictEqual(R.splitScope(part).pending, true, part);
    const partial = R.splitScope('Scope: Zava Retail Seat');
    assert.strictEqual(partial.pending, true);
    assert.strictEqual(R.splitScope('Seattle sold 5 units').pending, false);
    assert.strictEqual(R.splitScope('Seattle sold 5 units').body, 'Seattle sold 5 units');
    assert.strictEqual(R.splitScope('**Scope:** all stores\n\nHi').scope, 'all stores');
});

test('markdown renders bold, lists and wrapped tables', () => {
    const html = R.renderMarkdown(marked, '**Seattle** sold 5\n\n| A | B |\n|:---|---:|\n| x | 1 |\n');
    assert.match(html, /<strong>Seattle<\/strong>/);
    assert.match(html, /<div class="table-wrap"><table>/);
    assert.match(html, /<\/table><\/div>/);
});

test('model or tool text cannot inject script, handlers or unsafe links', () => {
    const attacks = [
        '<script>alert(1)</script>',
        '<img src=x onerror=alert(1)>',
        '[click](javascript:alert(1))',
        '[click](JaVaScRiPt:alert(1))',
        '![x](https://evil.example/a.png)',
        '<a href="javascript:alert(1)">x</a>',
        '<iframe src="https://evil.example"></iframe>',
    ];
    for (const text of attacks) {
        const html = R.renderMarkdown(marked, text);
        assert.doesNotMatch(html, /<script|<iframe|<img[^>]*onerror|href="javascript|<img src="https?:/i, text + ' -> ' + html);
    }
});

test('own charts, downloads and web links still work', () => {
    const html = R.renderMarkdown(marked, '![chart](/charts/c0123456789abcdef0123.png)\n\n[CSV](/exports/e0123456789abcdef0123.csv) [site](https://example.com)');
    assert.match(html, /<img src="\/charts\/c0123456789abcdef0123\.png"/);
    assert.match(html, /<a href="\/exports\/e0123456789abcdef0123\.csv" target="_blank" rel="noopener noreferrer">CSV<\/a>/);
    assert.match(html, /href="https:\/\/example\.com"/);
});

console.log(`${passed} passed`);
