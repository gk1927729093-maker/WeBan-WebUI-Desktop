"""只读章节进度；运行中复用任务 Token，不重新登录账号。"""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

from account_support import account_id


class ProgressReadError(RuntimeError):
    pass


class QuietLog:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def response_data(response, label):
    if str(response.get('code')) not in ('0', '1', '200'):
        raise ProgressReadError(f'{label}读取失败，请稍后重试。')
    return response.get('data')


def course_item(course, index):
    name = str(course.get('resourceName') or course.get('name') or '未命名课程')
    key = str(course.get('resourceId') or hashlib.sha256(name.encode()).hexdigest()[:16])
    return {'id': key, 'name': name, 'completed': str(course.get('finished')) == '1'}


def collect_chapters(api, account):
    """仅调用项目、进度和课程列表接口，不调用开始学习、完课或考试接口。"""
    projects = response_data(api.list_my_project(), '项目列表') or []
    modules = response_data(api.list_completion(), '课程模块') or []
    if any(item.get('module') == 'labProject' and str(item.get('showable')) == '1' for item in modules):
        lab = response_data(api.lab_index(), '实验室课程') or {}
        current = lab.get('current')
        if current and all(item.get('userProjectId') != current.get('userProjectId') for item in projects):
            projects.append(current)
    result = {'account_id': account_id(account), 'username': account.get('username') or account.get('user_id', ''),
              'tenant_name': account['tenant_name'], 'projects': [], 'error': ''}
    for project in projects:
        project_id = project.get('userProjectId')
        if not project_id:
            raise ProgressReadError('项目缺少标识，暂时无法读取章节。')
        progress = response_data(api.show_progress(project_id), '项目进度') or {}
        simple = response_data(api.get_project_simple(project_id), '项目模式') or {}
        mode = int(simple.get('projectMode', 1) or 1)
        item = {'id': str(project_id), 'name': str(project.get('projectName') or progress.get('name') or '学习项目'),
                'completed': 0, 'total': 0, 'chapters': [], 'exams': []}
        for choose_type, label, total_key, done_key in (
                (3, '必修课', 'requiredNum', 'requiredFinishedNum'),
                (1, '推送课', 'pushNum', 'pushFinishedNum'),
                (2, '自选课', 'optionalNum', 'optionalFinishedNum')):
            if total_key not in progress or done_key not in progress:
                raise ProgressReadError(f'{label}进度字段缺失，暂时无法确认完成数。')
            required_total = int(progress[total_key] or 0)
            item['total'] += required_total
            item['completed'] += min(required_total, int(progress[done_key] or 0))
            if required_total <= 0:
                continue
            if mode == 1:
                categories = response_data(api.list_category(project_id, choose_type), '章节列表') or []
                for category in categories:
                    courses = response_data(api.list_course(project_id, category.get('categoryCode'), choose_type), '课程列表') or []
                    lessons = [course_item(course, i) for i, course in enumerate(courses)]
                    item['chapters'].append({'id': f"{choose_type}:{category.get('categoryCode', '')}",
                                             'name': str(category.get('categoryName') or '未分类章节'), 'type': label,
                                             'completed': sum(course['completed'] for course in lessons),
                                             'total': len(lessons), 'courses': lessons})
            else:
                grouped, seen = {}, set()
                page, page_count = 1, 1
                while page <= page_count:
                    data = response_data(api.list_flat_course(project_id, choose_type, page, 12), '课程分页') or {}
                    page_count = max(1, int(data.get('totalPages') or 1))
                    if page_count > 500:
                        raise ProgressReadError('课程分页数量异常，请稍后重试。')
                    for course in data.get('paginateData') or []:
                        lesson = course_item(course, len(seen))
                        if lesson['id'] in seen:
                            continue
                        seen.add(lesson['id'])
                        name = str(course.get('categoryName') or '课程列表')
                        grouped.setdefault(name, []).append(lesson)
                    page += 1
                for name, lessons in grouped.items():
                    item['chapters'].append({'id': f'{choose_type}:{name}', 'name': name, 'type': label,
                                             'completed': sum(course['completed'] for course in lessons),
                                             'total': len(lessons), 'courses': lessons})
        item['percent'] = round(min(100, item['completed'] / item['total'] * 100), 1) if item['total'] else 100
        if int(progress.get('examNum') or 0) > 0:
            try:
                plans = response_data(api.exam_list_plan(project_id), '考试成绩') or []
                for plan in plans:
                    item['exams'].append({'project_name': item['name'],
                                          'exam_name': str(plan.get('examPlanName') or '考试'),
                                          'score': float(plan.get('examScore') or 0),
                                          'full_score': float(plan.get('paperScore') or plan.get('fullScore') or 100),
                                          'pass_score': plan.get('passScore'),
                                          'taken': int(plan.get('examFinishNum') or 0) > 0})
            except Exception:
                item['exam_error'] = '考试成绩暂时无法读取，课程进度已正常同步。'
        result['projects'].append(item)
    result['checked_at'] = time.time()
    return result


class ChapterStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key, suffix='.json'):
        if not re.fullmatch(r'[0-9a-f]{20}', key):
            raise ValueError('账号标识不合法。')
        return self.root / (key + suffix)

    def read(self, key):
        try:
            return json.loads(self.path(key).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def write(self, key, data):
        path = self.path(key)
        temporary = path.with_suffix(f'.{threading.get_ident()}.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)

    def request(self, key):
        self.path(key, '.request').touch()

    def recent_requests(self):
        now = time.time()
        for path in self.root.glob('*.request'):
            if re.fullmatch(r'[0-9a-f]{20}', path.stem) and now - path.stat().st_mtime < 35:
                yield path.stem

    def error(self, key, message, source):
        previous = self.read(key) or {'account_id': key, 'projects': []}
        previous.update(error=message, attempted_at=time.time(), source=source)
        self.write(key, previous)


def make_idle_client(account, settings):
    from client import WeBanClient
    arguments = {'log': QuietLog(), 'debug': False, 'browser_path': settings.get('browser_path') or None}
    if account.get('user_id') and account.get('token'):
        arguments['user'] = {'userId': account['user_id'], 'token': account['token']}
    else:
        arguments.update(account=account.get('username'), password=account.get('password') or account.get('username'))
    client = WeBanClient(account['tenant_name'], **arguments)
    if not client.login():
        raise ProgressReadError('账号登录失败，请检查账号信息或稍后重试。')
    return client


class IdleChapterService:
    def __init__(self, store, is_running, client_factory=make_idle_client):
        self.store, self.is_running, self.client_factory = store, is_running, client_factory
        self.lock = threading.RLock()
        self.access_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chapter-read')
        self.clients, self.futures = {}, {}
        self.paused = False

    def pause_for_run(self):
        with self.lock:
            self.paused = True
        # 等待已开始的只读查询完成，再让任务登录，避免查询反过来顶掉任务。
        with self.access_lock:
            self.clients.clear()

    def resume_idle(self):
        with self.lock:
            self.paused = False

    def request(self, account, settings, force=False):
        key = account_id(account)
        self.store.request(key)
        cached = self.store.read(key)
        stamp = max((cached or {}).get('checked_at', 0), (cached or {}).get('attempted_at', 0))
        due = time.time() - stamp >= (2 if force else 10)
        with self.lock:
            active = self.paused or self.is_running(key)
            future = self.futures.get(key)
            if not active and due and (future is None or future.done()):
                future = self.executor.submit(self._fetch, copy.deepcopy(account), copy.deepcopy(settings))
                self.futures[key] = future
            loading = bool(active and due) or bool(future and not future.done())
        answer = copy.deepcopy(cached or {'account_id': key, 'projects': []})
        answer.update(refreshing=loading, waiting_for_task=active and not cached)
        return answer

    def _fetch(self, account, settings):
        key = account_id(account)
        with self.access_lock:
            with self.lock:
                if self.paused or self.is_running(key):
                    return
            try:
                signature = hashlib.sha256(json.dumps(account, sort_keys=True).encode()).hexdigest()
                entry = self.clients.get(key)
                if entry is None or entry[0] != signature:
                    entry = (signature, self.client_factory(account, settings))
                    self.clients[key] = entry
                try:
                    data = collect_chapters(entry[1].api, account)
                except PermissionError:
                    self.clients.pop(key, None)
                    with self.lock:
                        if self.paused or self.is_running(key):
                            return
                    entry = (signature, self.client_factory(account, settings))
                    self.clients[key] = entry
                    data = collect_chapters(entry[1].api, account)
                data['source'] = 'platform'
                self.store.write(key, data)
            except Exception as exc:
                message = str(exc) if isinstance(exc, ProgressReadError) else f'章节读取失败（{type(exc).__name__}），请稍后重试。'
                self.store.error(key, message, 'platform')

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


class WorkerChapterMonitor:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.clients = {}
        self.inflight = {}
        self.stop_event = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='chapter-worker')
        self.thread = threading.Thread(target=self._loop, daemon=True, name='chapter-watch')

    def register(self, account, client):
        from api import WeBanAPI
        # 独立只读 Session 复用现有 Token，不与学习请求共用可变 Session。
        api = WeBanAPI(tenant_code=client.tenant_code, user=dict(client.api.user),
                       debug=False, log=QuietLog())
        with self.lock:
            self.clients[account_id(account)] = (copy.deepcopy(account), api)

    def start(self):
        self.thread.start()

    def _loop(self):
        while not self.stop_event.wait(0.5):
            self.tick()

    def tick(self):
        for key in self.store.recent_requests():
            with self.lock:
                entry = self.clients.get(key)
                future = self.inflight.get(key)
                cached = self.store.read(key) or {}
                stamp = max(cached.get('checked_at', 0), cached.get('attempted_at', 0))
                if entry and (future is None or future.done()) and time.time() - stamp >= 10:
                    self.inflight[key] = self.executor.submit(self._fetch, key, entry)

    def _fetch(self, key, entry):
        account, api = entry
        try:
            data = collect_chapters(api, account)
            data['source'] = 'task'
            self.store.write(key, data)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ProgressReadError) else f'任务章节同步暂未成功（{type(exc).__name__}），稍后重试。'
            self.store.error(key, message, 'task')

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(2)
        self.executor.shutdown(wait=True, cancel_futures=True)
