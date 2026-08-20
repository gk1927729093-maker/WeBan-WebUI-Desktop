#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WeBan WebUI - 美观的中英双语管理界面"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomli_w
except ImportError:
    print("请安装依赖: pip install tomli-w fastapi uvicorn")
    sys.exit(1)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

# 数据目录设置
_data_dir = os.environ.get("WB_DATA_DIR", "")
if _data_dir:
    DATA_DIR = Path(_data_dir)
else:
    if getattr(sys, "frozen", False):
        DATA_DIR = Path(sys.executable).parent
    else:
        DATA_DIR = Path(__file__).parent

CONFIG_PATH = DATA_DIR / "config.toml"
LOGS_DIR = DATA_DIR / "logs"

app = FastAPI(title="WeBan WebUI", version="2.0.0")
active_connections: list[WebSocket] = []
task_process: subprocess.Popen | None = None
task_running = False
task_lock = threading.Lock()


def load_config() -> dict[str, Any]:
    """加载配置文件"""
    if not CONFIG_PATH.exists():
        return {"account": [], "settings": {}}
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        print(f"加载配置失败: {e}")
        return {"account": [], "settings": {}}


def save_config(config: dict[str, Any]) -> bool:
    """保存配置文件"""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "wb") as f:
            tomli_w.dump(config, f)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False


# API 端点
@app.get("/api/config")
async def get_config():
    """获取完整配置"""
    config = load_config()
    return JSONResponse(content=config)


@app.post("/api/config")
async def update_config(config: dict):
    """更新完整配置"""
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "配置保存成功"})
    return JSONResponse(content={"success": False, "message": "配置保存失败"}, status_code=500)


@app.get("/api/accounts")
async def get_accounts():
    """获取所有账号"""
    config = load_config()
    accounts = config.get("account", [])
    return JSONResponse(content={"success": True, "accounts": accounts})


@app.post("/api/accounts")
async def add_account(account: dict):
    """添加新账号"""
    required = ["username", "password"]
    if not all(k in account for k in required):
        return JSONResponse(content={"success": False, "message": "缺少必需字段"}, status_code=400)
    
    config = load_config()
    if "account" not in config:
        config["account"] = []
    
    # 检查是否已存在
    if any(acc.get("username") == account["username"] for acc in config["account"]):
        return JSONResponse(content={"success": False, "message": "用户名已存在"}, status_code=400)
    
    config["account"].append(account)
    
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "账号添加成功"})
    return JSONResponse(content={"success": False, "message": "保存失败"}, status_code=500)


@app.delete("/api/accounts/{username}")
async def delete_account(username: str):
    """删除账号"""
    config = load_config()
    accounts = config.get("account", [])
    
    original_len = len(accounts)
    config["account"] = [acc for acc in accounts if acc.get("username") != username]
    
    if len(config["account"]) == original_len:
        return JSONResponse(content={"success": False, "message": "账号不存在"}, status_code=404)
    
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "账号删除成功"})
    return JSONResponse(content={"success": False, "message": "保存失败"}, status_code=500)


@app.get("/api/settings")
async def get_settings():
    """获取全局设置"""
    config = load_config()
    settings = config.get("settings", {})
    return JSONResponse(content={"success": True, "settings": settings})


@app.post("/api/settings")
async def update_settings(settings: dict):
    """更新全局设置"""
    config = load_config()
    config["settings"] = settings
    
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "设置保存成功"})
    return JSONResponse(content={"success": False, "message": "保存失败"}, status_code=500)


@app.get("/api/task/status")
async def get_task_status():
    """获取任务状态"""
    return JSONResponse(content={"running": task_running})


@app.post("/api/task/start")
async def start_task():
    """启动任务"""
    global task_process, task_running
    
    with task_lock:
        if task_running:
            return JSONResponse(content={"success": False, "message": "任务已在运行"}, status_code=400)
        
        try:
            task_process = subprocess.Popen(
                [sys.executable, "main.py"],
                cwd=DATA_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            task_running = True
            return JSONResponse(content={"success": True, "message": "任务启动成功"})
        except Exception as e:
            return JSONResponse(content={"success": False, "message": f"启动失败: {e}"}, status_code=500)


@app.post("/api/task/stop")
async def stop_task():
    """停止任务"""
    global task_process, task_running
    
    with task_lock:
        if not task_running or task_process is None:
            return JSONResponse(content={"success": False, "message": "任务未运行"}, status_code=400)
        
        try:
            task_process.terminate()
            task_process.wait(timeout=5)
            task_running = False
            task_process = None
            return JSONResponse(content={"success": True, "message": "任务已停止"})
        except Exception as e:
            task_process.kill()
            task_running = False
            task_process = None
            return JSONResponse(content={"success": True, "message": "任务已强制停止"})


@app.get("/api/logs")
async def get_logs():
    """获取日志列表"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logs = []
    for log_file in LOGS_DIR.glob("*.log"):
        logs.append({
            "name": log_file.name,
            "size": log_file.stat().st_size,
            "modified": datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
        })
    return JSONResponse(content={"success": True, "logs": logs})


@app.get("/api/logs/{filename}")
async def get_log_content(filename: str):
    """获取日志内容"""
    log_file = LOGS_DIR / filename
    if not log_file.exists():
        return JSONResponse(content={"success": False, "message": "日志文件不存在"}, status_code=404)
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        return JSONResponse(content={"success": True, "content": content})
    except Exception as e:
        return JSONResponse(content={"success": False, "message": f"读取失败: {e}"}, status_code=500)


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket 实时日志推送"""
    await websocket.accept()
    active_connections.append(websocket)
    
    try:
        while True:
            # 保持连接活跃
            await asyncio.sleep(1)
            if task_running and task_process:
                # 这里可以读取进程输出并推送
                pass
    except WebSocketDisconnect:
        active_connections.remove(websocket)


@app.get("/", response_class=HTMLResponse)
async def root():
    """主页面 - 美观的中英双语界面"""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WeBan WebUI</title>
    <style>
        :root {
            /* 深色表面色阶 */
            --surface-0: #05070C;
            --surface-1: #0A0D12;
            --surface-2: #0F131C;
            --surface-3: #161D2B;
            --surface-4: #1E2636;
            
            /* 强调色 */
            --accent-primary: #38BDF8;
            --accent-secondary: #6EE7B7;
            --accent-danger: #F87171;
            --accent-warning: #FBBF24;
            
            /* 文本色 */
            --text-primary: #F8FAFC;
            --text-secondary: #CBD5E1;
            --text-tertiary: #94A3B8;
            
            /* 间距 */
            --spacing-xs: 0.5rem;
            --spacing-sm: 0.75rem;
            --spacing-md: 1rem;
            --spacing-lg: 1.5rem;
            --spacing-xl: 2rem;
            --spacing-2xl: 3rem;
            
            /* 圆角 */
            --radius-sm: 8px;
            --radius-md: 12px;
            --radius-lg: 16px;
            --radius-pill: 999px;
            --radius-circle: 50%;
            
            /* 字体 */
            --font-display: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
            --font-body: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: var(--font-body);
            background: var(--surface-0);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .app-container {
            display: grid;
            grid-template-columns: 240px 1fr;
            grid-template-rows: auto 1fr;
            min-height: 100vh;
        }
        
        /* 顶部导航栏 */
        .header {
            grid-column: 1 / -1;
            background: var(--surface-1);
            border-bottom: 1px solid var(--surface-3);
            padding: var(--spacing-md) var(--spacing-xl);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header h1 {
            font-size: clamp(1.25rem, 2vw, 1.5rem);
            font-weight: 600;
            letter-spacing: -0.02em;
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .lang-switcher {
            display: flex;
            gap: var(--spacing-xs);
            background: var(--surface-2);
            padding: var(--spacing-xs);
            border-radius: var(--radius-pill);
        }
        
        .lang-btn {
            padding: var(--spacing-xs) var(--spacing-md);
            border: none;
            background: transparent;
            color: var(--text-secondary);
            cursor: pointer;
            border-radius: var(--radius-pill);
            font-size: 0.875rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }
        
        .lang-btn.active {
            background: var(--accent-primary);
            color: var(--surface-0);
        }
        
        .lang-btn:hover:not(.active) {
            background: var(--surface-3);
            color: var(--text-primary);
        }
        
        /* 侧边栏 */
        .sidebar {
            background: var(--surface-1);
            border-right: 1px solid var(--surface-3);
            padding: var(--spacing-lg);
            display: flex;
            flex-direction: column;
            gap: var(--spacing-sm);
        }
        
        .nav-item {
            padding: var(--spacing-md);
            border-radius: var(--radius-md);
            background: transparent;
            border: none;
            color: var(--text-secondary);
            cursor: pointer;
            text-align: left;
            font-size: 0.9375rem;
            font-weight: 500;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: var(--spacing-sm);
        }
        
        .nav-item:hover {
            background: var(--surface-2);
            color: var(--text-primary);
        }
        
        .nav-item.active {
            background: var(--surface-3);
            color: var(--accent-primary);
            border-left: 3px solid var(--accent-primary);
        }
        
        .nav-icon {
            width: 20px;
            height: 20px;
            flex-shrink: 0;
        }
        
        /* 主内容区 */
        .main-content {
            padding: var(--spacing-xl);
            overflow-y: auto;
        }
        
        .page {
            display: none;
            animation: fadeIn 0.3s ease;
        }
        
        .page.active {
            display: block;
        }
        
        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .page-title {
            font-size: clamp(1.5rem, 3vw, 2rem);
            font-weight: 700;
            letter-spacing: -0.03em;
            margin-bottom: var(--spacing-lg);
            color: var(--text-primary);
        }
        
        /* 卡片 */
        .card {
            background: var(--surface-2);
            border-radius: var(--radius-lg);
            padding: var(--spacing-lg);
            margin-bottom: var(--spacing-lg);
            border: 1px solid var(--surface-3);
            transition: all 0.2s ease;
        }
        
        .card:hover {
            border-color: var(--surface-4);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }
        
        .card-title {
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: var(--spacing-md);
            color: var(--text-primary);
        }
        
        /* 按钮 */
        .btn {
            padding: var(--spacing-sm) var(--spacing-lg);
            border: none;
            border-radius: var(--radius-pill);
            font-size: 0.9375rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: var(--spacing-xs);
        }
        
        .btn-primary {
            background: var(--accent-primary);
            color: var(--surface-0);
        }
        
        .btn-primary:hover {
            background: #0EA5E9;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(56, 189, 248, 0.4);
        }
        
        .btn-primary:active {
            transform: translateY(0);
        }
        
        .btn-secondary {
            background: var(--surface-3);
            color: var(--text-primary);
        }
        
        .btn-secondary:hover {
            background: var(--surface-4);
        }
        
        .btn-danger {
            background: var(--accent-danger);
            color: var(--surface-0);
        }
        
        .btn-danger:hover {
            background: #EF4444;
            box-shadow: 0 4px 12px rgba(248, 113, 113, 0.4);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none !important;
        }
        
        /* 表单 */
        .form-group {
            margin-bottom: var(--spacing-lg);
        }
        
        .form-label {
            display: block;
            margin-bottom: var(--spacing-xs);
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-secondary);
        }
        
        .form-input {
            width: 100%;
            padding: var(--spacing-sm) var(--spacing-md);
            background: var(--surface-3);
            border: 1px solid var(--surface-4);
            border-radius: var(--radius-md);
            color: var(--text-primary);
            font-size: 0.9375rem;
            transition: all 0.2s ease;
        }
        
        .form-input:focus {
            outline: none;
            border-color: var(--accent-primary);
            box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.1);
        }
        
        .form-checkbox {
            display: flex;
            align-items: center;
            gap: var(--spacing-sm);
            cursor: pointer;
        }
        
        .form-checkbox input {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }
        
        /* 状态指示器 */
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: var(--spacing-xs);
            padding: var(--spacing-xs) var(--spacing-md);
            border-radius: var(--radius-pill);
            font-size: 0.875rem;
            font-weight: 500;
        }
        
        .status-badge.running {
            background: rgba(110, 231, 183, 0.1);
            color: var(--accent-secondary);
        }
        
        .status-badge.stopped {
            background: rgba(148, 163, 184, 0.1);
            color: var(--text-tertiary);
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: var(--radius-circle);
            animation: pulse 2s ease-in-out infinite;
        }
        
        .status-badge.running .status-dot {
            background: var(--accent-secondary);
        }
        
        .status-badge.stopped .status-dot {
            background: var(--text-tertiary);
            animation: none;
        }
        
        @keyframes pulse {
            0%, 100% {
                opacity: 1;
            }
            50% {
                opacity: 0.5;
            }
        }
        
        /* 表格 */
        .table-container {
            overflow-x: auto;
        }
        
        .table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .table th {
            text-align: left;
            padding: var(--spacing-md);
            background: var(--surface-3);
            color: var(--text-secondary);
            font-size: 0.875rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .table td {
            padding: var(--spacing-md);
            border-top: 1px solid var(--surface-3);
            color: var(--text-primary);
        }
        
        .table tr:hover {
            background: var(--surface-3);
        }
        
        /* 日志查看器 */
        .log-viewer {
            background: var(--surface-1);
            border-radius: var(--radius-md);
            padding: var(--spacing-md);
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.875rem;
            line-height: 1.5;
            color: var(--text-secondary);
            max-height: 500px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }
        
        .log-viewer::-webkit-scrollbar {
            width: 8px;
        }
        
        .log-viewer::-webkit-scrollbar-track {
            background: var(--surface-2);
        }
        
        .log-viewer::-webkit-scrollbar-thumb {
            background: var(--surface-4);
            border-radius: var(--radius-sm);
        }
        
        /* 空状态 */
        .empty-state {
            text-align: center;
            padding: var(--spacing-2xl);
            color: var(--text-tertiary);
        }
        
        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: var(--spacing-md);
            opacity: 0.5;
        }
        
        /* 响应式 */
        @media (max-width: 768px) {
            .app-container {
                grid-template-columns: 1fr;
            }
            
            .sidebar {
                display: none;
            }
            
            .main-content {
                padding: var(--spacing-md);
            }
        }
        
        /* 工具类 */
        .flex {
            display: flex;
        }
        
        .flex-col {
            flex-direction: column;
        }
        
        .items-center {
            align-items: center;
        }
        
        .justify-between {
            justify-content: space-between;
        }
        
        .gap-sm {
            gap: var(--spacing-sm);
        }
        
        .gap-md {
            gap: var(--spacing-md);
        }
        
        .mb-md {
            margin-bottom: var(--spacing-md);
        }
        
        .mb-lg {
            margin-bottom: var(--spacing-lg);
        }
    </style>
</head>
<body>
    <div class="app-container">
        <!-- 顶部导航栏 -->
        <header class="header">
            <h1>WeBan WebUI</h1>
            <div class="lang-switcher">
                <button class="lang-btn active" data-lang="zh">中文</button>
                <button class="lang-btn" data-lang="en">English</button>
            </div>
        </header>
        
        <!-- 侧边栏 -->
        <aside class="sidebar">
            <button class="nav-item active" data-page="dashboard">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>
                </svg>
                <span data-i18n="nav.dashboard">仪表盘</span>
            </button>
            <button class="nav-item" data-page="accounts">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
                </svg>
                <span data-i18n="nav.accounts">账号管理</span>
            </button>
            <button class="nav-item" data-page="settings">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                </svg>
                <span data-i18n="nav.settings">全局设置</span>
            </button>
            <button class="nav-item" data-page="logs">
                <svg class="nav-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
                <span data-i18n="nav.logs">日志查看</span>
            </button>
        </aside>
        
        <!-- 主内容区 -->
        <main class="main-content">
            <!-- Dashboard 页面 -->
            <div class="page active" id="page-dashboard">
                <h2 class="page-title" data-i18n="dashboard.title">仪表盘</h2>
                
                <div class="card">
                    <div class="flex items-center justify-between mb-lg">
                        <div>
                            <div class="card-title" data-i18n="dashboard.taskStatus">任务状态</div>
                            <div id="task-status" class="status-badge stopped">
                                <span class="status-dot"></span>
                                <span data-i18n="dashboard.stopped">已停止</span>
                            </div>
                        </div>
                        <div class="flex gap-md">
                            <button id="btn-start-task" class="btn btn-primary" data-i18n="dashboard.start">启动任务</button>
                            <button id="btn-stop-task" class="btn btn-danger" disabled data-i18n="dashboard.stop">停止任务</button>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-title" data-i18n="dashboard.realtimeLog">实时日志</div>
                    <div id="realtime-log" class="log-viewer">
                        <span data-i18n="dashboard.waitingLog">等待日志输出...</span>
                    </div>
                </div>
            </div>
            
            <!-- 账号管理页面 -->
            <div class="page" id="page-accounts">
                <h2 class="page-title" data-i18n="accounts.title">账号管理</h2>
                
                <div class="card">
                    <div class="card-title" data-i18n="accounts.addNew">添加新账号</div>
                    <form id="form-add-account" class="mb-lg">
                        <div class="form-group">
                            <label class="form-label" data-i18n="accounts.username">用户名</label>
                            <input type="text" class="form-input" id="input-username" required>
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="accounts.password">密码</label>
                            <input type="password" class="form-input" id="input-password" required>
                        </div>
                        <button type="submit" class="btn btn-primary" data-i18n="accounts.add">添加账号</button>
                    </form>
                </div>
                
                <div class="card">
                    <div class="card-title" data-i18n="accounts.list">账号列表</div>
                    <div class="table-container">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th data-i18n="accounts.username">用户名</th>
                                    <th data-i18n="accounts.password">密码</th>
                                    <th data-i18n="accounts.actions">操作</th>
                                </tr>
                            </thead>
                            <tbody id="accounts-table-body">
                                <tr>
                                    <td colspan="3">
                                        <div class="empty-state">
                                            <div class="empty-state-icon">📭</div>
                                            <div data-i18n="accounts.empty">暂无账号</div>
                                        </div>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <!-- 全局设置页面 -->
            <div class="page" id="page-settings">
                <h2 class="page-title" data-i18n="settings.title">全局设置</h2>
                
                <div class="card">
                    <form id="form-settings">
                        <div class="form-group">
                            <label class="form-checkbox">
                                <input type="checkbox" id="setting-study-mode">
                                <span data-i18n="settings.studyMode">学习模式</span>
                            </label>
                        </div>
                        <div class="form-group">
                            <label class="form-checkbox">
                                <input type="checkbox" id="setting-exam-mode">
                                <span data-i18n="settings.examMode">考试模式</span>
                            </label>
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.concurrency">并发线程数</label>
                            <input type="number" class="form-input" id="setting-concurrency" min="1" max="10" value="3">
                        </div>
                        <div class="form-group">
                            <label class="form-label" data-i18n="settings.timeout">超时时间（秒）</label>
                            <input type="number" class="form-input" id="setting-timeout" min="10" max="300" value="60">
                        </div>
                        <button type="submit" class="btn btn-primary" data-i18n="settings.save">保存设置</button>
                    </form>
                </div>
            </div>
            
            <!-- 日志查看页面 -->
            <div class="page" id="page-logs">
                <h2 class="page-title" data-i18n="logs.title">日志查看</h2>
                
                <div class="card">
                    <div class="card-title" data-i18n="logs.files">日志文件</div>
                    <div id="logs-list" class="mb-lg">
                        <div class="empty-state">
                            <div class="empty-state-icon">📄</div>
                            <div data-i18n="logs.empty">暂无日志文件</div>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-title" data-i18n="logs.content">日志内容</div>
                    <div id="log-content" class="log-viewer">
                        <span data-i18n="logs.selectFile">请选择日志文件...</span>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <script>
        // 国际化翻译
        const i18n = {
            zh: {
                'nav.dashboard': '仪表盘',
                'nav.accounts': '账号管理',
                'nav.settings': '全局设置',
                'nav.logs': '日志查看',
                'dashboard.title': '仪表盘',
                'dashboard.taskStatus': '任务状态',
                'dashboard.stopped': '已停止',
                'dashboard.running': '运行中',
                'dashboard.start': '启动任务',
                'dashboard.stop': '停止任务',
                'dashboard.realtimeLog': '实时日志',
                'dashboard.waitingLog': '等待日志输出...',
                'accounts.title': '账号管理',
                'accounts.addNew': '添加新账号',
                'accounts.username': '用户名',
                'accounts.password': '密码',
                'accounts.add': '添加账号',
                'accounts.list': '账号列表',
                'accounts.actions': '操作',
                'accounts.delete': '删除',
                'accounts.empty': '暂无账号',
                'accounts.deleteConfirm': '确定要删除账号',
                'accounts.addSuccess': '账号添加成功',
                'accounts.addFailed': '添加失败',
                'accounts.deleteSuccess': '账号删除成功',
                'accounts.deleteFailed': '删除失败',
                'settings.title': '全局设置',
                'settings.studyMode': '学习模式',
                'settings.examMode': '考试模式',
                'settings.concurrency': '并发线程数',
                'settings.timeout': '超时时间（秒）',
                'settings.save': '保存设置',
                'settings.saveSuccess': '设置保存成功',
                'settings.saveFailed': '保存失败',
                'logs.title': '日志查看',
                'logs.files': '日志文件',
                'logs.content': '日志内容',
                'logs.empty': '暂无日志文件',
                'logs.selectFile': '请选择日志文件...',
                'logs.view': '查看',
                'task.startSuccess': '任务启动成功',
                'task.startFailed': '启动失败',
                'task.stopSuccess': '任务停止成功',
                'task.stopFailed': '停止失败'
            },
            en: {
                'nav.dashboard': 'Dashboard',
                'nav.accounts': 'Accounts',
                'nav.settings': 'Settings',
                'nav.logs': 'Logs',
                'dashboard.title': 'Dashboard',
                'dashboard.taskStatus': 'Task Status',
                'dashboard.stopped': 'Stopped',
                'dashboard.running': 'Running',
                'dashboard.start': 'Start Task',
                'dashboard.stop': 'Stop Task',
                'dashboard.realtimeLog': 'Realtime Log',
                'dashboard.waitingLog': 'Waiting for log output...',
                'accounts.title': 'Account Management',
                'accounts.addNew': 'Add New Account',
                'accounts.username': 'Username',
                'accounts.password': 'Password',
                'accounts.add': 'Add Account',
                'accounts.list': 'Account List',
                'accounts.actions': 'Actions',
                'accounts.delete': 'Delete',
                'accounts.empty': 'No accounts yet',
                'accounts.deleteConfirm': 'Delete account',
                'accounts.addSuccess': 'Account added successfully',
                'accounts.addFailed': 'Failed to add account',
                'accounts.deleteSuccess': 'Account deleted successfully',
                'accounts.deleteFailed': 'Failed to delete account',
                'settings.title': 'Global Settings',
                'settings.studyMode': 'Study Mode',
                'settings.examMode': 'Exam Mode',
                'settings.concurrency': 'Concurrency',
                'settings.timeout': 'Timeout (seconds)',
                'settings.save': 'Save Settings',
                'settings.saveSuccess': 'Settings saved successfully',
                'settings.saveFailed': 'Failed to save settings',
                'logs.title': 'Log Viewer',
                'logs.files': 'Log Files',
                'logs.content': 'Log Content',
                'logs.empty': 'No log files yet',
                'logs.selectFile': 'Select a log file...',
                'logs.view': 'View',
                'task.startSuccess': 'Task started successfully',
                'task.startFailed': 'Failed to start task',
                'task.stopSuccess': 'Task stopped successfully',
                'task.stopFailed': 'Failed to stop task'
            }
        };

        let currentLang = localStorage.getItem('lang') || 'zh';
        let ws = null;

        // 初始化
        document.addEventListener('DOMContentLoaded', () => {
            // 设置初始语言
            setLanguage(currentLang);
            
            // 语言切换
            document.querySelectorAll('.lang-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const lang = btn.dataset.lang;
                    setLanguage(lang);
                });
            });
            
            // 导航切换
            document.querySelectorAll('.nav-item').forEach(item => {
                item.addEventListener('click', () => {
                    const page = item.dataset.page;
                    switchPage(page);
                });
            });
            
            // 加载初始数据
            loadTaskStatus();
            loadAccounts();
            loadSettings();
            loadLogs();
            
            // 连接 WebSocket
            connectWebSocket();
            
            // 绑定事件
            bindEvents();
        });

        // 设置语言
        function setLanguage(lang) {
            currentLang = lang;
            localStorage.setItem('lang', lang);
            
            // 更新语言按钮状态
            document.querySelectorAll('.lang-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.lang === lang);
            });
            
            // 更新所有翻译
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const key = el.dataset.i18n;
                el.textContent = i18n[lang][key] || key;
            });
            
            // 更新 HTML lang 属性
            document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
        }

        // 获取翻译
        function t(key) {
            return i18n[currentLang][key] || key;
        }

        // 切换页面
        function switchPage(pageName) {
            // 更新导航状态
            document.querySelectorAll('.nav-item').forEach(item => {
                item.classList.toggle('active', item.dataset.page === pageName);
            });
            
            // 显示对应页面
            document.querySelectorAll('.page').forEach(page => {
                page.classList.toggle('active', page.id === `page-${pageName}`);
            });
            
            // 加载页面数据
            if (pageName === 'accounts') loadAccounts();
            if (pageName === 'settings') loadSettings();
            if (pageName === 'logs') loadLogs();
        }

        // 绑定事件
        function bindEvents() {
            // 启动任务
            document.getElementById('btn-start-task').addEventListener('click', async () => {
                try {
                    const response = await fetch('/api/task/start', { method: 'POST' });
                    const data = await response.json();
                    if (data.success) {
                        showNotification(t('task.startSuccess'), 'success');
                        loadTaskStatus();
                    } else {
                        showNotification(t('task.startFailed') + ': ' + data.message, 'error');
                    }
                } catch (error) {
                    showNotification(t('task.startFailed') + ': ' + error.message, 'error');
                }
            });
            
            // 停止任务
            document.getElementById('btn-stop-task').addEventListener('click', async () => {
                try {
                    const response = await fetch('/api/task/stop', { method: 'POST' });
                    const data = await response.json();
                    if (data.success) {
                        showNotification(t('task.stopSuccess'), 'success');
                        loadTaskStatus();
                    } else {
                        showNotification(t('task.stopFailed') + ': ' + data.message, 'error');
                    }
                } catch (error) {
                    showNotification(t('task.stopFailed') + ': ' + error.message, 'error');
                }
            });
            
            // 添加账号
            document.getElementById('form-add-account').addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('input-username').value;
                const password = document.getElementById('input-password').value;
                
                try {
                    const response = await fetch('/api/accounts', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    const data = await response.json();
                    if (data.success) {
                        showNotification(t('accounts.addSuccess'), 'success');
                        document.getElementById('form-add-account').reset();
                        loadAccounts();
                    } else {
                        showNotification(t('accounts.addFailed') + ': ' + data.message, 'error');
                    }
                } catch (error) {
                    showNotification(t('accounts.addFailed') + ': ' + error.message, 'error');
                }
            });
            
            // 保存设置
            document.getElementById('form-settings').addEventListener('submit', async (e) => {
                e.preventDefault();
                const settings = {
                    study_mode: document.getElementById('setting-study-mode').checked,
                    exam_mode: document.getElementById('setting-exam-mode').checked,
                    concurrency: parseInt(document.getElementById('setting-concurrency').value),
                    timeout: parseInt(document.getElementById('setting-timeout').value)
                };
                
                try {
                    const response = await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(settings)
                    });
                    const data = await response.json();
                    if (data.success) {
                        showNotification(t('settings.saveSuccess'), 'success');
                    } else {
                        showNotification(t('settings.saveFailed') + ': ' + data.message, 'error');
                    }
                } catch (error) {
                    showNotification(t('settings.saveFailed') + ': ' + error.message, 'error');
                }
            });
        }

        // 加载任务状态
        async function loadTaskStatus() {
            try {
                const response = await fetch('/api/task/status');
                const data = await response.json();
                
                const statusEl = document.getElementById('task-status');
                const startBtn = document.getElementById('btn-start-task');
                const stopBtn = document.getElementById('btn-stop-task');
                
                if (data.running) {
                    statusEl.className = 'status-badge running';
                    statusEl.querySelector('span:last-child').textContent = t('dashboard.running');
                    startBtn.disabled = true;
                    stopBtn.disabled = false;
                } else {
                    statusEl.className = 'status-badge stopped';
                    statusEl.querySelector('span:last-child').textContent = t('dashboard.stopped');
                    startBtn.disabled = false;
                    stopBtn.disabled = true;
                }
            } catch (error) {
                console.error('Failed to load task status:', error);
            }
        }

        // 加载账号列表
        async function loadAccounts() {
            try {
                const response = await fetch('/api/accounts');
                const data = await response.json();
                
                const tbody = document.getElementById('accounts-table-body');
                
                if (!data.accounts || data.accounts.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="3">
                                <div class="empty-state">
                                    <div class="empty-state-icon">📭</div>
                                    <div>${t('accounts.empty')}</div>
                                </div>
                            </td>
                        </tr>
                    `;
                    return;
                }
                
                tbody.innerHTML = data.accounts.map(account => `
                    <tr>
                        <td>${escapeHtml(account.username)}</td>
                        <td>••••••••</td>
                        <td>
                            <button class="btn btn-danger btn-delete-account" data-username="${escapeHtml(account.username)}">
                                ${t('accounts.delete')}
                            </button>
                        </td>
                    </tr>
                `).join('');
                
                // 绑定删除按钮
                tbody.querySelectorAll('.btn-delete-account').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const username = btn.dataset.username;
                        if (confirm(`${t('accounts.deleteConfirm')} "${username}"?`)) {
                            try {
                                const response = await fetch(`/api/accounts/${encodeURIComponent(username)}`, {
                                    method: 'DELETE'
                                });
                                const data = await response.json();
                                if (data.success) {
                                    showNotification(t('accounts.deleteSuccess'), 'success');
                                    loadAccounts();
                                } else {
                                    showNotification(t('accounts.deleteFailed') + ': ' + data.message, 'error');
                                }
                            } catch (error) {
                                showNotification(t('accounts.deleteFailed') + ': ' + error.message, 'error');
                            }
                        }
                    });
                });
            } catch (error) {
                console.error('Failed to load accounts:', error);
            }
        }

        // 加载设置
        async function loadSettings() {
            try {
                const response = await fetch('/api/settings');
                const data = await response.json();
                
                if (data.success && data.settings) {
                    const settings = data.settings;
                    document.getElementById('setting-study-mode').checked = settings.study_mode || false;
                    document.getElementById('setting-exam-mode').checked = settings.exam_mode || false;
                    document.getElementById('setting-concurrency').value = settings.concurrency || 3;
                    document.getElementById('setting-timeout').value = settings.timeout || 60;
                }
            } catch (error) {
                console.error('Failed to load settings:', error);
            }
        }

        // 加载日志列表
        async function loadLogs() {
            try {
                const response = await fetch('/api/logs');
                const data = await response.json();
                
                const listEl = document.getElementById('logs-list');
                
                if (!data.logs || data.logs.length === 0) {
                    listEl.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">📄</div>
                            <div>${t('logs.empty')}</div>
                        </div>
                    `;
                    return;
                }
                
                listEl.innerHTML = data.logs.map(log => `
                    <div style="padding: var(--spacing-sm); border-bottom: 1px solid var(--surface-3); display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-weight: 500; color: var(--text-primary);">${escapeHtml(log.name)}</div>
                            <div style="font-size: 0.875rem; color: var(--text-tertiary);">
                                ${formatBytes(log.size)} • ${new Date(log.modified).toLocaleString()}
                            </div>
                        </div>
                        <button class="btn btn-secondary btn-view-log" data-filename="${escapeHtml(log.name)}">
                            ${t('logs.view')}
                        </button>
                    </div>
                `).join('');
                
                // 绑定查看按钮
                listEl.querySelectorAll('.btn-view-log').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const filename = btn.dataset.filename;
                        try {
                            const response = await fetch(`/api/logs/${encodeURIComponent(filename)}`);
                            const data = await response.json();
                            if (data.success) {
                                document.getElementById('log-content').textContent = data.content;
                            }
                        } catch (error) {
                            console.error('Failed to load log content:', error);
                        }
                    });
                });
            } catch (error) {
                console.error('Failed to load logs:', error);
            }
        }

        // 连接 WebSocket
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws/logs`);
            
            ws.onmessage = (event) => {
                const logEl = document.getElementById('realtime-log');
                logEl.textContent += event.data + '\n';
                logEl.scrollTop = logEl.scrollHeight;
            };
            
            ws.onclose = () => {
                setTimeout(connectWebSocket, 3000);
            };
        }

        // 显示通知
        function showNotification(message, type = 'info') {
            alert(message);
        }

        // HTML 转义
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // 格式化字节
        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
        }

        // 定期刷新任务状态
        setInterval(loadTaskStatus, 3000);
    </script>
</body>
</html>
"""
    )


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("WEBUI_PORT", "8080"))
    print(f"\n{'='*50}")
    print(f"  WeBan WebUI 正在启动...")
    print(f"  访问地址: http://127.0.0.1:{port}")
    print(f"  配置文件: {CONFIG_PATH}")
    print(f"  日志目录: {LOGS_DIR}")
    print(f"{'='*50}\n")
    
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
