var state = {
    conversationId: 'conv-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8),
    messages: [],
    isStreaming: false,
    sources: []
};

function generateId() {
    return 'conv-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
}

var $input = document.getElementById('user-input');
var $sendBtn = document.getElementById('btn-send');
var $messages = document.getElementById('messages');
var $welcome = document.getElementById('welcome-screen');
var $historyList = document.getElementById('history-list');
var $sourcesContent = document.getElementById('sources-content');

$input.addEventListener('input', function() {
    $sendBtn.disabled = !$input.value.trim();
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, 120) + 'px';
});

$input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

$sendBtn.addEventListener('click', sendMessage);
document.getElementById('btn-new-chat').addEventListener('click', newChat);

document.querySelectorAll('.example-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        $input.value = btn.getAttribute('data-q');
        $sendBtn.disabled = false;
        sendMessage();
    });
});

document.getElementById('btn-about').addEventListener('click', function() {
    document.getElementById('about-modal').classList.add('visible');
});
document.getElementById('close-about').addEventListener('click', function() {
    document.getElementById('about-modal').classList.remove('visible');
});
document.getElementById('btn-stats').addEventListener('click', function() {
    document.getElementById('stats-modal').classList.add('visible');
    loadStats();
});
document.getElementById('close-stats').addEventListener('click', function() {
    document.getElementById('stats-modal').classList.remove('visible');
});

document.querySelectorAll('.modal-overlay').forEach(function(overlay) {
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.classList.remove('visible');
    });
});

function scrollToBottom() {
    $messages.scrollTop = $messages.scrollHeight;
}

function sendMessage() {
    var text = $input.value.trim();
    if (!text || state.isStreaming) return;

    $welcome.style.display = 'none';
    $messages.classList.add('visible');

    state.messages.push({ role: 'user', content: text });
    appendMessage('user', text);
    scrollToBottom();

    $input.value = '';
    $sendBtn.disabled = true;
    $input.style.height = 'auto';

    var assistantEl = appendMessage('assistant', '');
    var bubbleEl = assistantEl.querySelector('.msg-bubble');
    bubbleEl.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
    scrollToBottom();

    state.isStreaming = true;
    var fullResponse = '';
    state.sources = [];

    fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            query: text,
            history: state.messages.slice(0, -1)
        })
    }).then(function(response) {
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function readChunk() {
            reader.read().then(function(result) {
                if (result.done) {
                    finishMessage(bubbleEl, text, fullResponse);
                    return;
                }

                buffer += decoder.decode(result.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop();

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    if (line.indexOf('data: ') !== 0) continue;
                    var data = line.substring(6).trim();
                    if (data === '[DONE]') {
                        finishMessage(bubbleEl, text, fullResponse);
                        return;
                    }

                    try {
                        var parsed = JSON.parse(data);
                        if (parsed.type === 'sources') {
                            state.sources = parsed.sources || [];
                            renderSources(state.sources);
                        } else if (parsed.type === 'token') {
                            fullResponse += parsed.content;
                            bubbleEl.innerHTML = renderMarkdown(fullResponse);
                            scrollToBottom();
                        } else if (parsed.type === 'error') {
                            fullResponse = 'Error: ' + parsed.content;
                            bubbleEl.innerHTML = renderMarkdown(fullResponse);
                        }
                    } catch (e) {}
                }

                readChunk();
            });
        }

        readChunk();
    }).catch(function(err) {
        fullResponse = 'Connection error: ' + err.message;
        finishMessage(bubbleEl, text, fullResponse);
    });
}

function finishMessage(bubbleEl, query, response) {
    state.isStreaming = false;
    bubbleEl.innerHTML = renderMarkdown(response);
    bubbleEl.innerHTML += '<div class="msg-actions">' +
        '<button class="msg-action-btn" data-action="up">Helpful</button>' +
        '<button class="msg-action-btn" data-action="down">Not helpful</button>' +
        '<button class="msg-action-btn" data-action="copy">Copy</button>' +
        '</div>';

    bubbleEl.querySelectorAll('.msg-action-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var action = btn.getAttribute('data-action');
            if (action === 'copy') {
                navigator.clipboard.writeText(response);
                btn.textContent = 'Copied!';
                setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
                return;
            }
            var siblings = bubbleEl.querySelectorAll('.msg-action-btn[data-action="up"], .msg-action-btn[data-action="down"]');
            siblings.forEach(function(s) { s.classList.remove('active-up', 'active-down'); });
            btn.classList.add(action === 'up' ? 'active-up' : 'active-down');
            fetch('/api/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    conversation_id: state.conversationId,
                    query: query,
                    response: response,
                    sources: state.sources.map(function(s) { return s.page_title; }),
                    rating: action
                })
            });
        });
    });

    state.messages.push({ role: 'assistant', content: response });
    saveHistory();
    scrollToBottom();
}

function renderSources(sources) {
    if (!sources || sources.length === 0) {
        $sourcesContent.innerHTML = '<div class="sources-empty">Sources will appear here when you ask a question.</div>';
        return;
    }
    var html = '';
    for (var i = 0; i < sources.length; i++) {
        var s = sources[i];
        var pct = Math.round((s.score || 0) * 100);
        html += '<div class="source-card">' +
            '<div class="source-title">' + escapeHtml(s.page_title || '') + '</div>' +
            '<div class="source-path">' + escapeHtml(s.source_file || '') + '</div>' +
            (s.section_heading ? '<div class="source-path">Section: ' + escapeHtml(s.section_heading) + '</div>' : '') +
            '<div class="source-score">Relevance: ' + pct + '%</div></div>';
    }
    html += '<div class="retrieval-info"><h4>Retrieval info</h4>' +
        '<div class="retrieval-row">Sources found: ' + sources.length + '</div>' +
        '<div class="retrieval-row">Model: Qwen2.5-14B-AWQ</div>' +
        '<div class="retrieval-row">Retrieval: Hybrid (Dense + BM25)</div></div>';
    $sourcesContent.innerHTML = html;
}

function newChat() {
    state.conversationId = generateId();
    state.messages = [];
    state.sources = [];
    $messages.innerHTML = '';
    $messages.classList.remove('visible');
    $welcome.style.display = '';
    $sourcesContent.innerHTML = '<div class="sources-empty">Sources will appear here when you ask a question.</div>';
    loadHistory();
}

function saveHistory() {
    var userMsg = null;
    for (var i = 0; i < state.messages.length; i++) {
        if (state.messages[i].role === 'user') { userMsg = state.messages[i]; break; }
    }
    var title = userMsg ? userMsg.content.slice(0, 50) : 'Untitled';
    fetch('/api/history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            conversation_id: state.conversationId,
            title: title,
            messages: state.messages,
            message_count: state.messages.length
        })
    }).then(function() { loadHistory(); });
}

function loadHistory() {
    fetch('/api/history').then(function(r) { return r.json(); }).then(function(data) {
        renderHistory(data);
    }).catch(function() {});
}

function renderHistory(conversations) {
    $historyList.innerHTML = '';
    if (!conversations.length) {
        $historyList.innerHTML = '<div style="font-size:12px;color:#999;padding:16px 8px;text-align:center;">No conversations yet</div>';
        return;
    }
    for (var i = 0; i < conversations.length; i++) {
        var conv = conversations[i];
        var isActive = conv.conversation_id === state.conversationId;
        var el = document.createElement('div');
        el.className = 'history-item ' + (isActive ? 'active' : '');
        el.innerHTML = '<div class="title">' + escapeHtml(conv.title) + '</div>' +
            '<div class="time">' + formatTime(conv.updated_at) + '</div>' +
            '<button class="btn-delete" title="Delete">x</button>';
        (function(cid) {
            el.addEventListener('click', function(e) {
                if (e.target.closest('.btn-delete')) return;
                loadConversation(cid);
            });
            el.querySelector('.btn-delete').addEventListener('click', function(e) {
                e.stopPropagation();
                fetch('/api/history/' + cid, { method: 'DELETE' }).then(function() {
                    if (cid === state.conversationId) newChat();
                    else loadHistory();
                });
            });
        })(conv.conversation_id);
        $historyList.appendChild(el);
    }
}

function loadConversation(convId) {
    fetch('/api/history/' + convId).then(function(r) {
        if (!r.ok) return;
        return r.json();
    }).then(function(data) {
        if (!data) return;
        state.conversationId = convId;
        state.messages = data.messages || [];
        $messages.innerHTML = '';
        $welcome.style.display = 'none';
        $messages.classList.add('visible');
        for (var i = 0; i < state.messages.length; i++) {
            appendMessage(state.messages[i].role, state.messages[i].content);
        }
        loadHistory();
        scrollToBottom();
    });
}

function loadStats() {
    var body = document.getElementById('stats-body');
    fetch('/api/feedback/stats').then(function(r) { return r.json(); }).then(function(data) {
        if (data.total === 0) { body.innerHTML = '<p>No feedback collected yet.</p>'; return; }
        var upPct = Math.round((data.up / data.total) * 100);
        body.innerHTML = '<div class="stats-grid">' +
            '<div class="stat-card"><div class="number">' + data.total + '</div><div class="label">Total</div></div>' +
            '<div class="stat-card up"><div class="number">' + data.up + '</div><div class="label">Helpful (' + upPct + '%)</div></div>' +
            '<div class="stat-card down"><div class="number">' + data.down + '</div><div class="label">Not helpful</div></div></div>';
    }).catch(function() { body.innerHTML = '<p>Could not load stats.</p>'; });
}

function appendMessage(role, content) {
    var el = document.createElement('div');
    el.className = 'msg ' + role;
    if (role === 'user') {
        el.innerHTML = '<div class="msg-bubble">' + escapeHtml(content) + '</div>';
    } else {
        el.innerHTML = '<div class="msg-avatar">AI</div>' +
            '<div class="msg-bubble">' + (content ? renderMarkdown(content) : '') + '</div>';
    }
    $messages.appendChild(el);
    return el;
}

function renderMarkdown(text) {
    var html = escapeHtml(text);
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function(m, lang, code) {
        return '<pre><code>' + code.trim() + '</code></pre>';
    });
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function escapeHtml(str) {
    var el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    var d = new Date(isoStr);
    var diff = Date.now() - d;
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return Math.round(diff / 60000) + ' min ago';
    if (diff < 86400000) return Math.round(diff / 3600000) + 'h ago';
    return d.toLocaleDateString('en', { month: 'short', day: 'numeric' });
}

loadHistory();
