param(
    [Parameter(Mandatory)]
    [ValidateSet('clean', 'broken-100', 'upgrade-101', 'broken-101', 'msi-101')]
    [string]$Scenario
)

$ErrorActionPreference = 'Stop'
$installKey = 'HKCU:\Software\WeBanWebUI'
$data = Join-Path $env:LOCALAPPDATA 'WeBanWebUI\Data'
if (!$env:RUNNER_TEMP -or (Test-Path -LiteralPath $installKey) -or (Test-Path -LiteralPath $data)) {
    throw '请在没有 WeBan 安装或用户数据的 Windows 测试环境执行。'
}
$testDir = Join-Path $env:RUNNER_TEMP ('WeBan 安装测试 ' + $Scenario)
New-Item -ItemType Directory -Path $testDir | Out-Null
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
$manifest = Get-Content -Raw -LiteralPath (Get-ChildItem -LiteralPath $dist -Filter '*.manifest.json').FullName |
    ConvertFrom-Json
$version = $manifest.version
$setup = Get-Item -LiteralPath (Join-Path $dist "WeBan-WebUI-$version-x64-Setup.exe")
$msi = Get-Item -LiteralPath (Join-Path $dist "WeBan-WebUI-$version-x64.msi")
if ($setup.VersionInfo.ProductVersion -ne "$version.0") { throw 'EXE 产品版本不匹配。' }

function Invoke-Installer {
    param([string]$File, [string[]]$Arguments, [string]$Log)
    $p = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        Get-Content -LiteralPath $Log -Tail 25 -ErrorAction SilentlyContinue
        Get-ChildItem -LiteralPath $testDir -File -Filter '*.log' | ForEach-Object {
            Select-String -LiteralPath $_.FullName -Pattern 'Note: 1: 1721|Return value 3|返回值 3|Error 0x' |
                Select-Object -Last 6 | ForEach-Object Line
        }
        throw "安装程序失败，退出码 $($p.ExitCode)。日志 $Log"
    }
}

function Start-Desktop {
    param([string]$Launcher, [string]$ExpectedVersion)
    $p = Start-Process -FilePath $Launcher -ArgumentList @('--quiet', '--no-browser', '--port', '19866') -WindowStyle Hidden -PassThru
    if (!$p.WaitForExit(45000) -or $p.ExitCode -ne 0) {
        Get-ChildItem -LiteralPath (Join-Path $data 'logs') -File -Filter '*.log' -ErrorAction SilentlyContinue |
            ForEach-Object { Get-Content -LiteralPath $_.FullName -Tail 18 }
        throw '启动器未成功启动 WebUI。'
    }
    $state = Get-Content -Raw -LiteralPath (Join-Path $data 'logs\desktop-server.json') | ConvertFrom-Json
    $identity = Invoke-RestMethod -Uri "http://127.0.0.1:$($state.Port)/api/desktop/identity" -NoProxy -TimeoutSec 10
    if ($identity.application -ne 'WeBanWebUI' -or $identity.version -ne $ExpectedVersion -or
        $identity.instance_id -ne $state.InstanceId) {
        throw "后台身份或版本不匹配，应为 $ExpectedVersion。"
    }
    return (Get-Process -Id $state.Pid)
}

Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class InstallerState {
    [DllImport("msi.dll", CharSet = CharSet.Unicode)]
    public static extern int MsiQueryProductState(string product);
}
'@

$msiexec = "$env:SystemRoot\System32\msiexec.exe"
$config = Join-Path $data 'config.toml'
$usingMsi = $Scenario -eq 'msi-101'
$oldVersion = $null
$previousCode = $null
$oldProcess = $null
$oldLocation = $null
if ($Scenario -ne 'clean') {
    $oldVersion = '1.0.1'
    $previousCode = '{ED6616F2-672B-4A02-8A4F-34B1B6B2C51A}'
    $previous = 'WeBan-WebUI-1.0.1-x64-Setup.exe'
    $expected = '87710731e6202057be01e2a42d6d4f5e87102dda71b0abefa72493f10b4d567c'
    if ($Scenario -eq 'broken-100') {
        $oldVersion = '1.0.0'
        $previousCode = '{5273C0F8-79FE-4D21-AD19-A58B010EDE95}'
        $previous = 'WeBan-WebUI-1.0.0-x64.msi'
        $expected = 'ed1e9f446e1b028472cd905106a9e947f53f52b1ede3edcade885df69af89076'
    }
    elseif ($usingMsi) {
        $previous = 'WeBan-WebUI-1.0.1-x64.msi'
        $expected = 'f48814dea63484123a0a0244737a6f49fb28229c77766d1c8cd96e493eff8164'
    }

    $source = Join-Path $env:RUNNER_TEMP "legacy\$previous"
    if ((Get-FileHash -LiteralPath $source).Hash -ne $expected) { throw '旧版发布文件校验失败。' }
    $log = Join-Path $testDir 'legacy-install.log'
    if ($previous.EndsWith('.msi')) {
        $legacyDirectory = Join-Path $testDir '自定义 旧版安装'
        Invoke-Installer $msiexec @('/i', ('"' + $source + '"'), '/qn', '/norestart', '/l*v',
            ('"' + $log + '"'), ('INSTALLFOLDER="' + $legacyDirectory + '"')) $log
    }
    else {
        Invoke-Installer $source @('/quiet', '/norestart', '/log', ('"' + $log + '"')) $log
    }
    if ([InstallerState]::MsiQueryProductState($previousCode) -ne 5) { throw '未安装预期的旧版产品。' }
    $oldLocation = (Get-ItemProperty -LiteralPath $installKey -Name InstallDirectory).InstallDirectory
    $oldLauncher = Join-Path $oldLocation 'WeBanWebUI.exe'
    $oldProcess = Start-Desktop $oldLauncher $oldVersion
    $dataBefore = (Get-FileHash -LiteralPath $config).Hash
    $sentinel = Join-Path $data 'logs\installer-upgrade-fixture.txt'
    Set-Content -LiteralPath $sentinel -Value '安装升级测试数据' -Encoding utf8
    $sentinelHash = (Get-FileHash -LiteralPath $sentinel).Hash

    if ($Scenario -eq 'broken-100') {
        Move-Item -LiteralPath $oldLauncher -Destination (Join-Path $testDir 'legacy-launcher.saved')
        if (Test-Path -LiteralPath $oldLauncher) { throw '未成功模拟旧启动器缺失。' }
    }
    elseif ($Scenario -eq 'broken-101') {
        Set-Content -LiteralPath $oldLauncher -Value '损坏的测试启动器' -Encoding utf8NoBOM
    }
}

$log = Join-Path $testDir 'install-current.log'
if ($usingMsi) {
    Invoke-Installer $msiexec @('/i', ('"' + $msi.FullName + '"'), '/qn', '/norestart',
        '/l*v', ('"' + $log + '"')) $log
}
else {
    Invoke-Installer $setup.FullName @('/quiet', '/norestart', '/log', ('"' + $log + '"')) $log
    $repairRan = [bool](Select-String -LiteralPath $log -Pattern 'Applying execute package: RepairLegacyLauncher, action: Install' -Quiet)
    if ($repairRan -ne ($Scenario -ne 'clean')) { throw '旧版启动器修复步骤的触发条件不匹配。' }
}
$location = (Get-ItemProperty -LiteralPath $installKey -Name InstallDirectory).InstallDirectory
$launcher = Join-Path $location 'WeBanWebUI.exe'
if ($oldLocation) {
    if ($location -ne $oldLocation) { throw '升级后安装目录发生变化。' }
    if (!$oldProcess.WaitForExit(10000)) { throw '升级后旧版后台仍在运行。' }
    if ([InstallerState]::MsiQueryProductState($previousCode) -eq 5) { throw '升级后旧版产品仍然登记为已安装。' }
    $bundles = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
    if (Get-ItemProperty -Path $bundles -ErrorAction SilentlyContinue | Where-Object {
        $_.DisplayName -eq 'WeBan WebUI Desktop' -and $_.DisplayVersion -eq "$oldVersion.0"
    }) { throw '升级后旧版 EXE 安装记录仍存在。' }
    if ((Get-FileHash -LiteralPath $config).Hash -ne $dataBefore -or
        (Get-FileHash -LiteralPath $sentinel).Hash -ne $sentinelHash) {
        throw '升级改动了已有配置或日志。'
    }
}
$running = Start-Desktop $launcher $version

if ($Scenario -eq 'broken-100') {
    $runtime = Join-Path $location 'runtime\python.exe'
    $probe = @'
import numpy as np
from captcha import LoginCaptchaSolver
from loguru import logger
net = LoginCaptchaSolver.get_ocr(logger)
assert net is not None
net.setInput(np.zeros((1, 1, 28, 28), dtype=np.float32))
result = net.forward()
assert result.shape == (1, 36) and np.isfinite(result).all()
'@
    & $runtime -B -X utf8 -c $probe
    if ($LASTEXITCODE -ne 0) { throw '中文路径下验证码推理测试失败。' }
}
$configHash = (Get-FileHash -LiteralPath $config).Hash
$log = Join-Path $testDir 'uninstall-current.log'
if ($usingMsi) {
    Invoke-Installer $msiexec @('/x', ('"' + $msi.FullName + '"'), '/qn', '/norestart',
        '/l*v', ('"' + $log + '"')) $log
}
else {
    Invoke-Installer $setup.FullName @('/uninstall', '/quiet', '/norestart', '/log', ('"' + $log + '"')) $log
}
if (!$running.WaitForExit(10000) -or (Test-Path -LiteralPath $launcher) -or (Test-Path -LiteralPath $installKey)) {
    throw '卸载后仍存在安装记录、启动器或后台。'
}
if ((Get-FileHash -LiteralPath $config).Hash -ne $configHash) { throw '卸载改动了用户配置。' }
Write-Host "$Scenario 通过安装、启动、卸载和数据检查。"
