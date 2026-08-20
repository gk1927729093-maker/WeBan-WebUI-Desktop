#!/usr/bin/env python3
"""
WeBan WebUI - 美观的深色主题中英双语界面
"""
import os
import json
import subprocess
import threading
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

try:
    import tomli
    import tomli_w
except ImportError:
    tomli = None
    tomli_w = None

# 配置
CONFIG_FILE = Path("config.toml")
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# 全局状态
app = FastAPI(title="WeBan WebUI")
task_process: Optional[subprocess.Popen] = None
task_running = False
websocket_clients = []

# 日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ========== API 端点 ==========

@app.get("/api/task/status")
async def get_task_status():
    """获取任务状态"""
    return {"running": task_running}


@app.post("/api/task/start")
async def start_task():
    """启动任务"""
    global task_process, task_running
    
    if task_running:
        return {"success": False, "message": "Task already running"}
    
    try:
        task_process = subprocess.Popen(
            ["python", "main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        task_running = True
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to start task: {e}")
        return {"success": False, "message": str(e)}


@app.post("/api/task/stop")
async def stop_task():
    """停止任务"""
    global task_process, task_running
    
    if not task_running:
        return {"success": False, "message": "Task not running"}
    
    try:
        if task_process:
            task_process.terminate()
            task_process.wait(timeout=5)
        task_running = False
        return {"success": True}
    except Exception as e:
        logger.error(f"Failed to stop task: {e}")
        return {"success": False, "message": str(e)}


@app.get("/api/accounts")
async def get_accounts():
    """获取账号列表"""
    config = load_config()
    accounts = config.get("accounts", [])
    return {"accounts": accounts}


@app.post("/api/accounts")
async def add_account(data: Dict[str, Any]):
    """添加账号"""
    config = load_config()
    if "accounts" not in config:
        config["accounts"] = []
    
    config["accounts"].append({
        "username": data.get("username"),
        "password": data.get("password")
    })
    
    save_config(config)
    return {"success": True}


@app.delete("/api/accounts/{username}")
async def delete_account(username: str):
    """删除账号"""
    config = load_config()
    if "accounts" in config:
        config["accounts"] = [
            acc for acc in config["accounts"]
            if acc.get("username") != username
        ]
        save_config(config)
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
    config["settings"] = data
    save_config(config)
    return {"success": True}


@app.get("/api/logs")
async def get_logs():
    """获取日志列表"""
    logs = []
    if LOG_DIR.exists():
        for log_file in sorted(LOG_DIR.glob("*.log"), reverse=True):
            logs.append({
                "name": log_file.name,
                "size": log_file.stat().st_size,
                "modified": log_file.stat().st_mtime
            })
    return {"logs": logs[:50]}


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket 实时日志推送"""
    await websocket.accept()
    websocket_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_clients.remove(websocket)


# ========== 配置管理 ==========

def load_config() -> Dict[str, Any]:
    """加载配置"""
    if not CONFIG_FILE.exists():
        return {}
    
    try:
        if tomli:
            with open(CONFIG_FILE, "rb") as f:
                return tomli.load(f)
    except:
        pass
    return {}


def save_config(config: Dict[str, Any]):
    """保存配置"""
    if tomli_w is None:
        logger.error("tomli_w not installed, cannot save config")
        return
    
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(config, f)

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
            display: flex;
            gap: 0.5rem;
            background: var(--surface-2);
            padding: 4px;
            border-radius: var(--radius-full);
        }

        .lang-btn {
            padding: 0.5rem 1rem;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            border-radius: var(--radius-full);
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.875rem;
        }

        .lang-btn.active {
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
            font-weight: 500;
            color: var(--text-primary);
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
                <button class="lang-btn active" data-lang="zh">中文</button>
                <button class="lang-btn" data-lang="en">English</button>
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
                            <label class="form-label" data-i18n="accounts.username">用户名</label>
                            <input type="text" name="username" class="form-input" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="accounts.password">密码</label>
                            <input type="password" name="password" class="form-input" required>
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
                            <input type="checkbox" name="study_mode" id="study_mode">
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.examMode">考试模式</label>
                            <input type="checkbox" name="exam_mode" id="exam_mode">
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.concurrent">并发数</label>
                            <input type="number" name="concurrent" class="form-input" value="3" min="1" max="10">
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
                'accounts.username': '用户名',
                'accounts.password': '密码',
                'accounts.add': '添加账号',
                'accounts.list': '账号列表',
                'accounts.delete': '删除',
                'settings.title': '全局设置',
                'settings.studyMode': '学习模式',
                'settings.examMode': '考试模式',
                'settings.concurrent': '并发数',
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
                'accounts.username': 'Username',
                'accounts.password': 'Password',
                'accounts.add': 'Add Account',
                'accounts.list': 'Account List',
                'accounts.delete': 'Delete',
                'settings.title': 'Global Settings',
                'settings.studyMode': 'Study Mode',
                'settings.examMode': 'Exam Mode',
                'settings.concurrent': 'Concurrent',
                'settings.save': 'Save Settings',
                'logs.title': 'Log History',
                'msg.success': 'Success',
                'msg.error': 'Error'
            }
        };

        let currentLang = localStorage.getItem('lang') || 'zh';
        let ws = null;

        document.addEventListener('DOMContentLoaded', function() {
            setLanguage(currentLang);
            
            document.querySelectorAll('.lang-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    setLanguage(btn.dataset.lang);
                });
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
                    }
                } catch (error) {
                    alert(i18n[currentLang]['msg.error'] + ': ' + error.message);
                }
            });
            
            document.getElementById('form-settings').addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData);
                data.study_mode = document.getElementById('study_mode').checked;
                data.exam_mode = document.getElementById('exam_mode').checked;
                
                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    const result = await response.json();
                    if (result.success) {
                        alert(i18n[currentLang]['msg.success']);
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
            
            document.querySelectorAll('.lang-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.lang === lang);
            });
            
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const key = el.dataset.i18n;
                const translation = i18n[lang][key];
                if (translation) {
                    el.textContent = translation;
                }
            });
            
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
                            <div class="account-username">${escapeHtml(account.username)}</div>
                            <div class="account-password">${'*'.repeat(account.password.length)}</div>
                        </div>
                        <button class="btn-delete" onclick="deleteAccount('${escapeHtml(account.username)}')">
                            ${i18n[currentLang]['accounts.delete']}
                        </button>
                    `;
                    listEl.appendChild(item);
                });
            } catch (error) {
                console.error('Failed to load accounts:', error);
            }
        }

        async function deleteAccount(username) {
            if (!confirm(`Delete account "${username}"?`)) return;
            
            try {
                const response = await fetch(`/api/accounts/${encodeURIComponent(username)}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                if (data.success) {
                    loadAccounts();
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
                    document.getElementById('study_mode').checked = data.study_mode;
                }
                if (data.exam_mode !== undefined) {
                    document.getElementById('exam_mode').checked = data.exam_mode;
                }
                if (data.concurrent !== undefined) {
                    document.querySelector('[name="concurrent"]').value = data.concurrent;
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
    port = int(os.environ.get("WEBUI_PORT", 8080))
    print(f"Starting WeBan WebUI on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
