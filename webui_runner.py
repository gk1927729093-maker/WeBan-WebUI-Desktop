"""持续接收新增账号的任务队列；仅在独立子进程中导入和执行 main。"""
import copy
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import tomllib
import uuid
from concurrent.futures import ThreadPoolExecutor

from account_support import account_id, valid_account
from chapter_progress import ChapterStore, WorkerChapterMonitor

EVENT_PREFIX = '@@WEBUI@@'
ATTENTION_PATTERN = re.compile(r'未达到需求|进度.*未更新|进度.*不变|验证码.*(?:失败|跳过)|账号锁定|行为.*异常|课程学习未完成|无法考试|网络异常.*跳过|未获取到.*跳过|暂不可学习')


class LiveAccountQueue:
    def __init__(self, config_path: Path, state_path: Path, worker, emit=None, interval=0.5):
        self.config_path = Path(config_path)
        self.state_path = Path(state_path)
        self.worker = worker
        self.emit = emit or (lambda event: None)
        self.interval = interval
        self.run_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.accounts = {}
        self.credentials = {}
        self.futures = {}
        self.max_workers = 5
        self.settings = {}
        self.ai = {}
        self.last_error = ''
        self.resume_completed()

    def snapshot(self):
        with self.lock:
            return {'run_id': self.run_id, 'runner_pid': os.getpid(),
                    'accepting': not self.stop_event.is_set(), 'updated_at': time.time(),
                    'max_workers': self.max_workers,
                    'accounts': copy.deepcopy(list(self.accounts.values()))}

    def save(self):
        snapshot = self.snapshot()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.state_path)

    def resume_completed(self):
        """默认保留上次已完成状态及成绩，其他账号重新进入队列。"""
        try:
            previous = json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        for item in previous.get('accounts', []):
            if item.get('status') == 'completed':
                item.pop('chapter_reader_ready', None)
                item['current_course'] = ''
                self.accounts[item['id']] = item

    def record_log(self, key, line, level='INFO', verification=None):
        with self.lock:
            record = self.accounts.get(key)
            if record:
                if verification is not None:
                    record['verification'] = verification
                    record['exam_scores'] = verification.get('exam_scores', [])
                record['last_log'] = line.replace('\n', ' ')[:320]
                current = re.search(r'学习[：:]\s*(.+)', line)
                if current:
                    record['current_course'] = current.group(1)[:300]
                if level in ('ERROR', 'CRITICAL') or (ATTENTION_PATTERN.search(line) and '正在重试' not in line):
                    record['issue'] = line.replace('\n', ' ')[:320]
        self.emit({'type': 'log', 'account_id': key or '', 'line': line, 'level': level})

    def refresh(self):
        try:
            with self.config_path.open('rb') as file:
                config = tomllib.load(file)
            limit = int(config.get('settings', {}).get('max_workers', 5))
            configured = {account_id(item): item for item in config.get('account', []) if valid_account(item)}
        except (OSError, ValueError, TypeError) as exc:
            message = f'读取账号配置失败：{type(exc).__name__}，保留现有任务并稍后重试。'
            if self.last_error != message:
                self.record_log('', message, 'ERROR')
                self.last_error = message
            return
        with self.lock:
            self.last_error = ''
            self.max_workers = max(1, min(50, limit))
            self.settings = config.get('settings', {})
            self.ai = config.get('ai', {})
            for key, item in configured.items():
                if key not in self.accounts or self.accounts[key]['status'] == 'cancelled':
                    self.accounts[key] = {
                        'id': key, 'tenant_name': item['tenant_name'],
                        'username': item.get('username') or item.get('user_id', ''),
                        'status': 'queued', 'message': '已加入队列，等待并发名额。',
                        'queued_at': time.time(), 'started_at': None, 'finished_at': None,
                        'last_log': '', 'issue': '',
                    }
                    self.record_log(key, '账号已加入队列。')
                if self.accounts[key]['status'] == 'queued':
                    self.credentials[key] = copy.deepcopy(item)
            for key, record in self.accounts.items():
                if key not in configured and record['status'] == 'queued':
                    record.update(status='cancelled', message='账号已移出队列。', finished_at=time.time())

    def tick(self, executor):
        self.refresh()
        with self.lock:
            for future, key in list(self.futures.items()):
                if not future.done():
                    continue
                record = self.accounts[key]
                try:
                    success = bool(future.result())
                    if not success:
                        status, message = 'failed', record['issue'] or '执行失败，请查看该账号日志。'
                    elif record.get('verification', {}).get('complete') is True:
                        status, message = 'completed', '已完成。' if not record['issue'] else '已完成，运行中的提醒保留在日志中。'
                    elif record.get('verification', {}).get('complete') is False:
                        status, message = 'attention', record['verification']['message']
                    elif record['issue']:
                        status, message = 'attention', '执行已结束，存在未完成或异常提醒，请查看日志。'
                    else:
                        status, message = 'completed', '已完成。'
                except Exception as exc:
                    status, message = 'failed', f'执行异常：{type(exc).__name__}，请查看日志。'
                record.update(status=status, message=message, finished_at=time.time(), current_course='')
                self.record_log(key, message, 'SUCCESS' if status == 'completed' else 'WARNING')
                self.credentials.pop(key, None)
                del self.futures[future]
            slots = max(0, self.max_workers - len(self.futures))
            for key, record in self.accounts.items():
                if slots <= 0 or self.stop_event.is_set():
                    break
                if record['status'] != 'queued':
                    continue
                record.update(status='running', message='正在运行。', started_at=time.time())
                future = executor.submit(self.worker, copy.deepcopy(self.credentials[key]),
                                         copy.deepcopy(self.settings), copy.deepcopy(self.ai),
                                         list(self.accounts).index(key))
                self.futures[future] = key
                slots -= 1
        self.save()

    def run(self):
        # 实际提交数量由 tick 控制，调大并发数时不需要中断已经运行的账号。
        with ThreadPoolExecutor(max_workers=50, thread_name_prefix='weban-account') as executor:
            while not self.stop_event.is_set():
                self.tick(executor)
                self.stop_event.wait(self.interval)
        with self.lock:
            for record in self.accounts.values():
                if record['status'] in ('running', 'queued'):
                    record.update(status='stopped', message='已停止。', finished_at=time.time())
        self.save()


def main():
    import main as runtime

    chapters = WorkerChapterMonitor(ChapterStore(Path(runtime.logs_dir) / 'chapter-progress'))

    output_lock = threading.Lock()

    def emit(event):
        with output_lock:
            print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False), flush=True)

    def register_chapters(account, client):
        chapters.register(account, client)
        with queue.lock:
            queue.accounts[account_id(account)]['chapter_reader_ready'] = True

    def worker(account, settings, ai, index):
        return runtime.run_account(account, settings, runtime.merge_ai_config(runtime._OPTS, ai), index,
                                   progress_observer=register_chapters)

    queue = LiveAccountQueue(Path(runtime.config_path), Path(runtime.logs_dir) / 'webui-state.json', worker, emit)

    def sink(message):
        record = message.record
        queue.record_log(record['extra'].get('account_key', ''),
                         f"{record['time']:%H:%M:%S} | {record['level'].name} | {record['message']}",
                         record['level'].name, record['extra'].get('completion_result'))

    runtime.logger.remove()
    runtime.logger.add(sink, colorize=False, level='INFO')
    queue.refresh()
    queue.save()
    try:
        settings = queue.settings
        runtime.check_browser_health(settings.get('browser_path') or None,
                                     settings.get('cdp_host') or None,
                                     int(settings.get('cdp_port') or 0) or None)
    except Exception as exc:
        queue.record_log('', f'浏览器检查失败：{exc}', 'ERROR')
        with queue.lock:
            for record in queue.accounts.values():
                if record['status'] in ('queued', 'running'):
                    record.update(status='failed', message='浏览器检查失败，请检查配置。', finished_at=time.time())
        queue.stop_event.set()
        queue.save()
        return 1
    queue.record_log('', '队列已启动；再次启动默认跳过已完成账号，运行中可随时添加或批量导入账号。')
    chapters.start()
    try:
        queue.run()
    finally:
        chapters.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
