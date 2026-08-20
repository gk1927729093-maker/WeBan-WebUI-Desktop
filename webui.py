#!/usr/bin/env python3
"""
WeBan WebUI - 美观的深色主题中英双语界面
"""
import os
import json
import subprocess
import threading
import logging
import asyncio
import sys
import shutil
import time
import urllib.request
from collections import deque
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

try:
    import tomllib
except ImportError:
    import tomli as tomllib

try:
    import tomli_w
except ImportError:
    tomli_w = None

# 本体代码始终位于本文件目录；WB_DATA_DIR 可把配置和日志放到持久化目录。
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WB_DATA_DIR", APP_DIR)).resolve()
CONFIG_FILE = DATA_DIR / "config.toml"
LOG_DIR = DATA_DIR / "logs"
MAIN_SCRIPT = APP_DIR / "main.py"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 全局状态
app = FastAPI(title="WeBan WebUI")
task_process: Optional[subprocess.Popen] = None
task_running = False
task_lock = threading.RLock()
task_logs: deque[tuple[int, str]] = deque(maxlen=500)
task_log_sequence = 0
school_cache: list[str] = []
school_cache_loaded_at = 0.0
school_cache_lock = threading.Lock()

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _get_weban_python_command() -> list[str]:
    """优先使用项目要求的 Python 3.12，避免 WebUI 与本体环境不一致。"""
    if sys.version_info[:2] == (3, 12):
        return [sys.executable]
    launcher = shutil.which("py")
    if launcher:
        return [launcher, "-3.12"]
    return [sys.executable]


# ========== API 端点 ==========

@app.get("/api/task/status")
async def get_task_status():
    """获取任务状态"""
    return {
        "running": task_process is not None and task_process.poll() is None
    }


@app.post("/api/task/start")
async def start_task():
    """启动任务"""
    global task_process, task_running

    with task_lock:
        if task_process is not None and task_process.poll() is None:
            return {"success": False, "message": "任务已在运行中"}
        if not MAIN_SCRIPT.is_file():
            return {"success": False, "message": "未找到 main.py 本体程序"}

        accounts = load_config().get("account", [])
        if not any(
            account.get("tenant_name")
            and (
                account.get("username")
                or (account.get("user_id") and account.get("token"))
            )
            for account in accounts
        ):
            return {
                "success": False,
                "message": "请先在账号管理中保存学校和账号信息",
            }

        try:
            python_command = _get_weban_python_command()
            task_process = subprocess.Popen(
                [
                    *python_command,
                    "-u",
                    MAIN_SCRIPT.name,
                    "--data-dir",
                    str(DATA_DIR),
                    "--non-interactive",
                ],
                cwd=str(APP_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            task_running = True
            _append_task_log("WeBan 任务已启动。")
            threading.Thread(
                target=_stream_task_output,
                args=(task_process,),
                daemon=True,
            ).start()
            return {"success": True}
        except OSError as exc:
            logger.exception("启动 WeBan 失败")
            return {"success": False, "message": f"启动失败：{exc}"}


@app.post("/api/task/stop")
async def stop_task():
    """停止任务"""
    global task_process, task_running
    
    with task_lock:
        if task_process is None or task_process.poll() is not None:
            task_running = False
            return {"success": False, "message": "任务未在运行"}

        try:
            task_process.terminate()
            task_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            task_process.kill()
            task_process.wait(timeout=5)
        except OSError as exc:
            logger.exception("停止 WeBan 失败")
            return {"success": False, "message": f"停止失败：{exc}"}

        task_running = False
        _append_task_log("WeBan 任务已停止。")
        return {"success": True}


@app.get("/api/accounts")
async def get_accounts():
    """获取账号列表"""
    config = load_config()
    accounts = config.get("account", [])
    return {"accounts": accounts}


@app.get("/api/schools")
def get_schools():
    """获取官方学校列表，失败时返回配置中已有的学校名称。"""
    schools = _get_school_names_from_config()
    try:
        schools = _load_school_names() or schools
    except (OSError, ValueError, TimeoutError) as exc:
        logger.warning("获取学校列表失败，使用本地学校列表：%s", exc)
    return {"schools": schools, "source": "official" if school_cache else "local"}


@app.post("/api/accounts")
async def add_account(data: Dict[str, Any]):
    """添加账号"""
    tenant_name = str(data.get("tenant_name", "")).strip()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip() or username
    if not tenant_name or not username:
        return {"success": False, "message": "学校名称和用户名不能为空"}

    config = load_config()
    accounts = config.setdefault("account", [])
    if any(
        account.get("tenant_name") == tenant_name
        and account.get("username") == username
        for account in accounts
    ):
        return {"success": False, "message": "该学校下的账号已存在"}

    accounts.append(
        {
            "tenant_name": tenant_name,
            "username": username,
            "password": password,
        }
    )
    if not save_config(config):
        return {"success": False, "message": "配置文件保存失败，请检查文件权限"}
    return {"success": True}


@app.delete("/api/accounts/{username}")
async def delete_account(username: str, tenant_name: Optional[str] = None):
    """删除账号"""
    config = load_config()
    accounts = config.get("account", [])
    remaining = [
        account
        for account in accounts
        if not (
            account.get("username") == username
            and (tenant_name is None or account.get("tenant_name") == tenant_name)
        )
    ]
    if len(remaining) == len(accounts):
        return {"success": False, "message": "未找到该账号"}
    config["account"] = remaining
    if not save_config(config):
        return {"success": False, "message": "配置文件保存失败，请检查文件权限"}
    return {"success": True}


@app.get("/api/settings")
async def get_settings():
    """获取设置"""
    config = load_config()
    return config.get("settings", {})


@app.post("/api/settings")
async def update_settings(data: Dict[str, Any]):
    """更新设置"""
    config = load_config()
    config.setdefault("settings", {}).update(data)
    if not save_config(config):
        return {"success": False, "message": "配置文件保存失败，请检查文件权限"}
    return {"success": True}


@app.get("/api/logs")
async def get_logs():
    """获取日志列表"""
    logs = []
    if LOG_DIR.exists():
        for log_file in sorted(
            LOG_DIR.rglob("*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ):
            logs.append({
                "name": log_file.relative_to(LOG_DIR).as_posix(),
                "size": log_file.stat().st_size,
                "modified": log_file.stat().st_mtime
            })
    return {"logs": logs[:50]}


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket 实时日志推送"""
    await websocket.accept()
    last_sequence = 0
    try:
        while True:
            with task_lock:
                pending = [
                    (sequence, line)
                    for sequence, line in task_logs
                    if sequence > last_sequence
                ]
            for sequence, line in pending:
                await websocket.send_text(line)
                last_sequence = sequence
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        pass


# ========== 配置管理 ==========

def load_config() -> Dict[str, Any]:
    """加载配置"""
    if not CONFIG_FILE.exists():
        return {"account": [], "settings": {}}

    try:
        with open(CONFIG_FILE, "rb") as f:
            config = tomllib.load(f)
            # 兼容早期 WebUI 使用的错误复数键。
            if "account" not in config and "accounts" in config:
                config["account"] = config.pop("accounts")
            config.setdefault("account", [])
            config.setdefault("settings", {})
            return config
    except Exception as exc:
        logger.error("读取配置失败：%s", exc)
    return {"account": [], "settings": {}}


def _get_school_names_from_config() -> list[str]:
    """从现有配置提取学校名，作为离线兜底和快速首屏建议。"""
    names = {
        str(account.get("tenant_name", "")).strip()
        for account in load_config().get("account", [])
    }
    return sorted(name for name in names if name)


def _load_school_names() -> list[str]:
    """从 WeBan 登录接口获取学校全称列表，并在内存中缓存。"""
    global school_cache, school_cache_loaded_at
    now = time.monotonic()
    with school_cache_lock:
        if school_cache and now - school_cache_loaded_at < 6 * 60 * 60:
            return list(school_cache)

    timestamp = f"{time.time():.3f}"
    request = urllib.request.Request(
        "https://weiban.mycourse.cn/pharos/login/getTenantListWithLetter.do"
        f"?timestamp={timestamp}",
        data=b"",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))

    schools = {
        str(entry.get("name", "")).strip()
        for group in payload.get("data", [])
        for entry in group.get("list", [])
        if entry.get("name")
    }
    if not schools:
        raise ValueError("官方接口没有返回学校列表")

    result = sorted(schools)
    with school_cache_lock:
        school_cache = result
        school_cache_loaded_at = time.monotonic()
    return list(result)


def save_config(config: Dict[str, Any]) -> bool:
    """保存配置"""
    if tomli_w is None:
        logger.error("tomli_w not installed, cannot save config")
        return False

    temporary_file = CONFIG_FILE.with_suffix(".toml.tmp")
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary_file, "wb") as file:
            tomli_w.dump(config, file)
        os.replace(temporary_file, CONFIG_FILE)
        return True
    except OSError as exc:
        logger.exception("保存配置失败：%s", exc)
        temporary_file.unlink(missing_ok=True)
        return False


def _append_task_log(line: str) -> None:
    global task_log_sequence
    message = line.rstrip()
    if not message:
        return
    with task_lock:
        task_log_sequence += 1
        task_logs.append((task_log_sequence, message))


def _stream_task_output(process: subprocess.Popen) -> None:
    global task_running
    if process.stdout is None:
        return

    try:
        for line in process.stdout:
            _append_task_log(line)
    finally:
        return_code = process.wait()
        _append_task_log(f"WeBan 任务已退出，退出码：{return_code}。")
        with task_lock:
            if task_process is process:
                task_running = False

# ========== HTML 界面 ==========

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WeBan WebUI</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --surface-0: #05070C;
            --surface-1: #0A0D12;
            --surface-2: #0F131C;
            --surface-3: #161D2B;
            --surface-4: #1E2636;
            --accent: #38BDF8;
            --accent-dim: #0EA5E9;
            --success: #6EE7B7;
            --danger: #F87171;
            --text-primary: #F8FAFC;
            --text-secondary: #94A3B8;
            --radius: 12px;
            --radius-full: 999px;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--surface-0);
            color: var(--text-primary);
            line-height: 1.6;
        }

        .app {
            display: grid;
            grid-template-columns: 240px 1fr;
            grid-template-rows: 60px 1fr;
            height: 100vh;
        }

        .header {
            grid-column: 1 / -1;
            background: var(--surface-1);
            border-bottom: 1px solid var(--surface-3);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 2rem;
        }

        .logo {
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            background: linear-gradient(135deg, var(--accent), var(--success));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .lang-switch {
            background: var(--surface-2);
            border: 1px solid var(--surface-3);
            border-radius: var(--radius);
        }

        .lang-btn {
            width: 2.5rem;
            height: 2.5rem;
            display: grid;
            place-items: center;
            padding: 0;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            border-radius: var(--radius);
            cursor: pointer;
            transition: all 0.2s;
        }

        .lang-btn:hover {
            background: var(--accent);
            color: white;
        }

        .sidebar {
            background: var(--surface-1);
            border-right: 1px solid var(--surface-3);
            padding: 1.5rem;
        }

        .nav {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.75rem 1rem;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            border-radius: var(--radius);
            cursor: pointer;
            transition: all 0.2s;
            text-align: left;
            width: 100%;
            font-size: 0.9375rem;
        }

        .nav-item:hover {
            background: var(--surface-2);
            color: var(--text-primary);
        }

        .nav-item.active {
            background: var(--surface-3);
            color: var(--accent);
        }

        .nav-icon {
            width: 20px;
            height: 20px;
            flex-shrink: 0;
        }

        .main {
            overflow-y: auto;
            padding: 2.5rem;
        }

        .page {
            display: none;
            max-width: 1200px;
        }

        .page.active {
            display: block;
        }

        .card {
            background: var(--surface-1);
            border: 1px solid var(--surface-3);
            border-radius: var(--radius);
            padding: 1.75rem;
            margin-bottom: 1.5rem;
        }

        .card-title {
            font-size: 1.375rem;
            font-weight: 600;
            margin-bottom: 1rem;
            letter-spacing: -0.015em;
        }

        .btn {
            padding: 0.625rem 1.5rem;
            border: none;
            border-radius: var(--radius-full);
            cursor: pointer;
            font-size: 0.9375rem;
            font-weight: 500;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--accent);
            color: white;
        }

        .btn-primary:hover:not(:disabled) {
            background: var(--accent-dim);
            transform: translateY(-1px);
        }

        .btn-danger {
            background: var(--danger);
            color: white;
        }

        .btn-danger:hover:not(:disabled) {
            opacity: 0.9;
            transform: translateY(-1px);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .status {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.5rem 1rem;
            border-radius: var(--radius-full);
            font-size: 0.875rem;
            font-weight: 500;
        }

        .status-running {
            background: rgba(110, 231, 183, 0.1);
            color: var(--success);
        }

        .status-stopped {
            background: rgba(148, 163, 184, 0.1);
            color: var(--text-secondary);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: currentColor;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .form-group {
            margin-bottom: 1.25rem;
        }

        .form-label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--text-secondary);
            font-size: 0.875rem;
            font-weight: 500;
        }

        .form-input {
            width: 100%;
            padding: 0.75rem 1rem;
            background: var(--surface-2);
            border: 1px solid var(--surface-3);
            border-radius: var(--radius);
            color: var(--text-primary);
            font-size: 0.9375rem;
            transition: all 0.2s;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--accent);
            background: var(--surface-3);
        }

        .school-picker {
            position: relative;
        }

        .school-suggestions {
            position: absolute;
            z-index: 20;
            top: calc(100% + 0.35rem);
            left: 0;
            right: 0;
            display: none;
            max-height: 260px;
            overflow-y: auto;
            padding: 0.35rem;
            background: var(--surface-1);
            border: 1px solid var(--surface-3);
            border-radius: var(--radius);
            box-shadow: 0 14px 30px rgba(0, 0, 0, 0.32);
        }

        .school-suggestions.visible {
            display: block;
        }

        .school-suggestion {
            width: 100%;
            padding: 0.65rem 0.75rem;
            border: 0;
            border-radius: calc(var(--radius) - 2px);
            background: transparent;
            color: var(--text-primary);
            text-align: left;
            cursor: pointer;
            font-size: 0.9rem;
        }

        .school-suggestion:hover,
        .school-suggestion.highlighted {
            background: var(--surface-3);
            color: var(--accent);
        }

        .school-hint {
            margin-top: 0.4rem;
            color: var(--text-secondary);
            font-size: 0.75rem;
        }

        .account-list {
            display: grid;
            gap: 0.75rem;
        }

        .account-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            background: var(--surface-2);
            border-radius: var(--radius);
        }

        .account-info {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }

        .account-username {
            font-weight: 600;
            color: var(--accent);
        }

        .account-school {
            font-weight: 500;
            color: var(--text-primary);
            font-size: 0.875rem;
        }

        .account-password {
            font-size: 0.875rem;
            color: var(--text-secondary);
            font-family: monospace;
        }

        .btn-delete {
            padding: 0.5rem 1rem;
            background: rgba(248, 113, 113, 0.1);
            color: var(--danger);
            border: 1px solid rgba(248, 113, 113, 0.2);
            border-radius: var(--radius-full);
            cursor: pointer;
            font-size: 0.875rem;
            transition: all 0.2s;
        }

        .btn-delete:hover {
            background: rgba(248, 113, 113, 0.2);
        }

        .log-viewer {
            background: var(--surface-2);
            border-radius: var(--radius);
            padding: 1rem;
            height: 500px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.8125rem;
            line-height: 1.5;
        }

        .log-line {
            color: var(--text-secondary);
            margin-bottom: 0.25rem;
        }

        .controls {
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            align-items: center;
        }
    </style>
</head>
<body>
    <div class="app">
        <div class="header">
            <div class="logo">WeBan WebUI</div>
            <div class="lang-switch">
                <button id="language-toggle" class="lang-btn" type="button" title="切换语言" aria-label="切换语言">
                    <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                        <circle cx="12" cy="12" r="9" stroke-width="2"></circle>
                        <path d="M3 12h18M12 3c2.4 2.5 3.6 5.5 3.6 9S14.4 18.5 12 21C9.6 18.5 8.4 15.5 8.4 12S9.6 5.5 12 3z" stroke-width="2"></path>
                    </svg>
                </button>
            </div>
        </div>

        <div class="sidebar">
            <nav class="nav">
                <button class="nav-item active" data-page="dashboard">
                    <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path>
                    </svg>
                    <span data-i18n="nav.dashboard">控制台</span>
                </button>
                <button class="nav-item" data-page="accounts">
                    <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"></path>
                    </svg>
                    <span data-i18n="nav.accounts">账号管理</span>
                </button>
                <button class="nav-item" data-page="settings">
                    <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                    </svg>
                    <span data-i18n="nav.settings">全局设置</span>
                </button>
                <button class="nav-item" data-page="logs">
                    <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <span data-i18n="nav.logs">日志查看</span>
                </button>
            </nav>
        </div>

        <main class="main">
            <!-- Dashboard -->
            <div id="page-dashboard" class="page active">
                <div class="card">
                    <h2 class="card-title" data-i18n="dashboard.title">任务控制</h2>
                    <div class="controls">
                        <span id="task-status" class="status status-stopped">
                            <span class="status-dot"></span>
                            <span data-i18n="dashboard.stopped">已停止</span>
                        </span>
                        <button id="btn-start" class="btn btn-primary" data-i18n="dashboard.start">启动任务</button>
                        <button id="btn-stop" class="btn btn-danger" disabled data-i18n="dashboard.stop">停止任务</button>
                    </div>
                </div>
                <div class="card">
                    <h2 class="card-title" data-i18n="dashboard.realtimeLogs">实时日志</h2>
                    <div id="realtime-logs" class="log-viewer"></div>
                </div>
            </div>

            <!-- Accounts -->
            <div id="page-accounts" class="page">
                <div class="card">
                    <h2 class="card-title" data-i18n="accounts.title">账号管理</h2>
                    <form id="form-add-account">
                        <div class="form-group">
                            <label class="form-label" data-i18n="accounts.school">学校名称</label>
                            <div class="school-picker">
                                <input type="text" name="tenant_name" id="tenant_name" class="form-input" required
                                       autocomplete="off" data-i18n-placeholder="accounts.schoolPlaceholder">
                                <div id="school-suggestions" class="school-suggestions" role="listbox"></div>
                            </div>
                            <div class="school-hint" data-i18n="accounts.schoolHint">输入学校名称的一部分，从列表中选择完整名称</div>
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="accounts.username">用户名</label>
                            <input type="text" name="username" class="form-input" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="accounts.password">密码</label>
                            <input type="password" name="password" class="form-input">
                        </div>
                        <button type="submit" class="btn btn-primary" data-i18n="accounts.add">添加账号</button>
                    </form>
                </div>
                <div class="card">
                    <h2 class="card-title" data-i18n="accounts.list">账号列表</h2>
                    <div id="account-list" class="account-list"></div>
                </div>
            </div>

            <!-- Settings -->
            <div id="page-settings" class="page">
                <div class="card">
                    <h2 class="card-title" data-i18n="settings.title">全局设置</h2>
                    <form id="form-settings">
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.studyMode">学习模式</label>
                            <select name="study_mode" id="study_mode" class="form-input">
                                <option value="false" data-i18n="settings.off">关闭</option>
                                <option value="true" data-i18n="settings.normal">正常</option>
                                <option value="force" data-i18n="settings.force">强制</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.examMode">考试模式</label>
                            <select name="exam_mode" id="exam_mode" class="form-input">
                                <option value="false" data-i18n="settings.off">关闭</option>
                                <option value="true" data-i18n="settings.normal">正常</option>
                                <option value="perfect" data-i18n="settings.perfect">满分优先</option>
                                <option value="force" data-i18n="settings.force">强制</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.maxWorkers">最大并发数</label>
                            <input type="number" name="max_workers" class="form-input" value="5" min="1" max="50">
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.studyTime">最少学习停留（秒）</label>
                            <input type="number" name="study_time" class="form-input" value="30" min="0">
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.randomAnswer">未知题随机作答</label>
                            <input type="checkbox" name="random_answer" id="random_answer">
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.videoSpeed">视频课程速度</label>
                            <select name="video_speed" id="video_speed" class="form-input">
                                <option value="0" data-i18n="settings.videoInstant">仅按最少停留</option>
                                <option value="1" data-i18n="settings.videoNormal">正常</option>
                                <option value="2" data-i18n="settings.videoDouble">2 倍</option>
                            </select>
                        </div>
                        <button type="submit" class="btn btn-primary" data-i18n="settings.save">保存设置</button>
                    </form>
                </div>
            </div>

            <!-- Logs -->
            <div id="page-logs" class="page">
                <div class="card">
                    <h2 class="card-title" data-i18n="logs.title">历史日志</h2>
                    <div id="log-list" class="account-list"></div>
                </div>
            </div>
        </main>
    </div>

    <script>
        const i18n = {
            zh: {
                'nav.dashboard': '控制台',
                'nav.accounts': '账号管理',
                'nav.settings': '全局设置',
                'nav.logs': '日志查看',
                'dashboard.title': '任务控制',
                'dashboard.start': '启动任务',
                'dashboard.stop': '停止任务',
                'dashboard.running': '运行中',
                'dashboard.stopped': '已停止',
                'dashboard.realtimeLogs': '实时日志',
                'accounts.title': '账号管理',
                'accounts.school': '学校名称',
                'accounts.schoolPlaceholder': '输入学校名称，例如：北京交通大学',
                'accounts.schoolHint': '输入学校名称的一部分，从列表中选择完整名称',
                'accounts.username': '用户名',
                'accounts.password': '密码',
                'accounts.add': '添加账号',
                'accounts.list': '账号列表',
                'accounts.delete': '删除',
                'settings.title': '全局设置',
                'settings.studyMode': '学习模式',
                'settings.examMode': '考试模式',
                'settings.maxWorkers': '最大并发数',
                'settings.studyTime': '最少学习停留（秒）',
                'settings.randomAnswer': '未知题随机作答',
                'settings.videoSpeed': '视频课程速度',
                'settings.off': '关闭',
                'settings.normal': '正常',
                'settings.force': '强制',
                'settings.perfect': '满分优先',
                'settings.videoInstant': '仅按最少停留',
                'settings.videoNormal': '正常',
                'settings.videoDouble': '2 倍',
                'settings.save': '保存设置',
                'logs.title': '历史日志',
                'msg.success': '操作成功',
                'msg.error': '操作失败'
            },
            en: {
                'nav.dashboard': 'Dashboard',
                'nav.accounts': 'Accounts',
                'nav.settings': 'Settings',
                'nav.logs': 'Logs',
                'dashboard.title': 'Task Control',
                'dashboard.start': 'Start Task',
                'dashboard.stop': 'Stop Task',
                'dashboard.running': 'Running',
                'dashboard.stopped': 'Stopped',
                'dashboard.realtimeLogs': 'Realtime Logs',
                'accounts.title': 'Account Management',
                'accounts.school': 'School Name',
                'accounts.schoolPlaceholder': 'Type part of a school name, e.g. Beijing Jiaotong',
                'accounts.schoolHint': 'Type part of a school name and select the complete name',
                'accounts.username': 'Username',
                'accounts.password': 'Password',
                'accounts.add': 'Add Account',
                'accounts.list': 'Account List',
                'accounts.delete': 'Delete',
                'settings.title': 'Global Settings',
                'settings.studyMode': 'Study Mode',
                'settings.examMode': 'Exam Mode',
                'settings.maxWorkers': 'Max Workers',
                'settings.studyTime': 'Minimum Study Time (seconds)',
                'settings.randomAnswer': 'Random Answer for Unknown Questions',
                'settings.videoSpeed': 'Video Course Speed',
                'settings.off': 'Off',
                'settings.normal': 'Normal',
                'settings.force': 'Force',
                'settings.perfect': 'Perfect Score',
                'settings.videoInstant': 'Minimum time only',
                'settings.videoNormal': 'Normal',
                'settings.videoDouble': '2x',
                'settings.save': 'Save Settings',
                'logs.title': 'Log History',
                'msg.success': 'Success',
                'msg.error': 'Error'
            }
        };

        let currentLang = localStorage.getItem('lang') || 'zh';
        let ws = null;
        let schoolNames = [];
        let highlightedSchoolIndex = -1;

        document.addEventListener('DOMContentLoaded', function() {
            setLanguage(currentLang);

            document.getElementById('language-toggle').addEventListener('click', () => {
                setLanguage(currentLang === 'zh' ? 'en' : 'zh');
            });

            const schoolInput = document.getElementById('tenant_name');
            const schoolSuggestions = document.getElementById('school-suggestions');
            schoolInput.addEventListener('focus', () => {
                loadSchools();
                renderSchoolSuggestions();
            });
            schoolInput.addEventListener('input', () => {
                highlightedSchoolIndex = -1;
                renderSchoolSuggestions();
            });
            schoolInput.addEventListener('keydown', (event) => {
                const options = schoolSuggestions.querySelectorAll('.school-suggestion');
                if (!schoolSuggestions.classList.contains('visible') || !options.length) return;
                if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    highlightedSchoolIndex = Math.min(highlightedSchoolIndex + 1, options.length - 1);
                    updateHighlightedSchool();
                } else if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    highlightedSchoolIndex = Math.max(highlightedSchoolIndex - 1, 0);
                    updateHighlightedSchool();
                } else if (event.key === 'Enter' && highlightedSchoolIndex >= 0) {
                    event.preventDefault();
                    options[highlightedSchoolIndex].click();
                } else if (event.key === 'Escape') {
                    hideSchoolSuggestions();
                }
            });
            document.addEventListener('click', (event) => {
                if (!event.target.closest('.school-picker')) hideSchoolSuggestions();
            });
            
            document.querySelectorAll('.nav-item').forEach(item => {
                item.addEventListener('click', () => {
                    switchPage(item.dataset.page);
                });
            });
            
            document.getElementById('btn-start').addEventListener('click', async () => {
                try {
                    const response = await fetch('/api/task/start', { method: 'POST' });
                    const data = await response.json();
                    if (data.success) {
                        alert(i18n[currentLang]['msg.success']);
                        loadTaskStatus();
                    } else {
                        alert(i18n[currentLang]['msg.error'] + ': ' + data.message);
                    }
                } catch (error) {
                    alert(i18n[currentLang]['msg.error'] + ': ' + error.message);
                }
            });
            
            document.getElementById('btn-stop').addEventListener('click', async () => {
                try {
                    const response = await fetch('/api/task/stop', { method: 'POST' });
                    const data = await response.json();
                    if (data.success) {
                        alert(i18n[currentLang]['msg.success']);
                        loadTaskStatus();
                    } else {
                        alert(i18n[currentLang]['msg.error'] + ': ' + data.message);
                    }
                } catch (error) {
                    alert(i18n[currentLang]['msg.error'] + ': ' + error.message);
                }
            });
            
            document.getElementById('form-add-account').addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData);
                
                try {
                    const response = await fetch('/api/accounts', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    const result = await response.json();
                    if (result.success) {
                        alert(i18n[currentLang]['msg.success']);
                        e.target.reset();
                        loadAccounts();
                    } else {
                        alert(i18n[currentLang]['msg.error'] + ': ' + result.message);
                    }
                } catch (error) {
                    alert(i18n[currentLang]['msg.error'] + ': ' + error.message);
                }
            });
            
            document.getElementById('form-settings').addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData);
                data.max_workers = Number(data.max_workers);
                data.study_time = Number(data.study_time);
                data.video_speed = Number(data.video_speed);
                data.random_answer = document.getElementById('random_answer').checked;
                
                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    const result = await response.json();
                    if (result.success) {
                        alert(i18n[currentLang]['msg.success']);
                    } else {
                        alert(i18n[currentLang]['msg.error'] + ': ' + result.message);
                    }
                } catch (error) {
                    alert(i18n[currentLang]['msg.error'] + ': ' + error.message);
                }
            });
            
            loadTaskStatus();
            loadAccounts();
            loadSettings();
            loadLogs();
            connectWebSocket();
            setInterval(loadTaskStatus, 3000);
        });

        function setLanguage(lang) {
            currentLang = lang;
            localStorage.setItem('lang', lang);
            
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const key = el.dataset.i18n;
                const translation = i18n[lang][key];
                if (translation) {
                    el.textContent = translation;
                }
            });

            document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
                const translation = i18n[lang][el.dataset.i18nPlaceholder];
                if (translation) el.placeholder = translation;
            });

            const languageToggle = document.getElementById('language-toggle');
            const nextLanguage = lang === 'zh' ? 'English' : '中文';
            languageToggle.title = `${lang === 'zh' ? '切换到' : 'Switch to'} ${nextLanguage}`;
            languageToggle.setAttribute('aria-label', languageToggle.title);
            document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
        }

        function switchPage(pageName) {
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.toggle('active', item.dataset.page === pageName);
            });
            
            document.querySelectorAll('.page').forEach(page => {
                page.classList.toggle('active', page.id === `page-${pageName}`);
            });
        }

        async function loadTaskStatus() {
            try {
                const response = await fetch('/api/task/status');
                const data = await response.json();
                
                const statusEl = document.getElementById('task-status');
                const btnStart = document.getElementById('btn-start');
                const btnStop = document.getElementById('btn-stop');
                
                if (data.running) {
                    statusEl.className = 'status status-running';
                    statusEl.querySelector('[data-i18n]').textContent = i18n[currentLang]['dashboard.running'];
                    btnStart.disabled = true;
                    btnStop.disabled = false;
                } else {
                    statusEl.className = 'status status-stopped';
                    statusEl.querySelector('[data-i18n]').textContent = i18n[currentLang]['dashboard.stopped'];
                    btnStart.disabled = false;
                    btnStop.disabled = true;
                }
            } catch (error) {
                console.error('Failed to load task status:', error);
            }
        }

        async function loadAccounts() {
            try {
                const response = await fetch('/api/accounts');
                const data = await response.json();
                
                const listEl = document.getElementById('account-list');
                listEl.innerHTML = '';
                
                data.accounts.forEach(account => {
                    const item = document.createElement('div');
                    item.className = 'account-item';
                    item.innerHTML = `
                        <div class="account-info">
                            <div class="account-school">${escapeHtml(account.tenant_name || '')}</div>
                            <div class="account-username">${escapeHtml(account.username || '')}</div>
                            <div class="account-password">${'*'.repeat((account.password || '').length)}</div>
                        </div>
                    `;
                    const deleteButton = document.createElement('button');
                    deleteButton.className = 'btn-delete';
                    deleteButton.textContent = i18n[currentLang]['accounts.delete'];
                    deleteButton.addEventListener('click', () => {
                        deleteAccount(account.username || '', account.tenant_name || '');
                    });
                    item.appendChild(deleteButton);
                    listEl.appendChild(item);
                });
            } catch (error) {
                console.error('Failed to load accounts:', error);
            }
        }

        async function loadSchools() {
            if (schoolNames.length) return;
            try {
                const response = await fetch('/api/schools');
                const data = await response.json();
                schoolNames = Array.isArray(data.schools) ? data.schools : [];
                renderSchoolSuggestions();
            } catch (error) {
                console.error('Failed to load schools:', error);
            }
        }

        function renderSchoolSuggestions() {
            const input = document.getElementById('tenant_name');
            const container = document.getElementById('school-suggestions');
            const keyword = input.value.trim().toLowerCase();
            const matches = schoolNames
                .filter(name => !keyword || name.toLowerCase().includes(keyword))
                .slice(0, 30);

            container.innerHTML = '';
            if (!matches.length || document.activeElement !== input) {
                hideSchoolSuggestions();
                return;
            }

            matches.forEach((school, index) => {
                const option = document.createElement('button');
                option.type = 'button';
                option.className = 'school-suggestion';
                option.setAttribute('role', 'option');
                option.textContent = school;
                option.addEventListener('mousedown', (event) => event.preventDefault());
                option.addEventListener('click', () => {
                    input.value = school;
                    hideSchoolSuggestions();
                    input.focus();
                });
                option.dataset.index = String(index);
                container.appendChild(option);
            });
            container.classList.add('visible');
            updateHighlightedSchool();
        }

        function updateHighlightedSchool() {
            document.querySelectorAll('.school-suggestion').forEach((option, index) => {
                option.classList.toggle('highlighted', index === highlightedSchoolIndex);
            });
        }

        function hideSchoolSuggestions() {
            document.getElementById('school-suggestions').classList.remove('visible');
        }

        async function deleteAccount(username, tenantName) {
            if (!confirm(`Delete account "${tenantName} / ${username}"?`)) return;
            
            try {
                const response = await fetch(`/api/accounts/${encodeURIComponent(username)}?tenant_name=${encodeURIComponent(tenantName)}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                if (data.success) {
                    loadAccounts();
                } else {
                    alert(i18n[currentLang]['msg.error'] + ': ' + data.message);
                }
            } catch (error) {
                alert(i18n[currentLang]['msg.error'] + ': ' + error.message);
            }
        }

        async function loadSettings() {
            try {
                const response = await fetch('/api/settings');
                const data = await response.json();
                
                if (data.study_mode !== undefined) {
                    document.getElementById('study_mode').value = String(data.study_mode);
                }
                if (data.exam_mode !== undefined) {
                    document.getElementById('exam_mode').value = String(data.exam_mode);
                }
                if (data.max_workers !== undefined) {
                    document.querySelector('[name="max_workers"]').value = data.max_workers;
                }
                if (data.study_time !== undefined) {
                    document.querySelector('[name="study_time"]').value = data.study_time;
                }
                if (data.random_answer !== undefined) {
                    document.getElementById('random_answer').checked =
                        data.random_answer === true
                        || ['1', 'true', 'yes', 'on'].includes(String(data.random_answer).toLowerCase());
                }
                if (data.video_speed !== undefined) {
                    document.getElementById('video_speed').value = String(data.video_speed);
                }
            } catch (error) {
                console.error('Failed to load settings:', error);
            }
        }

        async function loadLogs() {
            try {
                const response = await fetch('/api/logs');
                const data = await response.json();
                
                const listEl = document.getElementById('log-list');
                listEl.innerHTML = '';
                
                data.logs.forEach(log => {
                    const item = document.createElement('div');
                    item.className = 'account-item';
                    item.innerHTML = `
                        <div class="account-info">
                            <div class="account-username">${escapeHtml(log.name)}</div>
                            <div class="account-password">${formatBytes(log.size)} • ${new Date(log.modified * 1000).toLocaleString()}</div>
                        </div>
                    `;
                    listEl.appendChild(item);
                });
            } catch (error) {
                console.error('Failed to load logs:', error);
            }
        }

        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/logs`);
            
            ws.onmessage = (event) => {
                const logsEl = document.getElementById('realtime-logs');
                const line = document.createElement('div');
                line.className = 'log-line';
                line.textContent = event.data;
                logsEl.appendChild(line);
                logsEl.scrollTop = logsEl.scrollHeight;
            };
            
            ws.onclose = () => {
                setTimeout(connectWebSocket, 3000);
            };
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
        }
    </script>
</body>
</html>
"""


@app.get("/")
async def root():
    """返回 HTML 界面"""
    return HTMLResponse(HTML_CONTENT)


if __name__ == "__main__":
    host = os.environ.get("WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("WEBUI_PORT", 8080))
    print(f"Starting WeBan WebUI on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
