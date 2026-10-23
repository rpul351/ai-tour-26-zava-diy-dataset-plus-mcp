// Turns an answer from the agent into safe HTML. Runs in the browser; also loaded by tests/test_render.js under Node.
(function (root) {
    const escapeHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

    // Only links a person can safely follow: web pages, mail, and the agent's own charts and downloads.
    function safeHref(href) {
        const value = String(href || '').trim();
        return /^(https?:\/\/|mailto:|\/(charts|exports)\/|#)/i.test(value) ? value : '';
    }

    // The answer starts with "Scope: <stores>". Shown as a small label, not as text. While the first line is still arriving
    // nothing is shown yet, so a half-written "Sco" never flashes on screen.
    function splitScope(text) {
        const raw = String(text || '');
        if (raw.length <= 8 && /^\s*(\*\*)?s(c(o(p(e)?)?)?)?(:|\*\*)*$/i.test(raw)) return { scope: '', body: '', pending: true };
        const match = /^\s*(?:\*\*)?scope:?(?:\*\*)?:?[ \t]*([^\n]*)(\n+|$)/i.exec(raw);
        if (!match) return { scope: '', body: raw, pending: false };
        return { scope: match[1].replace(/\*\*/g, '').trim(), body: raw.slice(match[0].length), pending: !match[2] };
    }

    // "Zava Retail Seattle, Zava Retail Bellevue, ..." becomes "All 8 stores", "Seattle" or "Seattle, Tacoma".
    function scopeLabel(scope) {
        const text = String(scope || '').replace(/\([^)]*\)/g, '').trim();
        if (!text) return { label: '', full: '' };
        const names = text.split(/,|\band\b/i).map((n) => n.replace(/^\s*Zava Retail\s+/i, '').trim()).filter(Boolean);
        const all = /\ball\b.*\bstores\b/i.test(String(scope)) || names.length >= 8;
        const label = all ? `All ${Math.max(names.length, 8)} stores` : names.length > 3 ? `${names.length} stores` : names.join(', ');
        return { label, full: names.join(', ') };
    }

    let configured = null;
    function configure(marked) {
        if (configured === marked) return;
        marked.use({
            gfm: true,
            breaks: false,
            renderer: {
                html(token) { return escapeHtml(token && token.text !== undefined ? token.text : token); },
                link(token) {
                    const href = safeHref(token.href);
                    const inner = this.parser.parseInline(token.tokens);
                    return href ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${inner}</a>` : inner;
                },
                image(token) {
                    return /^\/charts\/[\w.-]+$/.test(String(token.href || ''))
                        ? `<img src="${escapeHtml(token.href)}" alt="${escapeHtml(token.text || '')}" loading="lazy">`
                        : escapeHtml(token.text || '');
                },
            },
        });
        configured = marked;
    }

    function renderMarkdown(marked, text) {
        configure(marked);
        return marked.parse(String(text || '')).replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, '</table></div>');
    }

    const api = { escapeHtml, safeHref, splitScope, scopeLabel, renderMarkdown };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.ZavaRender = api;
})(typeof window !== 'undefined' ? window : globalThis);
