/* 批量导入、持续队列和账号日志界面。所有账号文本均通过 textContent 或转义显示。 */
const accountView = { accounts: [], states: [], logs: [], history: [], lastSequence: 0, runId: '' };
const stateLabels = { idle: '未开始', queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', attention: '需检查', stopped: '已停止', cancelled: '已移除' };
const COMPLETED_ARCHIVE_DELAY = 24 * 60 * 60;

function partitionAccountProgress(accounts, now = Date.now() / 1000) {
    const current = [], archived = [];
    for (const account of accounts) {
        const finished = account.finished_at;
        const eligible = account.status === 'completed' && typeof finished === 'number'
            && Number.isFinite(finished) && finished > 0 && now - finished > COMPLETED_ARCHIVE_DELAY;
        (eligible ? archived : current).push(account);
    }
    archived.sort((first, second) => second.finished_at - first.finished_at);
    return { current, archived };
}

function filterArchivedProgress(accounts, search = '') {
    const query = search.trim().toLocaleLowerCase();
    return accounts.filter(account => !query || accountLabel(account).toLocaleLowerCase().includes(query));
}

function accountLabel(account) {
    return `${account.username || '账号'} · ${account.tenant_name || '未填写学校'}`;
}

function accountBadge(status) {
    return `<span class="state-badge state-${Object.hasOwn(stateLabels, status) ? status : 'idle'}">${stateLabels[status] || '未开始'}</span>`;
}

function finalScoreText(account) {
    if (account.status !== 'completed') return '';
    const scores = (account.exam_scores || account.verification?.exam_scores || []).filter(item => item.taken !== false);
    if (!scores.length) return '';
    return '最终成绩：' + scores.map(item => `${scores.length > 1 ? item.exam_name + ' ' : ''}${Number(item.score)} / ${Number(item.full_score || 100)} 分`).join('；');
}

function updateAccountFilters() {
    for (const id of ['realtime-account-filter', 'history-account-filter']) {
        const select = document.getElementById(id);
        const previous = select.value;
        const known = new Map(accountView.accounts.map(item => [item.id, accountLabel(item)]));
        for (const state of accountView.states) known.set(state.id, accountLabel(state));
        for (const log of accountView.history) {
            if (log.account_id) known.set(log.account_id, accountLabel(log));
        }
        const signature = JSON.stringify([...known]);
        if (select.dataset.optionsSignature === signature) continue;
        select.dataset.optionsSignature = signature;
        select.replaceChildren(new Option('全部账号', 'all'), new Option('系统日志', 'system'));
        for (const [key, label] of known) select.add(new Option(label, key));
        if ([...select.options].some(option => option.value === previous)) select.value = previous;
    }
}

function createProgressRow(account, archived = false) {
    const item = document.createElement('div');
    item.className = 'account-item account-progress-row';
    const finished = account.finished_at ? ` · ${new Date(account.finished_at * 1000).toLocaleString()} ${account.status === 'completed' ? '完成' : '结束'}` : '';
    item.innerHTML = `<div class="account-info"><div class="account-detail"><span class="account-username">${escapeHtml(account.username)}</span><span class="account-school">${escapeHtml(account.tenant_name)}</span></div><div class="account-message">${escapeHtml(account.message || '')}${escapeHtml(finished)}</div><div class="account-message">${escapeHtml(account.issue || account.last_log || '')}</div></div><div class="account-actions">${accountBadge(account.status)}<button class="btn btn-secondary btn-sm" type="button">查看日志</button></div>`;
    item.querySelector('button').addEventListener('click', async () => {
        if (archived) {
            switchPage('logs');
            await loadLogs();
            document.getElementById('history-account-filter').value = account.id;
            renderHistory();
        } else {
            document.getElementById('realtime-account-filter').value = account.id;
            renderRealtimeLogs();
            document.getElementById('realtime-logs').scrollIntoView({ block: 'nearest' });
        }
    });
    const chaptersButton = document.createElement('button');
    chaptersButton.type = 'button';
    chaptersButton.className = 'btn btn-secondary btn-sm';
    chaptersButton.textContent = '章节进度';
    chaptersButton.addEventListener('click', () => openChaptersForAccount(account.id));
    item.querySelector('.account-actions').appendChild(chaptersButton);
    const score = finalScoreText(account);
    if (score) {
        const scoreElement = document.createElement('div');
        scoreElement.className = 'account-score';
        scoreElement.textContent = score;
        item.querySelector('.account-info').appendChild(scoreElement);
    }
    return item;
}

function renderProgress(accounts = partitionAccountProgress(accountView.states).current) {
    const list = document.getElementById('account-progress');
    list.replaceChildren();
    if (!accounts.length) {
        list.innerHTML = `<div class="empty-state">${accountView.states.length ? '当前暂无未完成或近期完成的账号，历史完成记录可在“已完成归档”查看。' : '启动任务后，这里会分别显示每个账号的进度和完成状态。'}</div>`;
        return;
    }
    for (const account of accounts) list.appendChild(createProgressRow(account));
}

function renderArchivedProgress(archived = partitionAccountProgress(accountView.states).archived) {
    const list = document.getElementById('archive-progress');
    if (!list) return;
    const visible = filterArchivedProgress(archived, document.getElementById('archive-search').value);
    document.getElementById('archive-count').textContent = `已归档 ${archived.length} 个账号，当前显示 ${visible.length} 个。按完成时间从近到远排列。`;
    list.replaceChildren();
    if (!visible.length) {
        list.innerHTML = `<div class="empty-state">${archived.length ? '没有符合搜索条件的已归档账号。' : '暂无完成超过 24 小时的账号，最近完成的账号仍保留在控制台。'}</div>`;
        return;
    }
    for (const account of visible) list.appendChild(createProgressRow(account, true));
}

function mountCompletedArchive() {
    if (document.getElementById('page-archive')) return;
    const navigation = document.createElement('button');
    navigation.type = 'button';
    navigation.className = 'nav-item';
    navigation.dataset.page = 'archive';
    navigation.innerHTML = '<svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M4 8h16v12H4V8zm-1-5h18v5H3V3zm6 9h6"></path></svg><span>已完成归档</span>';
    navigation.addEventListener('click', () => {
        switchPage('archive');
        renderArchivedProgress();
    });
    document.querySelector('[data-page="chapters"]').after(navigation);
    const page = document.createElement('div');
    page.id = 'page-archive';
    page.className = 'page';
    page.innerHTML = '<section class="card"><h2 class="card-title">已完成归档</h2><p class="feature-hint">完成超过 24 小时的账号自动收录在这里，24 小时内完成的暂留控制台。完成时间、最终分数、章节进度和日志均保留，再次启动任务仍默认跳过已完成账号。</p><label class="form-label" for="archive-search">搜索已归档账号</label><input id="archive-search" class="form-input" type="search" placeholder="输入学号或学校名称"><p id="archive-count" class="archive-count" aria-live="polite"></p><div id="archive-progress" class="account-list"></div></section>';
    document.querySelector('main.main').appendChild(page);
    document.getElementById('archive-search').addEventListener('input', () => renderArchivedProgress());
    const hint = document.createElement('p');
    hint.className = 'feature-hint';
    hint.textContent = '这里保留未完成和最近 24 小时内完成的账号，完成超过 24 小时后自动移入“已完成归档”。';
    document.getElementById('account-progress').before(hint);
}

async function loadTaskStatus() {
    try {
        const response = await fetch('/api/task/status');
        if (!response.ok) throw new Error('状态读取失败');
        const data = await response.json();
        accountView.states = data.accounts || [];
        document.dispatchEvent(new Event('account-states-updated'));
        const groups = partitionAccountProgress(accountView.states);
        const counts = data.counts || {};
        const status = document.getElementById('task-status');
        status.className = `status ${data.running ? 'status-running' : 'status-stopped'}`;
        let label = data.running ? '运行中，可继续添加账号' : '已停止';
        if (data.all_finished) {
            if (counts.failed || counts.attention) label = '本批任务已结束，部分账号需检查';
            else if (counts.completed === accountView.states.length) label = data.running ? '全部完成，等待新增账号' : '本批账号已完成';
        }
        status.querySelector('[data-i18n]').textContent = label;
        document.getElementById('btn-start').disabled = data.running;
        document.getElementById('btn-stop').disabled = !data.running;
        const displayCounts = { ...counts, completed: groups.current.filter(item => item.status === 'completed').length, archived: groups.archived.length };
        const summary = [['queued', '排队中'], ['running', '运行中'], ['completed', '近期完成'], ['attention', '需检查'], ['failed', '失败'], ['archived', '已归档']];
        document.getElementById('account-summary').innerHTML = summary.map(([key, text]) => {
            const content = `<div class="summary-number">${Number(displayCounts[key] || 0)}</div><div class="summary-label">${text}</div>`;
            return key === 'archived' ? `<button id="archive-summary-link" class="summary-tile archive-summary-link" type="button" title="查看已完成归档">${content}</button>` : `<div class="summary-tile">${content}</div>`;
        }).join('');
        document.getElementById('archive-summary-link').addEventListener('click', () => {
            switchPage('archive');
            renderArchivedProgress();
        });
        updateAccountFilters();
        renderProgress(groups.current);
        renderArchivedProgress(groups.archived);
        if (document.getElementById('page-accounts').classList.contains('active') ||
            document.getElementById('page-chapters').classList.contains('active')) await loadAccounts();
    } catch (error) { console.error('读取任务状态失败', error); }
}

async function loadAccounts() {
    try {
        const response = await fetch('/api/accounts');
        const data = await response.json();
        accountView.accounts = data.accounts || [];
        const list = document.getElementById('account-list');
        list.replaceChildren();
        if (!accountView.accounts.length) list.innerHTML = '<div class="empty-state">还没有账号，可以在上方批量导入或单个添加。</div>';
        for (const account of accountView.accounts) {
            const item = document.createElement('div');
            item.className = 'account-item account-progress-row';
            item.innerHTML = `<div class="account-info"><div class="account-school">${escapeHtml(account.tenant_name)}</div><div class="account-username">${escapeHtml(account.username)}</div><div class="account-message">${escapeHtml(account.message || '')}</div></div><div class="account-actions">${accountBadge(account.status)}<button type="button" class="btn btn-danger btn-sm" ${account.status === 'running' ? 'disabled' : ''}>删除</button></div>`;
            item.querySelector('button').addEventListener('click', () => deleteAccount(account.username, account.tenant_name));
            const chaptersButton = document.createElement('button');
            chaptersButton.type = 'button';
            chaptersButton.className = 'btn btn-secondary btn-sm';
            chaptersButton.textContent = '章节进度';
            chaptersButton.addEventListener('click', () => openChaptersForAccount(account.id));
            item.querySelector('.account-actions').prepend(chaptersButton);
            const score = finalScoreText(account);
            if (score) {
                const scoreElement = document.createElement('div');
                scoreElement.className = 'account-score';
                scoreElement.textContent = score;
                item.querySelector('.account-info').appendChild(scoreElement);
            }
            list.appendChild(item);
        }
        updateAccountFilters();
        document.dispatchEvent(new Event('accounts-updated'));
    } catch (error) { console.error('读取账号失败', error); }
}

function renderRealtimeLogs() {
    const selected = document.getElementById('realtime-account-filter').value;
    const list = document.getElementById('realtime-logs');
    list.replaceChildren();
    const filtered = accountView.logs.filter(log => selected === 'all' || (selected === 'system' ? !log.account_id : log.account_id === selected));
    for (const log of filtered.slice(-600)) appendLogElement(list, log);
    if (!filtered.length) {
        const empty = document.createElement('div');
        empty.className = 'log-line';
        empty.dataset.empty = 'true';
        empty.textContent = '该账号暂无实时日志，之前运行的记录可在“日志查看”中按账号查看。';
        list.appendChild(empty);
    }
    list.scrollTop = list.scrollHeight;
}

function appendLogElement(list, log) {
    list.querySelector('[data-empty]')?.remove();
    const line = document.createElement('div');
    line.className = 'log-line' + (log.level === 'ERROR' ? ' log-error' : log.level === 'SUCCESS' ? ' log-success' : '');
    const account = accountView.accounts.find(item => item.id === log.account_id) || accountView.states.find(item => item.id === log.account_id);
    line.textContent = (account ? `[${account.username}] ` : '') + log.line;
    list.appendChild(line);
}

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws/logs`);
    ws.onmessage = event => {
        let log;
        try { log = JSON.parse(event.data); } catch { log = { line: event.data, account_id: '' }; }
        if (log.sequence && log.sequence <= accountView.lastSequence) return;
        accountView.lastSequence = log.sequence || accountView.lastSequence;
        accountView.logs.push(log);
        if (accountView.logs.length > 5000) accountView.logs.splice(0, accountView.logs.length - 5000);
        const selected = document.getElementById('realtime-account-filter').value;
        if (selected === 'all' || (selected === 'system' ? !log.account_id : log.account_id === selected)) {
            const list = document.getElementById('realtime-logs');
            const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
            appendLogElement(list, log);
            while (list.children.length > 600) list.firstElementChild.remove();
            if (nearBottom) list.scrollTop = list.scrollHeight;
        }
    };
    ws.onclose = () => setTimeout(connectWebSocket, 3000);
}

async function loadLogs() {
    try {
        const data = await (await fetch('/api/logs')).json();
        accountView.history = data.logs || [];
        updateAccountFilters();
        renderHistory();
    } catch (error) { console.error('读取日志失败', error); }
}

function renderHistory() {
    const selected = document.getElementById('history-account-filter').value;
    const list = document.getElementById('log-list');
    list.replaceChildren();
    const groups = new Map();
    for (const log of accountView.history) {
        if (selected !== 'all' && (selected === 'system' ? !!log.account_id : log.account_id !== selected)) continue;
        const key = log.account_id || 'system';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(log);
    }
    if (!groups.size) list.innerHTML = '<div class="empty-state">该账号暂无历史日志。</div>';
    for (const [key, files] of groups) {
        const title = document.createElement('div');
        title.className = 'log-group-title';
        title.textContent = key === 'system' ? '系统日志' : accountLabel(files[0]);
        list.appendChild(title);
        for (const log of files) {
            const row = document.createElement('div');
            row.className = 'account-item account-progress-row';
            row.innerHTML = `<div class="account-info"><div class="account-username">${escapeHtml(log.name.split('/').pop())}</div><div class="account-message">${formatBytes(log.size)} · ${new Date(log.modified * 1000).toLocaleString()}</div></div><button class="btn btn-secondary btn-sm" type="button">查看内容</button>`;
            row.querySelector('button').addEventListener('click', async () => {
                const response = await fetch(`/api/logs/content?name=${encodeURIComponent(log.name)}`);
                if (!response.ok) { alert('无法读取该日志文件。'); return; }
                const result = await response.json();
                document.getElementById('history-log-name').textContent = (key === 'system' ? '系统' : accountLabel(log)) + ' / ' + log.name.split('/').pop();
                const content = document.getElementById('history-log-content');
                content.hidden = false;
                content.textContent = (result.truncated ? '仅显示最近 400 KB 日志。\n' : '') + result.content;
                content.scrollIntoView({ block: 'nearest' });
            });
            list.appendChild(row);
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    mountCompletedArchive();
    document.querySelector('[data-page="logs"]').addEventListener('click', loadLogs);
    document.querySelector('[data-page="accounts"]').addEventListener('click', loadAccounts);
    document.getElementById('realtime-account-filter').addEventListener('change', renderRealtimeLogs);
    document.getElementById('history-account-filter').addEventListener('change', renderHistory);
    document.getElementById('batch-school').addEventListener('focus', async () => {
        await loadSchools();
        const options = document.getElementById('batch-schools');
        options.replaceChildren(...schoolNames.map(name => new Option(name, name)));
    });
    document.getElementById('batch-file').addEventListener('change', async event => {
        const file = event.target.files[0];
        if (!file) return;
        if (file.size > 2_000_000) { alert('文件不能超过 2 MB。'); event.target.value = ''; return; }
        const bytes = await file.arrayBuffer();
        let text;
        try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
        catch { text = new TextDecoder('gb18030').decode(bytes); }
        document.getElementById('batch-accounts').value = text;
    });
    document.getElementById('form-import-accounts').addEventListener('submit', async event => {
        event.preventDefault();
        const button = document.getElementById('btn-import');
        const resultElement = document.getElementById('import-result');
        button.disabled = true;
        try {
            const response = await fetch('/api/accounts/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tenant_name: document.getElementById('batch-school').value, text: document.getElementById('batch-accounts').value }) });
            const result = await response.json();
            const errors = result.errors || [];
            resultElement.className = 'import-result' + ((!result.success || errors.length) ? ' error' : '');
            resultElement.textContent = `新增 ${result.added || 0} 个，跳过重复 ${result.duplicates || 0} 个，格式错误 ${errors.length} 行。\n${result.message || ''}` + errors.map(error => `\n第 ${error.line} 行：${error.message}`).join('');
            if (result.success && !errors.length) {
                document.getElementById('batch-accounts').value = '';
                document.getElementById('batch-file').value = '';
            }
            await loadAccounts();
            await loadTaskStatus();
        } catch (error) {
            resultElement.className = 'import-result error';
            resultElement.textContent = '导入失败：' + error.message;
        } finally { button.disabled = false; }
    });
});
