#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WeBan WebUI - Complete Single-File Application"""
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
    print("Please install dependencies: pip install tomli-w fastapi uvicorn websockets")
    sys.exit(1)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
# from loguru import logger

# Data directory setup
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

app = FastAPI(title="WeBan WebUI", version="1.0.0")
active_connections: list[WebSocket] = []
task_process: subprocess.Popen | None = None
task_running = False
task_lock = threading.Lock()


def load_config() -> dict[str, Any]:
    """Load configuration from TOML file"""
    if not CONFIG_PATH.exists():
        return {"account": [], "settings": {}}
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {"account": [], "settings": {}}


def save_config(config: dict[str, Any]) -> bool:
    """Save configuration to TOML file"""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "wb") as f:
            tomli_w.dump(config, f)
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


# API Endpoints
@app.get("/api/config")
async def get_config():
    """Get full configuration"""
    config = load_config()
    return JSONResponse(content=config)


@app.post("/api/config")
async def update_config(config: dict):
    """Update full configuration"""
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "Configuration saved successfully"})
    return JSONResponse(content={"success": False, "message": "Failed to save configuration"}, status_code=500)


@app.get("/api/accounts")
async def get_accounts():
    """Get all accounts"""
    config = load_config()
    accounts = config.get("account", [])
    return JSONResponse(content={"success": True, "accounts": accounts})


@app.post("/api/accounts")
async def add_account(account: dict):
    """Add new account"""
    required = ["username", "password"]
    if not all(k in account for k in required):
        return JSONResponse(content={"success": False, "message": "Missing required fields"}, status_code=400)
    
    config = load_config()
    accounts = config.get("account", [])
    
    # Check duplicate
    if any(acc.get("username") == account["username"] for acc in accounts):
        return JSONResponse(content={"success": False, "message": "Account already exists"}, status_code=400)
    
    accounts.append(account)
    config["account"] = accounts
    
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "Account added successfully"})
    return JSONResponse(content={"success": False, "message": "Failed to save account"}, status_code=500)


@app.delete("/api/accounts/{username}")
async def delete_account(username: str):
    """Delete account"""
    config = load_config()
    accounts = config.get("account", [])
    
    filtered = [acc for acc in accounts if acc.get("username") != username]
    if len(filtered) == len(accounts):
        return JSONResponse(content={"success": False, "message": "Account not found"}, status_code=404)
    
    config["account"] = filtered
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "Account deleted successfully"})
    return JSONResponse(content={"success": False, "message": "Failed to delete account"}, status_code=500)


@app.get("/api/settings")
async def get_settings():
    """Get global settings"""
    config = load_config()
    settings = config.get("settings", {})
    return JSONResponse(content={"success": True, "settings": settings})


@app.post("/api/settings")
async def update_settings(settings: dict):
    """Update global settings"""
    config = load_config()
    config["settings"] = settings
    
    if save_config(config):
        return JSONResponse(content={"success": True, "message": "Settings updated successfully"})
    return JSONResponse(content={"success": False, "message": "Failed to update settings"}, status_code=500)


@app.get("/api/task/status")
async def get_task_status():
    """Get task running status"""
    global task_running, task_process
    is_alive = task_process is not None and task_process.poll() is None
    return JSONResponse(content={"running": is_alive and task_running})


@app.post("/api/task/start")
async def start_task():
    """Start main task"""
    global task_running, task_process
    
    with task_lock:
        if task_running and task_process and task_process.poll() is None:
            return JSONResponse(content={"success": False, "message": "Task already running"}, status_code=400)
        
        main_script = DATA_DIR / "main.py"
        if not main_script.exists():
            return JSONResponse(content={"success": False, "message": "main.py not found"}, status_code=404)
        
        try:
            task_process = subprocess.Popen(
                [sys.executable, str(main_script)],
                cwd=str(DATA_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            task_running = True
            
            # Start log streaming thread
            threading.Thread(target=stream_task_logs, daemon=True).start()
            
            return JSONResponse(content={"success": True, "message": "Task started successfully"})
        except Exception as e:
            logger.error(f"Failed to start task: {e}")
            return JSONResponse(content={"success": False, "message": str(e)}, status_code=500)


@app.post("/api/task/stop")
async def stop_task():
    """Stop main task"""
    global task_running, task_process
    
    with task_lock:
        if not task_running or not task_process:
            return JSONResponse(content={"success": False, "message": "No task running"}, status_code=400)
        
        try:
            task_process.terminate()
            task_process.wait(timeout=5)
            task_running = False
            return JSONResponse(content={"success": True, "message": "Task stopped successfully"})
        except subprocess.TimeoutExpired:
            task_process.kill()
            task_running = False
            return JSONResponse(content={"success": True, "message": "Task force killed"})
        except Exception as e:
            logger.error(f"Failed to stop task: {e}")
            return JSONResponse(content={"success": False, "message": str(e)}, status_code=500)


@app.get("/api/logs")
async def get_log_files():
    """Get all log files"""
    if not LOGS_DIR.exists():
        return JSONResponse(content={"success": True, "logs": []})
    
    logs = []
    for account_dir in LOGS_DIR.iterdir():
        if account_dir.is_dir():
            for log_file in account_dir.glob("*.log"):
                stat = log_file.stat()
                logs.append({
                    "account": account_dir.name,
                    "filename": log_file.name,
                    "size": stat.st_size,
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
    
    logs.sort(key=lambda x: x["mtime"], reverse=True)
    return JSONResponse(content={"success": True, "logs": logs})


@app.get("/api/logs/{account}/{filename}")
async def get_log_content(account: str, filename: str):
    """Get log file content"""
    log_path = LOGS_DIR / account / filename
    if not log_path.exists():
        return JSONResponse(content={"success": False, "message": "Log file not found"}, status_code=404)
    
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        return JSONResponse(content={"success": True, "content": content})
    except Exception as e:
        logger.error(f"Failed to read log: {e}")
        return JSONResponse(content={"success": False, "message": str(e)}, status_code=500)


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for real-time logs"""
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)


def stream_task_logs():
    """Stream task logs to WebSocket clients"""
    global task_process
    if not task_process or not task_process.stdout:
        return
    
    for line in task_process.stdout:
        if not line:
            break
        
        message = json.dumps({"type": "log", "content": line.strip()})
        
        # Send to all connected clients
        for connection in active_connections[:]:
            try:
                asyncio.run(connection.send_text(message))
            except Exception:
                active_connections.remove(connection)


# Frontend HTML
@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTMLResponse(content=HTML_TEMPLATE)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WeBan WebUI</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Inter,-apple-system,sans-serif;background:#0A0D12;color:#F8FAFC;min-height:100vh}
.container{display:flex;height:100vh}
.sidebar{width:240px;background:#0F172A;border-right:1px solid #1E293B;padding:1.5rem 1rem}
.logo{font-size:1.25rem;font-weight:600;margin-bottom:2rem;color:#38BDF8}
.nav-item{padding:0.75rem 1rem;margin-bottom:0.5rem;border-radius:8px;cursor:pointer;transition:all 0.2s;color:#94A3B8}
.nav-item:hover{background:#1E293B;color:#F8FAFC}
.nav-item.active{background:#1E293B;color:#38BDF8;border-left:3px solid #38BDF8}
.main{flex:1;overflow-y:auto;padding:2rem}
.header{margin-bottom:2rem}
.header h1{font-size:1.75rem;margin-bottom:0.5rem}
.header p{color:#94A3B8;font-size:0.875rem}
.card{background:#111827;border:1px solid #1E293B;border-radius:12px;padding:1.5rem;margin-bottom:1.5rem}
.card-title{font-size:1.125rem;font-weight:600;margin-bottom:1rem;color:#F8FAFC}
.form-group{margin-bottom:1rem}
.form-label{display:block;margin-bottom:0.5rem;font-size:0.875rem;color:#94A3B8}
.form-input{width:100%;padding:0.625rem 0.875rem;background:#1E293B;border:1px solid #334155;border-radius:8px;color:#F8FAFC;font-size:0.875rem;transition:all 0.2s}
.form-input:focus{outline:none;border-color:#38BDF8}
.form-input::placeholder{color:#475569}
.btn{padding:0.625rem 1.25rem;border:none;border-radius:8px;font-size:0.875rem;font-weight:500;cursor:pointer;transition:all 0.2s}
.btn-primary{background:#38BDF8;color:#0A0D12}
.btn-primary:hover{background:#22D3EE}
.btn-danger{background:#EF4444;color:#FFF}
.btn-danger:hover{background:#DC2626}
.btn-secondary{background:#334155;color:#F8FAFC}
.btn-secondary:hover{background:#475569}
.btn:disabled{opacity:0.5;cursor:not-allowed}
.btn-group{display:flex;gap:0.75rem;margin-bottom:1.5rem}
.account-item{display:flex;justify-content:space-between;align-items:center;padding:1rem;background:#1E293B;border-radius:8px;margin-bottom:0.75rem}
.account-info{flex:1}
.account-username{font-weight:500;margin-bottom:0.25rem}
.account-meta{font-size:0.75rem;color:#64748B}
.log-container{background:#0F172A;border:1px solid #1E293B;border-radius:8px;padding:1rem;height:400px;overflow-y:auto;font-family:Consolas,Monaco,monospace;font-size:0.8rem;line-height:1.5}
.log-line{margin-bottom:0.25rem;color:#94A3B8}
.log-line.error{color:#F87171}
.log-line.success{color:#4ADE80}
.log-line.warning{color:#FBBF24}
.status-badge{display:inline-block;padding:0.25rem 0.75rem;border-radius:12px;font-size:0.75rem;font-weight:500}
.status-running{background:#10B98133;color:#4ADE80}
.status-stopped{background:#EF444433;color:#F87171}
.log-item{display:flex;justify-content:space-between;align-items:center;padding:0.875rem;background:#1E293B;border-radius:8px;margin-bottom:0.5rem}
.log-meta{font-size:0.75rem;color:#64748B}
.page{display:none}
.page.active{display:block}
.checkbox-group{display:flex;align-items:center;gap:0.5rem;margin-bottom:0.75rem}
.checkbox{width:18px;height:18px;cursor:pointer}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:768px){.container{flex-direction:column}.sidebar{width:100%;border-right:none;border-bottom:1px solid #1E293B}.grid-2{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
<aside class="sidebar">
<div class="logo">WeBan WebUI</div>
<nav>
<div class="nav-item active" onclick="switchPage('dashboard')">Dashboard</div>
<div class="nav-item" onclick="switchPage('accounts')">Account Management</div>
<div class="nav-item" onclick="switchPage('settings')">Global Settings</div>
<div class="nav-item" onclick="switchPage('logs')">Log Viewer</div>
</nav>
</aside>
<main class="main">
<div id="dashboard" class="page active">
<div class="header">
<h1>Dashboard</h1>
<p>Control and monitor WeBan tasks</p>
</div>
<div class="card">
<div class="card-title">Task Control</div>
<div class="btn-group">
<button class="btn btn-primary" onclick="startTask()" id="startBtn">Start Task</button>
<button class="btn btn-danger" onclick="stopTask()" id="stopBtn" disabled>Stop Task</button>
<span class="status-badge status-stopped" id="statusBadge">Stopped</span>
</div>
</div>
<div class="card">
<div class="card-title">Real-time Logs</div>
<div class="log-container" id="realtimeLogs"></div>
</div>
</div>
<div id="accounts" class="page">
<div class="header">
<h1>Account Management</h1>
<p>Add and manage WeBan accounts</p>
</div>
<div class="card">
<div class="card-title">Add New Account</div>
<div class="form-group">
<label class="form-label">Username</label>
<input type="text" class="form-input" id="newUsername" placeholder="Enter username">
</div>
<div class="form-group">
<label class="form-label">Password</label>
<input type="password" class="form-input" id="newPassword" placeholder="Enter password">
</div>
<button class="btn btn-primary" onclick="addAccount()">Add Account</button>
</div>
<div class="card">
<div class="card-title">Account List</div>
<div id="accountList"></div>
</div>
</div>
<div id="settings" class="page">
<div class="header">
<h1>Global Settings</h1>
<p>Configure WeBan behavior</p>
</div>
<div class="card">
<div class="card-title">Learning & Exam Settings</div>
<div class="checkbox-group">
<input type="checkbox" id="enableLearn" class="checkbox">
<label for="enableLearn">Enable Learning Mode</label>
</div>
<div class="checkbox-group">
<input type="checkbox" id="enableExam" class="checkbox">
<label for="enableExam">Enable Exam Mode</label>
</div>
<div class="form-group">
<label class="form-label">Concurrent Tasks</label>
<input type="number" class="form-input" id="concurrent" min="1" max="10" value="3">
</div>
<div class="form-group">
<label class="form-label">Retry Attempts</label>
<input type="number" class="form-input" id="retry" min="0" max="10" value="3">
</div>
<div class="form-group">
<label class="form-label">Timeout (seconds)</label>
<input type="number" class="form-input" id="timeout" min="10" max="300" value="60">
</div>
<button class="btn btn-primary" onclick="saveSettings()">Save Settings</button>
</div>
</div>
<div id="logs" class="page">
<div class="header">
<h1>Log Viewer</h1>
<p>Browse historical log files</p>
</div>
<div class="card">
<div class="card-title">Log Files</div>
<div id="logList"></div>
</div>
</div>
</main>
</div>
<script>
let ws=null;
function switchPage(p){
document.querySelectorAll('.page').forEach(e=>e.classList.remove('active'));
document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
document.getElementById(p).classList.add('active');
event.target.classList.add('active');
if(p==='dashboard')connectWebSocket();
if(p==='accounts')loadAccounts();
if(p==='settings')loadSettings();
if(p==='logs')loadLogFiles();
}
function connectWebSocket(){
if(ws)return;
ws=new WebSocket(`ws://${location.host}/ws/logs`);
ws.onmessage=e=>{
const d=JSON.parse(e.data);
if(d.type==='log'){
const c=document.getElementById('realtimeLogs');
const l=document.createElement('div');
l.className='log-line';
if(d.content.includes('ERROR'))l.classList.add('error');
else if(d.content.includes('SUCCESS'))l.classList.add('success');
else if(d.content.includes('WARNING'))l.classList.add('warning');
l.textContent=d.content;
c.appendChild(l);
c.scrollTop=c.scrollHeight;
}
};
}
async function startTask(){
try{
const r=await fetch('/api/task/start',{method:'POST'});
const d=await r.json();
if(d.success){
updateTaskStatus(true);
alert('Task started successfully');
}else alert('Failed to start: '+d.message);
}catch(e){alert('Error: '+e.message)}
}
async function stopTask(){
try{
const r=await fetch('/api/task/stop',{method:'POST'});
const d=await r.json();
if(d.success){
updateTaskStatus(false);
alert('Task stopped successfully');
}else alert('Failed to stop: '+d.message);
}catch(e){alert('Error: '+e.message)}
}
function updateTaskStatus(running){
document.getElementById('startBtn').disabled=running;
document.getElementById('stopBtn').disabled=!running;
const badge=document.getElementById('statusBadge');
if(running){
badge.textContent='Running';
badge.className='status-badge status-running';
}else{
badge.textContent='Stopped';
badge.className='status-badge status-stopped';
}
}
async function loadAccounts(){
try{
const r=await fetch('/api/accounts');
const d=await r.json();
const list=document.getElementById('accountList');
if(d.success&&d.accounts.length>0){
list.innerHTML=d.accounts.map(a=>`
<div class="account-item">
<div class="account-info">
<div class="account-username">${a.username}</div>
<div class="account-meta">Password: ${'*'.repeat(8)}</div>
</div>
<button class="btn btn-danger" onclick="deleteAccount('${a.username}')">Delete</button>
</div>
`).join('');
}else list.innerHTML='<p style="color:#64748B;text-align:center">No accounts yet</p>';
}catch(e){console.error('Load accounts failed:',e)}
}
async function addAccount(){
const u=document.getElementById('newUsername').value.trim();
const p=document.getElementById('newPassword').value.trim();
if(!u||!p){alert('Please fill in all fields');return}
try{
const r=await fetch('/api/accounts',{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({username:u,password:p})
});
const d=await r.json();
if(d.success){
alert('Account added successfully');
document.getElementById('newUsername').value='';
document.getElementById('newPassword').value='';
loadAccounts();
}else alert('Failed to add: '+d.message);
}catch(e){alert('Error: '+e.message)}
}
async function deleteAccount(u){
if(!confirm(`Delete account ${u}?`))return;
try{
const r=await fetch(`/api/accounts/${u}`,{method:'DELETE'});
const d=await r.json();
if(d.success){
alert('Account deleted successfully');
loadAccounts();
}else alert('Failed to delete: '+d.message);
}catch(e){alert('Error: '+e.message)}
}
async function loadSettings(){
try{
const r=await fetch('/api/settings');
const d=await r.json();
if(d.success){
const s=d.settings;
document.getElementById('enableLearn').checked=s.enable_learn!==false;
document.getElementById('enableExam').checked=s.enable_exam!==false;
document.getElementById('concurrent').value=s.concurrent||3;
document.getElementById('retry').value=s.retry||3;
document.getElementById('timeout').value=s.timeout||60;
}
}catch(e){console.error('Load settings failed:',e)}
}
async function saveSettings(){
const settings={
enable_learn:document.getElementById('enableLearn').checked,
enable_exam:document.getElementById('enableExam').checked,
concurrent:parseInt(document.getElementById('concurrent').value),
retry:parseInt(document.getElementById('retry').value),
timeout:parseInt(document.getElementById('timeout').value)
};
try{
const r=await fetch('/api/settings',{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify(settings)
});
const d=await r.json();
if(d.success)alert('Settings saved successfully');
else alert('Failed to save: '+d.message);
}catch(e){alert('Error: '+e.message)}
}
async function loadLogFiles(){
try{
const r=await fetch('/api/logs');
const d=await r.json();
const list=document.getElementById('logList');
if(d.success&&d.logs.length>0){
list.innerHTML=d.logs.map(g=>{
const s=(g.size/1024).toFixed(2);
const t=new Date(g.mtime).toLocaleString();
return`
<div class="log-item">
<div>
<div>${g.account} / ${g.filename}</div>
<div class="log-meta">${s} KB · ${t}</div>
</div>
<button class="btn btn-secondary" onclick="viewLog('${g.account}','${g.filename}')">View</button>
</div>
`;
}).join('');
}else list.innerHTML='<p style="color:#64748B;text-align:center">No log files yet</p>';
}catch(e){console.error('Load logs failed:',e)}
}
async function viewLog(a,f){
try{
const r=await fetch(`/api/logs/${a}/${f}`);
const d=await r.json();
if(d.success){
const w=window.open('','_blank');
w.document.write(`<html><head><title>${f}</title><style>body{background:#0A0D12;color:#F8FAFC;font-family:Consolas,Monaco,monospace;padding:2rem;line-height:1.5}pre{white-space:pre-wrap;word-break:break-word}</style></head><body><pre>${d.content}</pre></body></html>`);
}else alert('Failed to view: '+d.message);
}catch(e){alert('Error: '+e.message)}
}
connectWebSocket();
setInterval(async()=>{
const r=await fetch('/api/task/status');
const d=await r.json();
updateTaskStatus(d.running);
},2000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("WEBUI_PORT", "8080"))
    host = os.environ.get("WEBUI_HOST", "127.0.0.1")
    print(f"WeBan WebUI starting at http://{host}:{port}")
    print(f"Data directory: {DATA_DIR}")
    uvicorn.run(app, host=host, port=port, log_level="info")
