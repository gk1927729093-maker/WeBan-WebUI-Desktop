/* 使用模拟状态验证账号分组、选择及异步响应隔离，不访问实际学习平台。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'webui_chapters.js'), 'utf8');
const account = (id, status = 'idle') => ({ id, username: id, tenant_name: '测试学校', status });
const ids = accounts => Array.from(accounts, item => item.id);

function setup(accounts = [], states = []) {
    const storage = new Map();
    const ui = { active: false, requests: [] };
    const element = () => ({ dataset: {}, value: '', disabled: false, hidden: false,
        textContent: '', innerHTML: '', attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        replaceChildren(...children) { this.children = children; } });
    const select = { ...element(), options: [],
        replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; },
        add(option) { this.options.push(option); } };
    const buttons = ['running', 'not_running'].map(group => ({ ...element(), dataset: { chapterGroup: group } }));
    const nodes = { 'chapter-account': select,
        'page-chapters': { classList: { contains: () => ui.active } } };
    for (const id of ['chapter-projects', 'chapter-current-course', 'chapter-refresh', 'chapter-sync-status']) nodes[id] = element();
    const context = vm.createContext({
        accountView: { accounts, states },
        stateLabels: { running: '运行中', idle: '未开始', completed: '已完成', failed: '失败', queued: '排队中' },
        accountLabel: item => `${item.username} · ${item.tenant_name}`,
        localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)) },
        document: { addEventListener() {}, getElementById: id => nodes[id], querySelectorAll: () => buttons },
        Option: class { constructor(text, value) { this.text = text; this.value = value; } },
        switchPage: name => { ui.active = name === 'chapters'; },
        loadAccounts: async () => {},
        alert: message => { throw new Error(message); },
        fetch: async url => {
            ui.requests.push(url);
            return { ok: true, json: async () => ({ account_id: url.split('/')[3], checked_at: 123, projects: [] }) };
        },
    });
    vm.runInContext(source, context);
    return { context, view: vm.runInContext('chapterView', context), nodes, buttons, select, storage, ui };
}

test('仅正在执行的账号属于运行中，其他状态全部归入未运行', () => {
    const statuses = ['running', 'idle', 'queued', 'completed', 'failed', 'attention', 'stopped', 'cancelled'];
    const h = setup();
    const groups = h.context.groupChapterAccounts(statuses.map(status => account(status, status)));
    assert.deepEqual(ids(groups.running), ['running']);
    assert.deepEqual(ids(groups.not_running), statuses.slice(1));
});

test('使用最新任务状态，完成或重试后能立即改变分组', () => {
    const h = setup();
    const groups = h.context.groupChapterAccounts([account('done', 'running'), account('retry', 'failed')],
        [{ id: 'done', status: 'completed' }, { id: 'retry', status: 'running' }]);
    assert.deepEqual(ids(groups.running), ['retry']);
    assert.deepEqual(ids(groups.not_running), ['done']);
});

test('仅展示仍在账号管理中的账号，且不会改写原始状态', () => {
    const records = Object.freeze([Object.freeze(account('saved'))]);
    const h = setup();
    const groups = h.context.groupChapterAccounts(records,
        [{ id: 'saved', status: 'running' }, { id: 'deleted', status: 'completed' }]);
    assert.deepEqual(ids(groups.running), ['saved']);
    assert.equal(groups.not_running.length, 0);
    assert.equal(records[0].status, 'idle');
});

test('分组刷新保留当前选择，并更新两个分组的数量', () => {
    const h = setup([account('first', 'running'), account('second', 'running'), account('done', 'completed')]);
    h.context.updateChapterAccounts('second');
    assert.equal(h.select.value, 'second');
    h.context.updateChapterAccounts();
    assert.equal(h.select.value, 'second');
    assert.equal(h.buttons[0].textContent, '运行中（2）');
    assert.equal(h.buttons[1].textContent, '未运行（1）');
    assert.equal(h.ui.requests.length, 0);
});

test('切换分组时恢复该组上次查看的账号', () => {
    const h = setup([account('live', 'running'), account('done1', 'completed'), account('done2', 'completed')]);
    h.context.updateChapterAccounts();
    h.storage.set('chapter-account-not_running', 'done2');
    h.view.group = 'not_running';
    h.context.updateChapterAccounts();
    assert.equal(h.select.value, 'done2');
    assert.equal(h.buttons[1].attributes['aria-pressed'], 'true');
    assert.deepEqual(h.select.options.slice(1).map(option => option.value), ['done1', 'done2']);
});

test('选中账号完成后移出运行中，清除旧章节；页面未打开时不查询平台', () => {
    const h = setup([account('first', 'running'), account('second', 'running')]);
    h.context.updateChapterAccounts('first');
    h.view.data = { account_id: 'first' };
    h.context.accountView.states = [{ id: 'first', status: 'completed' }, { id: 'second', status: 'running' }];
    h.context.updateChapterAccounts();
    assert.equal(h.select.value, 'second');
    assert.equal(h.view.key, 'second');
    assert.equal(h.view.data, null);
    assert.equal(h.ui.requests.length, 0);
});

test('运行中没有账号时清除旧进度并显示空组提示', () => {
    const h = setup([account('live', 'running')]);
    h.context.updateChapterAccounts();
    h.context.accountView.states = [{ id: 'live', status: 'completed' }];
    h.context.updateChapterAccounts();
    assert.equal(h.select.value, '');
    assert.equal(h.select.disabled, true);
    assert.equal(h.nodes['chapter-refresh'].disabled, true);
    assert.equal(h.view.data, null);
    assert.equal(h.nodes['chapter-sync-status'].textContent, '当前没有运行中的账号。');
});

test('账号自动换组后，旧账号较晚返回的响应不会覆盖新账号', async () => {
    const h = setup([account('first', 'running'), account('second', 'running')]);
    h.context.updateChapterAccounts('first');
    h.ui.active = true;
    const pending = [];
    h.context.fetch = url => new Promise(resolve => pending.push({ url, resolve }));
    const oldRead = h.context.refreshChapterProgress();
    let newRead;
    const change = h.context.changeChapterAccount;
    h.context.changeChapterAccount = (...args) => (newRead = change(...args));
    h.context.accountView.states = [{ id: 'first', status: 'completed' }, { id: 'second', status: 'running' }];
    h.context.updateChapterAccounts();
    assert.equal(pending.length, 2);
    pending[0].resolve({ ok: true, json: async () => ({ account_id: 'first', checked_at: 123, projects: [] }) });
    await oldRead;
    assert.equal(h.view.data, null);
    pending[1].resolve({ ok: true, json: async () => ({ account_id: 'second', checked_at: 123, projects: [] }) });
    await newRead;
    assert.equal(h.view.data.account_id, 'second');
});

test('从归档进入指定已完成账号时自动切到未运行组并选中该账号', async () => {
    const h = setup([account('live', 'running'), account('done1', 'completed'), account('done2', 'completed')]);
    h.context.updateChapterAccounts();
    await h.context.openChaptersForAccount('done2');
    assert.equal(h.view.group, 'not_running');
    assert.equal(h.select.value, 'done2');
    assert.equal(h.view.data.account_id, 'done2');
    assert.equal(h.ui.requests.length, 1);
    assert.equal(h.storage.get('chapter-group'), 'not_running');
});
