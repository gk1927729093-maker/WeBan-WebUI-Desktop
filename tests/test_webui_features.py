"""使用模拟账号验证队列，不登录平台，也不触碰实际账号配置。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path
import tempfile
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import tomli_w

from account_support import account_id, account_log_folder, parse_accounts
from webui_runner import LiveAccountQueue, main as run_queue

TEST_ROOT = Path(__file__).resolve().parents[1] / 'logs' / 'feature-tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)


def fixture_account(name, school='测试学校'):
    return {'tenant_name': school, 'username': name, 'password': 'TEST_PASSWORD'}


def write_config(path, accounts, workers=2):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(tomli_w.dumps({'account': accounts, 'settings': {'max_workers': workers},
                                      'ai': {'enable': False}}), encoding='utf-8')
    temporary.replace(path)


class TemporaryDataTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.clean_fixture)

    def clean_fixture(self):
        self.assertTrue(self.root.is_relative_to(TEST_ROOT.resolve()))
        self.temporary.cleanup()


class ImportParserTests(unittest.TestCase):
    def test_excel_paste_and_leading_zero(self):
        accounts, errors = parse_accounts('\ufeff学号\t密码\n00123\tpass1\n00456\t', '测试学校')
        self.assertFalse(errors)
        self.assertEqual([item['username'] for item in accounts], ['00123', '00456'])
        self.assertEqual(accounts[1]['password'], '00456')

    def test_csv_quoted_password_and_multiple_schools(self):
        accounts, errors = parse_accounts('学校,学号,密码\n测试一校,001,"a,b"\n测试二校,001,c')
        self.assertFalse(errors)
        self.assertEqual(accounts[0]['password'], 'a,b')
        self.assertNotEqual(account_id(accounts[0]), account_id(accounts[1]))
        self.assertNotEqual(account_log_folder(accounts[0]), account_log_folder(accounts[1]))

    def test_malformed_row_does_not_expose_password(self):
        accounts, errors = parse_accounts('001,SECRET\n学校,002,pw,extra')
        self.assertFalse(accounts)
        self.assertEqual(len(errors), 2)
        self.assertNotIn('SECRET', json.dumps(errors))

    def test_space_separated_and_blank_lines(self):
        accounts, errors = parse_accounts('# 说明\n\n001 pw\n002', '测试学校')
        self.assertFalse(errors)
        self.assertEqual(len(accounts), 2)


class BackendTests(TemporaryDataTest):
    def test_chapter_reads_use_the_correct_account_owner(self):
        first, second, third = [fixture_account(name) for name in ('RUNNING', 'OLD_DONE', 'LIVE_DONE')]
        records = [{'id': account_id(first), 'status': 'running'},
                   {'id': account_id(second), 'status': 'completed'},
                   {'id': account_id(third), 'status': 'completed', 'chapter_reader_ready': True}]
        process = SimpleNamespace(poll=lambda: None)
        with patch.object(self.webui, 'task_process', process), patch.object(self.webui, 'task_launch_time', 0), \
                patch.object(self.webui, '_read_task_state', return_value={'updated_at': time.time(), 'accounts': records}):
            self.assertTrue(self.webui._account_needs_worker(account_id(first)))
            self.assertFalse(self.webui._account_needs_worker(account_id(second)))
            self.assertTrue(self.webui._account_needs_worker(account_id(third)))

    def setUp(self):
        super().setUp()
        self.webui = importlib.import_module('webui')
        self.log_root = self.root / 'logs'
        self.log_root.mkdir()
        self.config = self.root / 'config.toml'
        write_config(self.config, [])
        for attribute, value in {'DATA_DIR': self.root, 'CONFIG_FILE': self.config,
                                 'LOG_DIR': self.log_root, 'STATE_FILE': self.log_root / 'webui-state.json',
                                 'task_process': None}.items():
            patcher = patch.object(self.webui, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_import_counts_and_config_sections(self):
        result = asyncio.run(self.webui.import_accounts({'tenant_name': '测试学校',
            'text': '001,pw\n001,pw\n002,pw\n学校,003,pw,extra'}))
        self.assertTrue(result['success'])
        self.assertEqual((result['added'], result['duplicates'], len(result['errors'])), (2, 1, 1))
        self.assertEqual(self.webui.load_config()['ai'], {'enable': False})
        public = asyncio.run(self.webui.get_accounts())
        self.assertNotIn('password', public['accounts'][0])
        self.assertNotIn('token', public['accounts'][0])

    def test_parallel_additions_are_not_lost(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda i: self.webui._store_accounts([fixture_account(f'TEST{i}')]), range(24)))
        self.assertTrue(all(item['success'] for item in results))
        self.assertEqual(len(self.webui.load_config()['account']), 24)

    def test_completed_state_survives_stopping(self):
        first, second = fixture_account('A'), fixture_account('B')
        state = {'accounts': [{'id': account_id(first), **{k: first[k] for k in ('tenant_name', 'username')}, 'status': 'completed'},
                              {'id': account_id(second), **{k: second[k] for k in ('tenant_name', 'username')}, 'status': 'running'}]}
        self.webui.STATE_FILE.write_text(json.dumps(state), encoding='utf-8')
        self.webui._mark_task_stopped()
        actual = self.webui._read_task_state()['accounts']
        self.assertEqual([item['status'] for item in actual], ['completed', 'stopped'])

    def test_logs_are_grouped_and_outside_paths_rejected(self):
        account = fixture_account('001')
        write_config(self.config, [account])
        folder = self.log_root / account_log_folder(account)
        folder.mkdir()
        (folder / 'example.log').write_text('TEST LOG', encoding='utf-8')
        result = asyncio.run(self.webui.get_logs(account_id(account)))
        self.assertEqual(len(result['logs']), 1)
        self.assertEqual(result['logs'][0]['account_id'], account_id(account))
        content = asyncio.run(self.webui.get_log_content(result['logs'][0]['name']))
        self.assertEqual(content['content'], 'TEST LOG')
        with self.assertRaises(self.webui.HTTPException):
            asyncio.run(self.webui.get_log_content('../config.toml'))

    def test_invalid_concurrency_is_rejected(self):
        for value in (0, 51, True, '5'):
            result = asyncio.run(self.webui.update_settings({'max_workers': value}))
            self.assertFalse(result['success'])

    def test_active_import_is_queued_without_process_restart(self):
        class ExistingProcess:
            def poll(self): return None
        process = ExistingProcess()
        with patch.object(self.webui, 'task_process', process):
            result = asyncio.run(self.webui.add_account(fixture_account('NEW')))
            self.assertEqual(result['queued'], 1)
            self.assertIs(self.webui.task_process, process)


class QueueTests(TemporaryDataTest):
    def test_default_restart_skips_completed_and_preserves_scores(self):
        first, second = fixture_account('ALREADY_DONE'), fixture_account('REMAINING')
        config, state = self.root / 'config.toml', self.root / 'state.json'
        write_config(config, [first, second])
        scores = [{'exam_name': '测试考试', 'score': 96, 'full_score': 100, 'taken': True}]
        state.write_text(json.dumps({'accounts': [
            {'id': account_id(first), 'tenant_name': first['tenant_name'], 'username': first['username'],
             'status': 'completed', 'chapter_reader_ready': True, 'current_course': '旧课程',
             'finished_at': 123, 'exam_scores': scores},
            {'id': account_id(second), 'status': 'stopped'}]}), encoding='utf-8')
        calls = []
        worker = lambda account, *args: calls.append(account['username']) or True
        queue = LiveAccountQueue(config, state, worker)
        with ThreadPoolExecutor(max_workers=2) as executor:
            queue.tick(executor)
            for future in queue.futures: future.result(2)
            queue.tick(executor)
        self.assertEqual(calls, ['REMAINING'])
        completed = queue.accounts[account_id(first)]
        self.assertNotIn('chapter_reader_ready', completed)
        self.assertEqual(completed['current_course'], '')
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['exam_scores'], scores)
        self.assertEqual(completed['finished_at'], 123)

        # 再次启动时两个账号均已完成；随后新增的账号仍可正常接入。
        restarted = LiveAccountQueue(config, state, worker)
        third = fixture_account('NEW_ACCOUNT')
        with ThreadPoolExecutor(max_workers=2) as executor:
            restarted.tick(executor)
            self.assertFalse(restarted.futures)
            write_config(config, [first, second, third])
            restarted.tick(executor)
            for future in restarted.futures: future.result(2)
            restarted.tick(executor)
        self.assertEqual(calls, ['REMAINING', 'NEW_ACCOUNT'])
        self.assertEqual(restarted.accounts[account_id(first)]['exam_scores'], scores)

    def test_browser_failure_preserves_completed_accounts(self):
        first, second = fixture_account('ALREADY_DONE'), fixture_account('REMAINING')
        config, state = self.root / 'config.toml', self.root / 'webui-state.json'
        write_config(config, [first, second])
        state.write_text(json.dumps({'accounts': [
            {'id': account_id(first), 'tenant_name': first['tenant_name'], 'username': first['username'],
             'status': 'completed', 'exam_scores': [{'score': 96}]}]}), encoding='utf-8')
        runtime = SimpleNamespace(config_path=config, logs_dir=self.root, logger=Mock(),
                                  check_browser_health=Mock(side_effect=RuntimeError('TEST_BROWSER_ERROR')))
        with patch.dict(sys.modules, {'main': runtime}), patch('webui_runner.WorkerChapterMonitor'), \
                patch.object(sys, 'argv', ['webui_runner.py']), patch('builtins.print'):
            self.assertEqual(run_queue(), 1)
        actual = {item['id']: item for item in json.loads(state.read_text(encoding='utf-8'))['accounts']}
        self.assertEqual(actual[account_id(first)]['status'], 'completed')
        self.assertEqual(actual[account_id(first)]['exam_scores'], [{'score': 96}])
        self.assertEqual(actual[account_id(second)]['status'], 'failed')

    def test_verified_progress_overrides_recovered_error(self):
        config = self.root / 'config.toml'
        account = fixture_account('VERIFIED')
        write_config(config, [account])
        def worker(*args):
            key = account_id(account)
            queue.record_log(key, '中途出现错误，之后已恢复', 'ERROR')
            queue.record_log(key, '最终进度已完成', verification={'complete': True, 'message': '已完成。'})
            return True
        queue = LiveAccountQueue(config, self.root / 'state.json', worker)
        with ThreadPoolExecutor(max_workers=1) as executor:
            queue.tick(executor)
            deadline = time.monotonic() + 2
            while queue.accounts[account_id(account)]['status'] == 'running' and time.monotonic() < deadline:
                time.sleep(0.01)
                queue.tick(executor)
        self.assertEqual(queue.accounts[account_id(account)]['status'], 'completed')
        self.assertTrue(queue.accounts[account_id(account)]['issue'])

    def test_recovered_captcha_retry_is_not_marked_incomplete(self):
        config = self.root / 'config.toml'
        account = fixture_account('RETRY')
        write_config(config, [account])
        queue = LiveAccountQueue(config, self.root / 'state.json', lambda *args: True)
        queue.refresh()
        key = account_id(account)
        queue.record_log(key, '验证码识别失败，正在重试', 'WARNING')
        self.assertFalse(queue.accounts[key]['issue'])
        queue.record_log(key, '网络异常，跳过本门课程', 'WARNING')
        self.assertTrue(queue.accounts[key]['issue'])

    def test_append_during_running_and_after_completion_without_repeating(self):
        config = self.root / 'config.toml'
        state = self.root / 'state.json'
        release_a, release_b = threading.Event(), threading.Event()
        started_a, started_b = threading.Event(), threading.Event()
        calls, log_events = [], []
        accounts = [fixture_account(name) for name in ('A', 'B', 'C', 'D', 'E')]

        def worker(account, settings, ai, index):
            name = account['username']
            calls.append(name)
            if name == 'A':
                started_a.set()
                release_a.wait(4)
            if name == 'B':
                started_b.set()
                release_b.wait(4)
            if name == 'C': return False
            if name == 'D': queue.record_log(account_id(account), '必修课完成 1/2，未达到需求数', 'WARNING')
            queue.record_log(account_id(account), f'{name} 的测试日志')
            return True

        write_config(config, accounts[:1], workers=1)
        queue = LiveAccountQueue(config, state, worker, log_events.append, interval=0.02)
        thread = threading.Thread(target=queue.run)
        thread.start()

        def wait_until(predicate):
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                if predicate(): return
                time.sleep(0.02)
            self.fail('队列状态未在预期时间内更新')

        try:
            self.assertTrue(started_a.wait(2))
            write_config(config, accounts[:2], workers=1)
            wait_until(lambda: account_id(accounts[1]) in queue.accounts)
            self.assertEqual(queue.accounts[account_id(accounts[1])]['status'], 'queued')
            self.assertFalse(started_b.is_set())
            write_config(config, accounts[:2], workers=2)
            self.assertTrue(started_b.wait(2))
            self.assertEqual(calls.count('A'), 1)
            release_b.set()
            wait_until(lambda: queue.accounts[account_id(accounts[1])]['status'] == 'completed')
            self.assertEqual(queue.accounts[account_id(accounts[0])]['status'], 'running')
            write_config(config, accounts[:4], workers=2)
            wait_until(lambda: queue.accounts.get(account_id(accounts[3]), {}).get('status') == 'attention')
            self.assertEqual(queue.accounts[account_id(accounts[2])]['status'], 'failed')
            release_a.set()
            wait_until(lambda: queue.accounts[account_id(accounts[0])]['status'] == 'completed')
            write_config(config, accounts, workers=2)
            wait_until(lambda: queue.accounts.get(account_id(accounts[4]), {}).get('status') == 'completed')
            self.assertTrue(all(calls.count(name) == 1 for name in ('A', 'B', 'C', 'D', 'E')))
            self.assertTrue(any(event['account_id'] == account_id(accounts[1]) for event in log_events))
        finally:
            release_a.set()
            release_b.set()
            queue.stop_event.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        saved = json.loads(state.read_text(encoding='utf-8'))
        self.assertNotIn('TEST_PASSWORD', json.dumps(saved))
        self.assertEqual(len(saved['accounts']), 5)


class AccountLogIsolationTests(TemporaryDataTest):
    def test_same_username_in_different_schools_has_separate_logs(self):
        with patch.dict('os.environ', {'WB_DATA_DIR': str(self.root)}), \
                patch.object(sys, 'argv', ['test-worker', '--data-dir', str(self.root), '--non-interactive']):
            runtime = importlib.import_module('main')
        runtime.logger.remove()

        class FakeClient:
            def __init__(self, tenant_name, *args, **kwargs):
                self.school = tenant_name
                self.log = kwargs['log']
            def login(self): return True
            def simulate_home_page(self): pass
            def sync_answers(self): pass
            def run_project_cycle(self, **kwargs): self.log.info('ONLY_' + self.school)
            def check_cycle_completion(self, *args): return {'complete': True, 'message': '已完成。'}

        first, second = fixture_account('SAME', 'SCHOOL_A'), fixture_account('SAME', 'SCHOOL_B')
        try:
            with patch.object(runtime, 'WeBanClient', FakeClient):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(runtime.run_account, item, {'random_answer': True}, {}, index)
                               for index, item in enumerate((first, second))]
                    self.assertTrue(all(future.result() for future in futures))
            for account, other in ((first, second), (second, first)):
                logfile = next((self.root / 'logs' / account_log_folder(account)).glob('*.log'))
                content = logfile.read_text(encoding='utf-8')
                self.assertIn('ONLY_' + account['tenant_name'], content)
                self.assertNotIn('ONLY_' + other['tenant_name'], content)
        finally:
            runtime.logger.remove()


class CompletionVerificationTests(unittest.TestCase):
    def make_client(self, progress=None, score=100, code='0'):
        from client import WeBanClient
        client = object.__new__(WeBanClient)
        client._project_load_failed = False
        client._cycle_projects = [{'projectName': '测试项目', 'userProjectId': 'TEST'}]
        defaults = {'requiredNum': 2, 'requiredFinishedNum': 2,
                    'pushNum': 0, 'pushFinishedNum': 0, 'optionalNum': 0, 'optionalFinishedNum': 0,
                    'examNum': 1, 'examFinishedNum': 1}
        defaults.update(progress or {})
        client.api = SimpleNamespace(show_progress=lambda _: {'code': code, 'data': defaults},
                                     exam_list_plan=lambda _: {'code': '0', 'data': [{'examScore': score, 'paperScore': 100, 'passScore': 80}]})
        return client

    def test_completed_progress(self):
        result = self.make_client().check_cycle_completion('true', 'true')
        self.assertTrue(result['complete'])
        self.assertEqual(result['exam_scores'][0]['score'], 100)

    def test_incomplete_course(self):
        result = self.make_client({'requiredFinishedNum': 1}).check_cycle_completion('true', 'true')
        self.assertFalse(result['complete'])
        self.assertIn('1/2', result['message'])

    def test_disabled_exam_does_not_block_completion(self):
        self.assertTrue(self.make_client({'examFinishedNum': 0}).check_cycle_completion('true', 'false')['complete'])

    def test_perfect_mode_checks_target_score(self):
        self.assertFalse(self.make_client(score=95).check_cycle_completion('true', 'perfect')['complete'])
        self.assertTrue(self.make_client(score=95).check_cycle_completion('true', 'true')['complete'])

    def test_progress_failure_is_not_completed(self):
        self.assertFalse(self.make_client(code='-1').check_cycle_completion('true', 'true')['complete'])

    def test_completed_attempt_below_pass_score_is_incomplete(self):
        result = self.make_client(score=70).check_cycle_completion('true', 'true')
        self.assertFalse(result['complete'])
        self.assertIn('及格线 80', result['message'])


if __name__ == '__main__':
    unittest.main()
