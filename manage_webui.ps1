param(
    [ValidateSet('Start', 'Stop')]
    [string]$Action = 'Start',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
$webuiScript = Join-Path $projectDir 'webui.py'
$logDir = Join-Path $projectDir 'logs'
$pidFile = Join-Path $logDir 'webui.pid'
$webuiUrl = 'http://127.0.0.1:8080'

function Get-ManagedWebUIProcess {
    if (!(Test-Path -LiteralPath $pidFile)) { return $null }
    $managedProcessId = 0
    if (![int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$managedProcessId)) {
        return $null
    }
    $candidateProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $managedProcessId" -ErrorAction SilentlyContinue
    if ($candidateProcess -and $candidateProcess.ExecutablePath -ieq $pythonPath -and $candidateProcess.CommandLine -like '*webui.py*') {
        return $candidateProcess
    }
    return $null
}

function Test-WebUIReady {
    try {
        $status = Invoke-RestMethod -Uri "$webuiUrl/api/task/status" -TimeoutSec 2 -Proxy $null
        return $status.running -is [bool]
    } catch { return $false }
}

$managedProcess = Get-ManagedWebUIProcess
if ($Action -eq 'Stop') {
    if ($null -eq $managedProcess) {
        Write-Output 'WebUI 当前未运行。'
        exit 0
    }
    try {
        $status = Invoke-RestMethod -Uri "$webuiUrl/api/task/status" -TimeoutSec 2 -Proxy $null
        if ($status.running) {
            $null = Invoke-RestMethod -Uri "$webuiUrl/api/task/stop" -Method Post -TimeoutSec 12 -Proxy $null
        }
    } catch { Write-Warning '任务停止接口未响应，继续停止本项目的 WebUI。' }
    # Windows 的虚拟环境启动器还会创建 Python 子进程，需要一并结束。
    & "$env:SystemRoot\System32\taskkill.exe" /PID $managedProcess.ProcessId /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw '停止 WebUI 进程失败，请检查任务管理器。' }
    if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile }
    Write-Output 'WebUI 已停止。'
    exit 0
}

if ($null -ne $managedProcess -and (Test-WebUIReady)) {
    Write-Output "WebUI 已在运行：$webuiUrl"
    if (!$NoBrowser) { Start-Process $webuiUrl }
    exit 0
}

if ($null -ne $managedProcess) {
    throw 'WebUI 进程仍在启动或没有响应，请先运行 stop_webui.bat 后重试。'
}
if (!(Test-Path -LiteralPath $pythonPath)) {
    throw '未找到项目的 Python 虚拟环境，请检查 .venv 文件夹。'
}
if (Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue) {
    throw '8080 端口已被其他进程占用，请检查后重试。'
}

$null = New-Item -ItemType Directory -Path $logDir -Force
# 固定使用本项目的配置目录和本机访问地址。
$env:WB_DATA_DIR = $projectDir
$env:WEBUI_HOST = '127.0.0.1'
$env:WEBUI_PORT = '8080'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"' + $webuiScript + '"')) -WorkingDirectory $projectDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'webui.stdout.log') -RedirectStandardError (Join-Path $logDir 'webui.stderr.log') -PassThru
[System.IO.File]::WriteAllText($pidFile, [string]$serverProcess.Id, [System.Text.Encoding]::ASCII)

for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Test-WebUIReady) {
        Write-Output "WebUI 已启动：$webuiUrl"
        if (!$NoBrowser) { Start-Process $webuiUrl }
        exit 0
    }
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        throw "WebUI 启动失败，请查看 $logDir\webui.stderr.log。"
    }
    Start-Sleep -Milliseconds 500
}
throw "WebUI 启动超时，请查看 $logDir\webui.stderr.log。"
