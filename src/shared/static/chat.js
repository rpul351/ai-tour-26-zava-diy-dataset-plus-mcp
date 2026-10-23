// Chat page for the Zava Inventory Advisor. Rendering rules live in render.js, the saved transcript in transcript.js.
(() => {
    const $ = (id) => document.getElementById(id);
    const messagesEl = $('messages');
    const welcomeEl = $('welcome');
    const form = $('composer');
    const input = $('messageInput');
    const sendBtn = $('sendBtn');
    const fileBtn = $('fileBtn');
    const fileInput = $('fileInput');

    let isStreaming = false;
    let uploadedFile = null;
    let source = null;

    // One id per browser tab, so people using the same server do not share a conversation.
    const newId = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
    let sessionId = sessionStorage.getItem('sessionId') || (() => { const id = newId(); sessionStorage.setItem('sessionId', id); return id; })();

    // Tool calls are technical detail: shown only when the page is opened with ?debug=1 (for demos).
    const SHOW_TOOL_CALLS = new URLSearchParams(window.location.search).has('debug');

    // Every question and final answer, kept in this tab so the chat can be saved. Nothing is sent anywhere.
    const transcript = [];

    const el = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    };

    // Keep following the answer only while the reader is at the bottom; if they scrolled up to read, leave them there.
    const nearBottom = () => messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 140;
    const scrollToEnd = (force) => { if (force || nearBottom()) messagesEl.scrollTop = messagesEl.scrollHeight; };

    function hideWelcome() { if (welcomeEl) welcomeEl.hidden = true; }

    function setBusy(busy) {
        isStreaming = busy;
        fileBtn.disabled = busy;
        syncSend();
    }

    function syncSend() {
        sendBtn.disabled = isStreaming || (!input.value.trim() && !uploadedFile);
    }

    function autosize() {
        if (!input.value) { input.style.height = ''; return; }
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    }

    function addUser(text) {
        hideWelcome();
        const row = el('div', 'message user');
        row.append(el('div', 'bubble', text));
        messagesEl.append(row);
        scrollToEnd(true);
    }

    function addAssistant() {
        hideWelcome();
        const row = el('div', 'message assistant');
        const avatar = el('span', 'avatar brand-mark', 'Z');
        avatar.setAttribute('aria-hidden', 'true');
        const stack = el('div', 'stack');
        const bubble = el('div', 'bubble');
        const scope = el('div', 'scope');
        scope.hidden = true;
        const body = el('div', 'body');
        const thinking = el('div', 'thinking');
        thinking.setAttribute('role', 'status');
        thinking.setAttribute('aria-label', 'Working on your answer');
        thinking.append(el('i'), el('i'), el('i'));
        const status = el('span', 'status', 'Thinking\u2026');
        thinking.append(status);
        bubble.append(scope, body, thinking);
        stack.append(bubble);
        row.append(avatar, stack);
        messagesEl.append(row);
        scrollToEnd(true);
        return { row, stack, bubble, scope, body, thinking, status, text: '' };
    }

    // Draw the answer so far. Called as text arrives and once more when it is complete.
    function draw(view) {
        const stick = nearBottom();
        const parts = ZavaRender.splitScope(view.text);
        if (parts.scope && !parts.pending) {
            const { label, full } = ZavaRender.scopeLabel(parts.scope);
            view.scope.textContent = label || parts.scope;
            view.scope.title = full || parts.scope;
            view.scope.hidden = false;
        }
        if (parts.body.trim()) {
            view.body.innerHTML = ZavaRender.renderMarkdown(window.marked, parts.body);
            view.body.querySelectorAll('p').forEach((p) => { if (/^\s*verification note/i.test(p.textContent)) p.classList.add('notice'); });
            view.body.querySelectorAll('a').forEach((a) => { if (a.getAttribute('href') && a.getAttribute('href').startsWith('/exports/')) a.setAttribute('download', ''); });
        }
        if (parts.body.trim()) view.thinking.hidden = true;
        if (stick) scrollToEnd(true);
    }

    function addCopy(view) {
        const bar = el('div', 'msg-actions');
        const button = el('button', '', 'Copy');
        button.type = 'button';
        button.setAttribute('aria-label', 'Copy this answer');
        button.addEventListener('click', async () => {
            const text = view.body.innerText.trim();
            try { await navigator.clipboard.writeText(text); } catch (_) {
                const area = el('textarea'); area.value = text; document.body.append(area); area.select(); document.execCommand('copy'); area.remove();
            }
            button.textContent = 'Copied';
            setTimeout(() => { button.textContent = 'Copy'; }, 1600);
        });
        bar.append(button);
        view.stack.append(bar);
    }

    function fail(view, message) {
        view.thinking.hidden = true;
        view.row.classList.add('error');
        view.scope.hidden = true;
        view.body.textContent = message;
    }

    function addToolCall(container, tool) {
        const args = Object.entries(tool.arguments || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ');
        container.append(el('div', '', `${tool.name}(${args}) \u00B7 ${tool.ms} ms`));
        scrollToEnd(false);
    }

    function addImage(view, info) {
        if (!String(info.relative_path || '').startsWith('/')) return;
        const img = el('img');
        img.src = info.relative_path;
        img.alt = info.attachment_name || 'Chart';
        img.loading = 'lazy';
        view.body.append(img);
        scrollToEnd(false);
    }

    function formatFileSize(bytes) {
        if (!bytes) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
        return `${parseFloat((bytes / 1024 ** i).toFixed(1))} ${units[i]}`;
    }

    function handleFileSelection() {
        const file = fileInput.files[0];
        if (!file) return;
        if (file.size > 10 * 1024 * 1024) {
            alert('File size must be less than 10 MB');
            fileInput.value = '';
            return;
        }
        uploadedFile = file;
        const chip = el('div', 'file-info');
        chip.append(el('span', 'file-name', file.name), el('span', 'file-size', formatFileSize(file.size)));
        hideWelcome();
        messagesEl.append(chip);
        input.placeholder = 'Add a message about the file, or press send';
        syncSend();
        scrollToEnd(true);
    }

    async function sendMessage(preset) {
        const message = (preset !== undefined ? preset : input.value).trim();
        if ((!message && !uploadedFile) || isStreaming) return;
        setBusy(true);

        let finalMessage = message;
        try {
            if (uploadedFile) {
                const shown = message ? `${message}\n\nFile: ${uploadedFile.name}` : `Please analyse this file: ${uploadedFile.name}`;
                addUser(shown);
                transcript.push({ role: 'user', text: shown });
                const formData = new FormData();
                formData.append('file', uploadedFile);
                if (message) formData.append('message', message);
                const uploaded = await fetch('/upload', { method: 'POST', body: formData });
                if (!uploaded.ok) throw new Error('The file could not be uploaded.');
                const result = await uploaded.json();
                finalMessage = result.content || 'Please analyse this file.';
                uploadedFile = null;
                fileInput.value = '';
                input.placeholder = 'Ask about stock or sales';
            } else {
                addUser(message);
                transcript.push({ role: 'user', text: message });
            }
        } catch (error) {
            const view = addAssistant();
            fail(view, error.message);
            setBusy(false);
            return;
        }

        input.value = '';
        autosize();

        const view = addAssistant();
        let toolsEl = null;
        let finished = false;
        let frame = 0;
        const schedule = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; draw(view); }); };
        const finish = () => {
            finished = true;
            if (frame) { cancelAnimationFrame(frame); frame = 0; }
            if (source) source.close();
            source = null;
            setBusy(false);
            if (window.matchMedia('(hover: hover)').matches) input.focus();
        };

        source = new EventSource('/chat/stream?' + new URLSearchParams({ message: finalMessage, session_id: sessionId }));
        const mine = source;

        source.onmessage = (event) => {
            if (finished || source !== mine) return;
            if (event.data === '[DONE]') {
                view.thinking.hidden = true;
                draw(view);
                if (view.text.trim()) { transcript.push({ role: 'assistant', text: view.text }); addCopy(view); }
                finish();
                return;
            }
            let parsed;
            try { parsed = JSON.parse(event.data); } catch (_) { return; }
            if (parsed.tool) {
                if (SHOW_TOOL_CALLS) {
                    if (!toolsEl) { toolsEl = el('div', 'toolcalls'); messagesEl.insertBefore(toolsEl, view.row); }
                    addToolCall(toolsEl, parsed.tool);
                }
            } else if (parsed.status) {
                view.status.textContent = parsed.status + '\u2026';
            } else if (parsed.content) {
                view.text += parsed.content;
                schedule();
            } else if (parsed.file || (parsed.type === 'file' && parsed.file_info)) {
                const info = parsed.file || parsed.file_info;
                if (info.is_image) addImage(view, info);
                else { view.text += `\n\n[${info.file_name}](${info.relative_path})\n`; schedule(); }
            } else if (parsed.error) {
                fail(view, parsed.error);
                finish();
            }
        };

        source.onerror = () => {
            if (finished || source !== mine) return;
            fail(view, 'The connection was lost. Please try again.');
            finish();
        };
    }

    function newChat() {
        if (source) { source.close(); source = null; }
        sessionId = newId();
        sessionStorage.setItem('sessionId', sessionId);
        transcript.length = 0;
        uploadedFile = null;
        fileInput.value = '';
        messagesEl.querySelectorAll('.message, .file-info, .toolcalls').forEach((node) => node.remove());
        if (welcomeEl) welcomeEl.hidden = false;
        input.value = '';
        input.placeholder = 'Ask about stock or sales';
        autosize();
        setBusy(false);
        input.focus();
    }

    // Save the conversation as a Markdown file, or print it (the browser can save that as a PDF).
    function saveChat() {
        const text = ZavaTranscript.buildTranscript(transcript, { now: new Date() });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
        link.download = ZavaTranscript.fileName(new Date());
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }

    form.addEventListener('submit', (event) => { event.preventDefault(); sendMessage(); });
    input.addEventListener('input', () => { autosize(); syncSend(); });
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendMessage(); }
    });
    document.querySelectorAll('.chip').forEach((chip) => chip.addEventListener('click', () => sendMessage(chip.dataset.prompt)));
    $('newChatBtn').addEventListener('click', newChat);
    $('saveChatBtn').addEventListener('click', saveChat);
    $('printChatBtn').addEventListener('click', () => window.print());
    fileBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileSelection);

    syncSend();
    if (window.matchMedia('(hover: hover)').matches) input.focus();
})();
