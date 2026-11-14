"""章节查询测试使用模拟接口，不登录真实账号。"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from account_support import account_id
from chapter_progress import (ChapterStore, IdleChapterService, ProgressReadError,
                              WorkerChapterMonitor, collect_chapters)

TEST_ROOT = Path(__file__).resolve().parents[1] / 'logs' / 'feature-tests'
TEST_ROOT.mkdir(parents=True, exist_ok=True)
ACCOUNT = {'tenant_name': '测试学校', 'username': 'CHAPTER_TEST', 'password': 'PRIVATE_PASSWORD'}


def ok(data): return {'code': '0', 'data': data}


class FakeAPI:
    def __init__(self, flat=False):
        self.flat = flat
        self.done = 1
        self.calls = []

    def list_my_project(self): return ok([{'userProjectId': 'P1', 'projectName': '测试项目'}])
    def list_completion(self): return ok([])
    def show_progress(self, project):
        return ok({'requiredNum': 2, 'requiredFinishedNum': self.done, 'pushNum': 0,
                   'pushFinishedNum': 0, 'optionalNum': 0, 'optionalFinishedNum': 0})
    def get_project_simple(self, project): return ok({'projectMode': 2 if self.flat else 1})
    def list_category(self, project, kind): return ok([{'categoryCode': 'C1', 'categoryName': '测试章节'}])
    def list_course(self, project, category, kind):
        self.calls.append(('list_course', project, category, kind))
        return ok([{'resourceId': 'A', 'resourceName': '第一节', 'finished': 1, 'userCourseId': 'PRIVATE_COURSE_RECORD'},
                   {'resourceId': 'B', 'resourceName': '第二节', 'finished': 1 if self.done == 2 else 2}])
    def list_flat_course(self, project, kind, page, size):
        self.calls.append(('flat', page))
        first = {'resourceId': 'A', 'resourceName': '第一节', 'finished': 1, 'categoryName': '第一章'}
        second = {'resourceId': 'B', 'resourceName': '第二节', 'finished': 2, 'categoryName': '第二章'}
        return ok({'totalPages': 2, 'paginateData': [first] if page == 1 else [first, second]})


class ChapterFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEST_ROOT)
        self.root = Path(self.temporary.name).resolve()
        self.store = ChapterStore(self.root / 'chapters')
        self.addCleanup(self.cleanup_fixture)

    def cleanup_fixture(self):
        self.assertTrue(self.root.is_relative_to(TEST_ROOT.resolve()))
        self.temporary.cleanup()


class CollectionTests(unittest.TestCase):
    def test_final_exam_score_is_included(self):
        api = FakeAPI()
        original = api.show_progress
        def progress(project):
            result = original(project)
            result['data'].update(examNum=1, examFinishedNum=1)
            return result
        api.show_progress = progress
        api.exam_list_plan = lambda project: ok([{'examPlanName': '结课考试', 'examScore': 96,
                                                 'passScore': 80, 'paperScore': 100, 'examFinishNum': 1}])
        exam = collect_chapters(api, ACCOUNT)['projects'][0]['exams'][0]
        self.assertEqual((exam['score'], exam['full_score'], exam['taken']), (96, 100, True))

    def test_chapter_and_lesson_completion(self):
        data = collect_chapters(FakeAPI(), ACCOUNT)
        project = data['projects'][0]
        self.assertEqual((project['completed'], project['total'], project['percent']), (1, 2, 50))
        self.assertEqual([item['completed'] for item in project['chapters'][0]['courses']], [True, False])
        serialized = json.dumps(data)
        self.assertNotIn('PRIVATE_PASSWORD', serialized)
        self.assertNotIn('PRIVATE_COURSE_RECORD', serialized)

    def test_flat_pages_are_grouped_and_deduplicated(self):
        api = FakeAPI(flat=True)
        data = collect_chapters(api, ACCOUNT)
        self.assertEqual(len(data['projects'][0]['chapters']), 2)
        self.assertEqual(sum(chapter['total'] for chapter in data['projects'][0]['chapters']), 2)
        self.assertEqual(api.calls, [('flat', 1), ('flat', 2)])

    def test_missing_progress_is_not_treated_as_zero(self):
        api = FakeAPI()
        api.show_progress = lambda project: ok({})
        with self.assertRaises(ProgressReadError): collect_chapters(api, ACCOUNT)

    def test_list_failure_does_not_report_completed(self):
        api = FakeAPI()
        api.list_course = lambda *args: {'code': '-1', 'data': []}
        with self.assertRaises(ProgressReadError): collect_chapters(api, ACCOUNT)

    def test_no_projects_is_valid_empty_result(self):
        api = FakeAPI()
        api.list_my_project = lambda: ok([])
        self.assertEqual(collect_chapters(api, ACCOUNT)['projects'], [])


class IdleServiceTests(ChapterFixture):
    def test_completed_account_can_be_viewed_while_another_is_running(self):
        other = {**ACCOUNT, 'username': 'OTHER_RUNNING'}
        factory = Mock(return_value=SimpleNamespace(api=FakeAPI()))
        service = self.make_service(factory, lambda key: key == account_id(other))
        service.request(ACCOUNT, {})
        service.futures[account_id(ACCOUNT)].result(2)
        self.assertTrue(service.request(other, {})['waiting_for_task'])
        factory.assert_called_once()

    def make_service(self, factory, running=lambda key: False):
        service = IdleChapterService(self.store, running, factory)
        self.addCleanup(service.close)
        return service

    def test_cached_login_is_reused_and_new_progress_is_loaded(self):
        api = FakeAPI()
        factory = Mock(return_value=SimpleNamespace(api=api))
        service = self.make_service(factory)
        key = account_id(ACCOUNT)
        service.request(ACCOUNT, {})
        service.futures[key].result(2)
        self.assertEqual(self.store.read(key)['projects'][0]['completed'], 1)
        self.assertFalse(service.request(ACCOUNT, {})['refreshing'])
        factory.assert_called_once()
        cached = self.store.read(key)
        cached['checked_at'] -= 20
        self.store.write(key, cached)
        api.done = 2
        service.request(ACCOUNT, {})
        service.futures[key].result(2)
        self.assertEqual(self.store.read(key)['projects'][0]['completed'], 2)
        factory.assert_called_once()

    def test_running_account_never_triggers_another_login(self):
        factory = Mock()
        service = self.make_service(factory, lambda key: True)
        result = service.request(ACCOUNT, {})
        self.assertTrue(result['waiting_for_task'])
        self.assertFalse(service.futures)
        factory.assert_not_called()
        self.assertTrue(self.store.path(account_id(ACCOUNT), '.request').exists())

    def test_read_error_keeps_last_successful_progress(self):
        key = account_id(ACCOUNT)
        previous = collect_chapters(FakeAPI(), ACCOUNT)
        previous['checked_at'] -= 20
        self.store.write(key, previous)
        service = self.make_service(Mock(side_effect=ProgressReadError('测试读取失败')))
        service.request(ACCOUNT, {})
        service.futures[key].result(2)
        result = self.store.read(key)
        self.assertEqual(result['projects'][0]['completed'], 1)
        self.assertEqual(result['checked_at'], previous['checked_at'])
        self.assertIn('失败', result['error'])

    def test_task_start_waits_for_read_and_prevents_late_login(self):
        entered, release, paused = threading.Event(), threading.Event(), threading.Event()
        events = []
        def factory(*args):
            entered.set()
            release.wait(3)
            events.append('login-finished')
            return SimpleNamespace(api=FakeAPI())
        service = self.make_service(factory)
        service.request(ACCOUNT, {})
        self.assertTrue(entered.wait(1))
        def pause():
            service.pause_for_run()
            events.append('task-may-start')
            paused.set()
        thread = threading.Thread(target=pause)
        thread.start()
        try:
            time.sleep(0.03)
            self.assertFalse(paused.is_set())
            release.set()
            self.assertTrue(paused.wait(2))
            self.assertEqual(events, ['login-finished', 'task-may-start'])
            self.assertFalse(service.clients)
            count = len(service.futures)
            service.request(ACCOUNT, {}, force=True)
            self.assertEqual(len(service.futures), count)
        finally:
            release.set()
            thread.join(3)

    def test_store_rejects_outside_paths(self):
        with self.assertRaises(ValueError): self.store.path('../../config')


class WorkerMonitorTests(ChapterFixture):
    def test_worker_reuses_token_without_login_or_serializing_it(self):
        monitor = WorkerChapterMonitor(self.store)
        self.addCleanup(monitor.close)
        client = SimpleNamespace(tenant_code='TEST', api=SimpleNamespace(user={'userId': 'PRIVATE_USER', 'token': 'PRIVATE_TOKEN'}), login=Mock())
        with patch('api.WeBanAPI', return_value=FakeAPI()) as reader:
            monitor.register(ACCOUNT, client)
        monitor.tick()
        self.assertFalse(monitor.inflight)
        key = account_id(ACCOUNT)
        self.store.request(key)
        monitor.tick()
        monitor.inflight[key].result(2)
        data = self.store.read(key)
        self.assertEqual(data['source'], 'task')
        self.assertEqual(data['projects'][0]['total'], 2)
        client.login.assert_not_called()
        serialized = json.dumps(data)
        for secret in ('PRIVATE_PASSWORD', 'PRIVATE_TOKEN', 'PRIVATE_USER'):
            self.assertNotIn(secret, serialized)
        self.assertEqual(reader.call_args.kwargs['user']['token'], 'PRIVATE_TOKEN')


if __name__ == '__main__':
    unittest.main()
