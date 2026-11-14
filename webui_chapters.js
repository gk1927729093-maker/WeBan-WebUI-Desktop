/* 章节进度按账号独立请求，较早的响应不会覆盖后来选择的账号。 */
const chapterView = { key: '', group: 'running', data: null, version: 0, busy: false, nextRefresh: 0, expanded: new Set() };

function groupChapterAccounts(accounts, states = []) {
    const current = new Map(states.map(item => [item.id, item.status]));
    const groups = { running: [], not_running: [] };
    for (const account of accounts) {
        const status = current.get(account.id) || account.status || 'idle';
        groups[status === 'running' ? 'running' : 'not_running'].push({ ...account, status });
    }
    return groups;
}

function chooseChapterAccount(accounts, preferences) {
    return preferences.find(key => accounts.some(account => account.id === key)) || accounts[0]?.id || '';
}

function updateChapterAccounts(preferredKey = '', refreshSelection = true) {
    const select = document.getElementById('chapter-account');
    if (!select) return;
    if (typeof preferredKey !== 'string') preferredKey = '';
    const groups = groupChapterAccounts(accountView.accounts, accountView.states);
    for (const button of document.querySelectorAll('[data-chapter-group]')) {
        const group = button.dataset.chapterGroup;
        button.textContent = `${group === 'running' ? '运行中' : '未运行'}（${groups[group].length}）`;
        button.setAttribute('aria-pressed', String(group === chapterView.group));
    }
    const accounts = groups[chapterView.group];
    const signature = JSON.stringify([chapterView.group, accounts.map(item => [item.id, item.username, item.tenant_name, item.status])]);
    if (select.dataset.signature === signature && !preferredKey) return;
    const previous = chooseChapterAccount(accounts, [preferredKey, select.value, chapterView.key,
        localStorage.getItem(`chapter-account-${chapterView.group}`), localStorage.getItem('chapter-account')]);
    select.dataset.signature = signature;
    select.replaceChildren(new Option(accounts.length ? '请选择账号' : chapterView.group === 'running' ? '暂无运行中的账号' : '暂无未运行的账号', ''));
    for (const account of accounts) select.add(new Option(`${accountLabel(account)} · ${stateLabels[account.status] || '未开始'}`, account.id));
    select.disabled = !accounts.length;
    select.value = previous;
    if (!accounts.length || chapterView.key !== select.value) {
        void changeChapterAccount(refreshSelection && document.getElementById('page-chapters').classList.contains('active'));
    }
}

function mountChapterGroups() {
    const saved = localStorage.getItem('chapter-group');
    if (saved === 'running' || saved === 'not_running') chapterView.group = saved;
    const tabs = document.createElement('div');
    tabs.className = 'chapter-group-tabs';
    tabs.setAttribute('role', 'group');
    tabs.setAttribute('aria-label', '按账号运行状态筛选');
    tabs.innerHTML = '<button class="chapter-group-button" data-chapter-group="running" type="button" aria-pressed="true">运行中（0）</button><button class="chapter-group-button" data-chapter-group="not_running" type="button" aria-pressed="false">未运行（0）</button>';
    document.querySelector('label[for="chapter-account"]').before(tabs);
    const hint = document.createElement('p');
    hint.className = 'feature-hint';
    hint.textContent = '运行中只显示当前执行任务的账号；未运行包含未开始、排队中、已完成、失败、需检查和已停止的账号。';
    tabs.after(hint);
    for (const button of tabs.querySelectorAll('[data-chapter-group]')) {
        button.addEventListener('click', () => {
            chapterView.group = button.dataset.chapterGroup;
            localStorage.setItem('chapter-group', chapterView.group);
            updateChapterAccounts();
        });
    }
}

async function openChaptersForAccount(key) {
    if (!accountView.accounts.some(account => account.id === key)) await loadAccounts();
    const groups = groupChapterAccounts(accountView.accounts, accountView.states);
    const account = [...groups.running, ...groups.not_running].find(item => item.id === key);
    if (!account) { alert('未找到该账号，请刷新账号列表后重试。'); return; }
    chapterView.group = account.status === 'running' ? 'running' : 'not_running';
    localStorage.setItem('chapter-group', chapterView.group);
    updateChapterAccounts(key, false);
    switchPage('chapters');
    await refreshChapterProgress();
}

async function changeChapterAccount(refresh = true) {
    const select = document.getElementById('chapter-account');
    chapterView.key = select.value;
    localStorage.setItem('chapter-account', chapterView.key);
    if (chapterView.key) localStorage.setItem(`chapter-account-${chapterView.group}`, chapterView.key);
    chapterView.version++;
    chapterView.busy = false;
    chapterView.nextRefresh = 0;
    chapterView.data = null;
    chapterView.expanded = new Set();
    document.getElementById('chapter-projects').replaceChildren();
    document.getElementById('chapter-current-course').hidden = true;
    document.getElementById('chapter-refresh').disabled = !chapterView.key;
    const status = document.getElementById('chapter-sync-status');
    status.className = 'chapter-sync-status';
    status.textContent = chapterView.key || !select.disabled ? '请选择账号查看章节。'
        : chapterView.group === 'running' ? '当前没有运行中的账号。' : '当前没有未运行的账号。';
    if (chapterView.key && refresh) await refreshChapterProgress();
}

async function refreshChapterProgress(force = false) {
    const key = document.getElementById('chapter-account').value;
    if (!key || chapterView.busy) return;
    const version = ++chapterView.version;
    chapterView.busy = true;
    const button = document.getElementById('chapter-refresh');
    const status = document.getElementById('chapter-sync-status');
    button.disabled = true;
    if (!chapterView.data) status.textContent = '正在同步平台章节进度…';
    try {
        const response = await fetch(`/api/accounts/${encodeURIComponent(key)}/chapters${force ? '?refresh=true' : ''}`, {cache: 'no-store'});
        if (!response.ok) throw new Error('该账号暂时无法读取，请稍后刷新。');
        const data = await response.json();
        if (version !== chapterView.version || key !== document.getElementById('chapter-account').value) return;
        chapterView.data = data;
        chapterView.nextRefresh = Date.now() + (data.refreshing ? 2000 : 10000);
        renderChapterProgress();
    } catch (error) {
        if (version !== chapterView.version) return;
        status.className = 'chapter-sync-status chapter-sync-error';
        status.textContent = error.message + (chapterView.data ? ' 已保留上次成功同步的进度。' : '');
        chapterView.nextRefresh = Date.now() + 10000;
    } finally {
        if (version === chapterView.version) {
            chapterView.busy = false;
            button.disabled = false;
        }
    }
}

function renderChapterProgress() {
    const data = chapterView.data;
    if (!data) return;
    const status = document.getElementById('chapter-sync-status');
    const stamp = data.checked_at ? new Date(data.checked_at * 1000).toLocaleString() : '';
    status.className = 'chapter-sync-status' + (data.error ? ' chapter-sync-error' : '');
    if (data.error) status.textContent = data.error + (stamp ? ` 上次成功同步：${stamp}。` : '');
    else if (data.waiting_for_task) status.textContent = '账号正在排队或登录，任务启动后会同步章节进度。';
    else if (data.refreshing) status.textContent = stamp ? `正在更新，当前显示 ${stamp} 的进度。` : '正在同步平台章节进度…';
    else status.textContent = stamp ? `最后同步：${stamp} · ${data.source === 'task' ? '随学习任务同步' : '平台当前进度'}` : '正在等待章节数据…';
    const current = document.getElementById('chapter-current-course');
    current.hidden = !data.current_course;
    current.textContent = data.current_course ? '当前学习：' + data.current_course : '';
    const container = document.getElementById('chapter-projects');
    container.replaceChildren();
    if (!data.projects?.length) {
        if (!data.refreshing && !data.error) container.innerHTML = '<div class="empty-state">该账号暂无可展示的课程项目。</div>';
        return;
    }
    const onlyPending = document.getElementById('chapter-only-pending').checked;
    for (const project of data.projects) {
        const card = document.createElement('section');
        card.className = 'card chapter-project-card';
        card.innerHTML = `<div class="chapter-project-heading"><h2 class="card-title">${escapeHtml(project.name)}</h2><span class="state-badge ${project.completed >= project.total ? 'state-completed' : 'state-running'}">${Number(project.completed)} / ${Number(project.total)} 课</span></div><div class="chapter-progress-track"><div style="width:${Math.min(100, Math.max(0, Number(project.percent) || 0))}%"></div></div><div class="chapter-percent">课程完成 ${Number(project.percent) || 0}%</div>`;
        if (project.exams?.length) {
            const scores = document.createElement('div');
            scores.className = 'chapter-exam-scores';
            scores.textContent = project.exams.map(exam => `${exam.exam_name}：${exam.taken ? Number(exam.score) + ' / ' + Number(exam.full_score) + ' 分' : '尚未考试'}`).join('；');
            card.appendChild(scores);
        }
        if (project.exam_error) {
            const notice = document.createElement('div');
            notice.className = 'chapter-sync-status chapter-sync-error';
            notice.textContent = project.exam_error;
            card.appendChild(notice);
        }
        let displayed = 0;
        for (const chapter of project.chapters || []) {
            const courses = (chapter.courses || []).filter(course => !onlyPending || !course.completed);
            if (onlyPending && !courses.length) continue;
            displayed++;
            const detail = document.createElement('details');
            detail.className = 'chapter-detail';
            const expandKey = `${project.id}:${chapter.id}`;
            detail.open = chapterView.expanded.has(expandKey);
            const percent = chapter.total ? chapter.completed / chapter.total * 100 : 100;
            const isCurrentChapter = data.current_course && chapter.courses.some(course => data.current_course.endsWith(course.name));
            const chapterStatus = chapter.completed >= chapter.total ? '已完成' : (chapter.completed > 0 || isCurrentChapter) ? '进行中' : '未开始';
            detail.innerHTML = `<summary><span class="chapter-name">${escapeHtml(chapter.name)}<span class="chapter-type">${escapeHtml(chapter.type)}</span></span><span class="chapter-count">${Number(chapter.completed)} / ${Number(chapter.total)} ${chapterStatus}</span></summary><div class="chapter-mini-track"><div style="width:${Math.min(100, percent)}%"></div></div>`;
            detail.addEventListener('toggle', () => {
                if (detail.open) chapterView.expanded.add(expandKey);
                else chapterView.expanded.delete(expandKey);
            });
            const list = document.createElement('ul');
            list.className = 'chapter-course-list';
            for (const course of courses) {
                const row = document.createElement('li');
                const currentCourse = !course.completed && data.current_course && data.current_course.endsWith(course.name);
                row.className = 'chapter-course';
                row.innerHTML = `<span class="chapter-course-icon ${course.completed ? 'course-completed' : currentCourse ? 'course-current' : ''}" aria-hidden="true">${course.completed ? '✓' : currentCourse ? '●' : '○'}</span><span class="chapter-course-name">${escapeHtml(course.name)}</span><span class="state-badge ${course.completed ? 'state-completed' : currentCourse ? 'state-running' : 'state-queued'}">${course.completed ? '已完成' : currentCourse ? '正在学习' : '未完成'}</span>`;
                list.appendChild(row);
            }
            detail.appendChild(list);
            card.appendChild(detail);
        }
        if (!displayed) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = onlyPending ? '该项目没有未完成课程。' : '该项目暂无章节明细。';
            card.appendChild(empty);
        }
        container.appendChild(card);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    mountChapterGroups();
    document.addEventListener('accounts-updated', updateChapterAccounts);
    document.addEventListener('account-states-updated', updateChapterAccounts);
    document.querySelector('[data-page="chapters"]').addEventListener('click', async () => {
        if (!accountView.accounts.length) await loadAccounts();
        updateChapterAccounts();
        const key = document.getElementById('chapter-account').value;
        if (chapterView.key !== key) await changeChapterAccount();
        else await refreshChapterProgress();
    });
    document.getElementById('chapter-account').addEventListener('change', () => changeChapterAccount());
    document.getElementById('chapter-refresh').addEventListener('click', () => refreshChapterProgress(true));
    document.getElementById('chapter-only-pending').addEventListener('change', renderChapterProgress);
    document.getElementById('chapter-auto-refresh').addEventListener('change', event => {
        if (event.target.checked) refreshChapterProgress();
    });
    setInterval(() => {
        if (document.getElementById('page-chapters').classList.contains('active') &&
            document.getElementById('chapter-auto-refresh').checked && Date.now() >= chapterView.nextRefresh) {
            refreshChapterProgress();
        }
    }, 1000);
});
