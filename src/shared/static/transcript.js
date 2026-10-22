// Builds a saved copy of a conversation. Runs in the browser only, so no chat leaves the page.
// Also loaded by tests/test_transcript.js under Node.
(function (root) {
    function stamp(date) {
        const p = (n) => String(n).padStart(2, '0');
        return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}`;
    }

    // entries: [{role: 'user' | 'assistant', text: string}]. Returns Markdown.
    function buildTranscript(entries, options) {
        const opts = options || {};
        const lines = [`# Zava Inventory Advisor chat`, ''];
        lines.push(`Saved ${stamp(opts.now || new Date())}${opts.user ? ` for ${opts.user}` : ''}.`);
        lines.push('Figures are a snapshot from the time of each answer. Links to charts and downloads work only while you are signed in.', '');
        let turn = 0;
        for (const entry of entries) {
            const text = String(entry.text || '').trim();
            if (!text) continue;
            if (entry.role === 'user') {
                turn += 1;
                lines.push(`## Question ${turn}`, '', text, '');
            } else {
                lines.push(`### Answer ${turn || 1}`, '', text, '');
            }
        }
        if (turn === 0) lines.push('_No questions yet._', '');
        return lines.join('\n');
    }

    function fileName(now) {
        const d = now || new Date();
        const p = (n) => String(n).padStart(2, '0');
        return `zava-chat-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.md`;
    }

    const api = { buildTranscript, fileName };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.ZavaTranscript = api;
})(typeof window !== 'undefined' ? window : globalThis);
