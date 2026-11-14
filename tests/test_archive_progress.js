/* 验证归档时间边界及数据保留，不登录平台，也不改实际账号配置。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const context = { document: { addEventListener() {} } };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'webui_extensions.js'), 'utf8'), context);
const now = 1_800_000_000;
const day = 86400;
const ids = accounts => Array.from(accounts, account => account.id);
const account = (id, secondsAgo, status = 'completed') => ({ id, status, finished_at: now - secondsAgo });

test('完成超过24小时才归档，恰好24小时及以内继续保留', () => {
    const result = context.partitionAccountProgress([
        account('old', day + 0.001), account('boundary', day), account('recent', day - 0.001)
    ], now);
    assert.deepEqual(ids(result.archived), ['old']);
    assert.deepEqual(ids(result.current), ['boundary', 'recent']);
});

test('未完成或异常账号不会因时间较早而归档', () => {
    const accounts = ['running', 'queued', 'failed', 'attention', 'stopped', 'idle', 'cancelled']
        .map(status => account(status, 2 * day, status));
    const result = context.partitionAccountProgress(accounts, now);
    assert.equal(result.archived.length, 0);
    assert.deepEqual(ids(result.current), ids(accounts));
});

test('缺少有效完成时间的账号保留在当前列表', () => {
    const accounts = [undefined, null, 0, -1, '', '100', true, NaN, Infinity, now + 1]
        .map((finished_at, index) => ({ id: String(index), status: 'completed', finished_at }));
    assert.equal(context.partitionAccountProgress(accounts, now).archived.length, 0);
});

test('只根据完成时间归档，不使用启动或加入队列的时间', () => {
    const result = context.partitionAccountProgress([
        { ...account('recent', 60), started_at: now - 3 * day, queued_at: now - 4 * day }
    ], now);
    assert.deepEqual(ids(result.current), ['recent']);
});

test('跨过24小时时自动移入归档，不需要修改原始记录', () => {
    const records = [Object.freeze(account('ready', day - 1))];
    assert.equal(context.partitionAccountProgress(records, now).archived.length, 0);
    assert.equal(context.partitionAccountProgress(records, now + 2).archived.length, 1);
    assert.equal(records[0].finished_at, now - day + 1);
});

test('归档按完成时间倒序，保留分数、核验结果和日志字段', () => {
    const first = Object.freeze({ ...account('older', 3 * day), exam_scores: [{ score: 96 }],
        verification: { complete: true }, last_log: '完成', issue: '', current_course: '' });
    const second = Object.freeze(account('newer', 2 * day));
    const records = Object.freeze([first, second]);
    const result = context.partitionAccountProgress(records, now);
    assert.deepEqual(ids(result.archived), ['newer', 'older']);
    assert.deepEqual(ids(records), ['older', 'newer']);
    assert.strictEqual(result.archived[1], first);
    assert.equal(result.archived[1].exam_scores[0].score, 96);
    assert.equal(context.finalScoreText(result.archived[1]), '最终成绩：96 / 100 分');
});

test('归档支持按学号或学校搜索，空搜索显示全部', () => {
    const records = [{ id: 'a', username: '00123', tenant_name: '测试学校' },
        { id: 'b', username: 'AbC456', tenant_name: '另一所学校' }];
    assert.deepEqual(ids(context.filterArchivedProgress(records, '001')), ['a']);
    assert.deepEqual(ids(context.filterArchivedProgress(records, '测试学校')), ['a']);
    assert.deepEqual(ids(context.filterArchivedProgress(records, ' abc ')), ['b']);
    assert.deepEqual(ids(context.filterArchivedProgress(records, ' ')), ['a', 'b']);
});
