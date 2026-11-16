"""构建独立、按用户安装的 Windows x64 MSI；打包清单不会读取实际账号配置。"""
import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import tomllib
import uuid
import xml.etree.ElementTree as ET
import zipfile
import zlib

import requests
import tomli_w

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.2'
UPSTREAM_BASE = 'fe844a893f3e2f80522a74717184fbecb26f13a6'
PUBLIC_ANSWER_SHA256 = '5438af36f2fddef978306882dac56bbf54fbf1f9f399c82f3d3b3c536f9b5e57'
NAMESPACE = uuid.UUID('398b97e9-6154-4cdc-a15e-01ef934f71bc')
WIX_NS = 'http://schemas.microsoft.com/wix/2006/wi'
ET.register_namespace('', WIX_NS)
DOWNLOADS = {
    'python-3.12.10-embed-amd64.zip': (
        'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip',
        '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'),
    'wix314-binaries.zip': (
        'https://github.com/wixtoolset/wix3/releases/download/wix3141rtm/wix314-binaries.zip',
        '6ac824e1642d6f7277d0ed7ea09411a508f6116ba6fae0aa5f2c7daa2ff43d31'),
}
APPLICATION_FILES = (
    'account_support.py', 'api.py', 'captcha.py', 'captcha_model.onnx', 'chapter_progress.py',
    'client.py', 'main.py', 'webui.py', 'webui_runner.py', 'webui_extensions.js',
    'webui_extensions.css', 'webui_chapters.js', 'pyproject.toml', 'requirements.txt',
    'LICENSE', 'README.md', 'README_WEBUI.md', '使用说明.txt',
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_tools(cache):
    cache.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in DOWNLOADS.items():
        target = cache / name
        if not target.is_file():
            print(f'下载构建依赖：{name}', flush=True)
            with requests.get(url, stream=True, timeout=(20, 120)) as response:
                response.raise_for_status()
                with target.open('wb') as output:
                    for part in response.iter_content(1024 * 1024):
                        output.write(part)
        if sha256(target) != expected:
            raise RuntimeError(f'构建依赖校验失败：{name}，请核对下载文件。')


def extract(archive_path, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError('压缩包包含越界路径。')
        archive.extractall(destination)


def default_config():
    return {'account': [], 'settings': {
        'study_mode': 'true', 'exam_mode': 'true', 'random_answer': True,
        'study_time': 30, 'video_speed': 1, 'exam_question_time': '3,3',
        'exam_submit_match_rate': 90, 'max_workers': 5,
        'browser_path': '', 'cdp_host': '', 'cdp_port': 0, 'debug': False,
    }, 'ai': {'enable': False, 'base_url': '', 'api_key': '', 'model': '',
              'timeout': 60, 'max_retries': 2}}


def read_public_answers(root=ROOT):
    """只接受固定的公开题库，兼容带 Git 的检出和 GitHub 源码压缩包。"""
    data = None
    if (root / '.git').exists() and shutil.which('git'):
        result = subprocess.run(['git', 'show', f'{UPSTREAM_BASE}:answer/answer.json'],
                                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            data = result.stdout
    if data is None:
        data = (root / 'answer' / 'answer.json').read_bytes().replace(b'\r\n', b'\n')
    if hashlib.sha256(data).hexdigest() != PUBLIC_ANSWER_SHA256:
        raise RuntimeError('题库不符合公开基线，停止打包以免夹带本机运行数据。请使用干净的源码检出。')
    json.loads(data)
    return data


def copy_site_packages(source, destination):
    def ignore(directory, names):
        return [name for name in names if name in ('__pycache__', 'pip', 'direct_url.json')
                or name.startswith('pip-') and name.endswith('.dist-info')
                or name.endswith(('.pyc', '.pyo'))]
    shutil.copytree(source, destination, ignore=ignore)


def make_icon(path):
    # 使用本项目自己的书本图标，ICO 中的图片由标准 PNG 数据组成。
    def image(size):
        segments = [(14, 17, 27, 17), (27, 17, 32, 21), (32, 21, 37, 17),
                    (37, 17, 50, 17), (50, 17, 50, 45), (50, 45, 37, 45),
                    (37, 45, 32, 49), (32, 49, 27, 45), (27, 45, 14, 45),
                    (14, 45, 14, 17), (32, 21, 32, 49)]
        rows = bytearray()
        for y in range(size):
            rows.append(0)
            for x in range(size):
                px, py = (x + .5) * 64 / size, (y + .5) * 64 / size
                inside = 4 <= px <= 60 and 4 <= py <= 60 and (max(16-px, 0, px-48)**2 + max(16-py, 0, py-48)**2 <= 144)
                color = (0, 122, 255, 255) if inside else (0, 0, 0, 0)
                for x1, y1, x2, y2 in segments:
                    t = max(0, min(1, ((px-x1)*(x2-x1)+(py-y1)*(y2-y1))/((x2-x1)**2+(y2-y1)**2)))
                    if (px-x1-t*(x2-x1))**2+(py-y1-t*(y2-y1))**2 < 1.6**2:
                        color = (255, 255, 255, 255)
                        break
                rows.extend(color)
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
        return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
    sizes = [16, 32, 48, 64, 256]
    images = [image(size) for size in sizes]
    result = bytearray(struct.pack('<HHH', 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for size, png in zip(sizes, images):
        result.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
        offset += len(png)
    path.write_bytes(result + b''.join(images))


def stage_application(stage, cache):
    app = stage / 'app'
    app.mkdir(parents=True)
    for name in APPLICATION_FILES:
        shutil.copy2(ROOT / name, app / name)
    shutil.copy2(ROOT / 'installer' / 'desktop_server.py', app / 'desktop_server.py')
    defaults = stage / 'defaults'
    defaults.mkdir()
    clean = tomli_w.dumps(default_config())
    (defaults / 'config.toml').write_text(clean, encoding='utf-8')
    (app / 'config.example.toml').write_text(clean, encoding='utf-8')
    # 题库仅取公开仓库基线，不收录本机账号同步后改写的文件。
    public_answers = read_public_answers()
    (defaults / 'answer.json').write_bytes(public_answers)
    extract(cache / 'python-3.12.10-embed-amd64.zip', stage / 'runtime')
    (stage / 'runtime' / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n../app\nimport site\n', encoding='ascii')
    site = ROOT / '.venv' / 'Lib' / 'site-packages'
    copy_site_packages(site, stage / 'runtime' / 'Lib' / 'site-packages')
    sources = stage / 'installer-source'
    shutil.copytree(ROOT / 'installer', sources, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    versions = sorted(f'{item.metadata["Name"]}=={item.version}' for item in importlib.metadata.distributions(path=[str(site)])
                      if item.metadata['Name'].lower() != 'pip')
    (sources / 'requirements-installed.txt').write_text('\n'.join(versions) + '\n', encoding='utf-8')
    shutil.copy2(ROOT / 'LICENSE', stage / 'LICENSE.txt')
    shutil.copy2(ROOT / 'installer' / '安装版使用说明.txt', stage / '安装版使用说明.txt')
    make_icon(stage / 'app.ico')
    csc = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe'
    subprocess.run([str(csc), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                    '/reference:System.Web.Extensions.dll', '/reference:System.Windows.Forms.dll',
                    f'/win32icon:{stage / "app.ico"}', f'/out:{stage / "WeBanWebUI.exe"}',
                    str(ROOT / 'installer' / 'Launcher.cs')], check=True)
    assert tomllib.loads((defaults / 'config.toml').read_text(encoding='utf-8'))['account'] == []
    return versions


def element(parent, tag, **attributes):
    return ET.SubElement(parent, f'{{{WIX_NS}}}{tag}', attributes)


def identifier(prefix, name):
    return prefix + hashlib.sha256(name.lower().encode('utf-8')).hexdigest()[:24]


def write_wix(stage, path):
    root = ET.Element(f'{{{WIX_NS}}}Wix')
    product = element(root, 'Product', Id='*', Name='WeBan WebUI', Version=VERSION,
                      Language='2052', Codepage='936', Manufacturer='WeBan WebUI',
                      UpgradeCode=str(uuid.uuid5(NAMESPACE, 'upgrade')).upper())
    element(product, 'Package', InstallerVersion='500', Compressed='yes', InstallScope='perUser',
            InstallPrivileges='limited', Platform='x64', SummaryCodepage='936',
            Description='WeBan WebUI 独立安装包', Comments='内置 Python；账号数据保存在独立用户目录。')
    element(product, 'MajorUpgrade', DowngradeErrorMessage='已安装更新版本，请先卸载更新版本后重试。', Schedule='afterInstallInitialize')
    element(product, 'MediaTemplate', EmbedCab='yes', CompressionLevel='high')
    element(product, 'Property', Id='ARPURLINFOABOUT', Value='https://github.com/wu-xiao-ya/WeBan-webui')
    element(product, 'Property', Id='ARPPRODUCTICON', Value='AppIcon')
    # 文件组件以 HKCU 注册值为关键路径，卸载时必须显式恢复用户选择的目录。
    remembered_directory = element(product, 'Property', Id='INSTALLFOLDER', Secure='yes')
    element(remembered_directory, 'RegistrySearch', Id='ReadInstalledDirectory', Root='HKCU',
            Key=r'Software\WeBanWebUI', Name='InstallDirectory', Type='raw', Win64='yes')
    element(product, 'Icon', Id='AppIcon', SourceFile='$(var.StageDir)\\app.ico')
    condition = element(product, 'Condition', Message='需要 64 位 Windows。')
    condition.text = 'VersionNT64'
    target = element(product, 'Directory', Id='TARGETDIR', Name='SourceDir')
    local = element(target, 'Directory', Id='LocalAppDataFolder')
    programs = element(local, 'Directory', Id='USERPROGRAMSFOLDER', Name='Programs')
    installation = element(programs, 'Directory', Id='INSTALLFOLDER', Name='WeBan WebUI')
    directories = {'.': installation}
    paths = sorted((item for item in stage.rglob('*') if item.is_dir()), key=lambda item: (len(item.relative_to(stage).parts), str(item).lower()))
    for directory in paths:
        relative = directory.relative_to(stage)
        parent = relative.parent.as_posix()
        directories[relative.as_posix()] = element(directories[parent], 'Directory',
            Id=identifier('D', relative.as_posix()), Name=relative.name)
    grouped = defaultdict(list)
    for file in sorted(stage.rglob('*')):
        if file.is_file():
            grouped[file.relative_to(stage).parent.as_posix()].append(file)
    components = []
    for relative, directory in directories.items():
        key = identifier('C', relative)
        component = element(directory, 'Component', Id=key, Guid=str(uuid.uuid5(NAMESPACE, 'directory:' + relative.lower())).upper(), Win64='yes')
        components.append(key)
        element(component, 'RegistryValue', Root='HKCU', Key=r'Software\WeBanWebUI\InstallerComponents',
                Name=key, Type='integer', Value='1', KeyPath='yes')
        for file in grouped[relative]:
            rel = file.relative_to(stage).as_posix()
            element(component, 'File', Id=identifier('F', rel), Source='$(var.StageDir)\\' + rel.replace('/', '\\'), Name=file.name)
        if not grouped[relative]:
            element(component, 'CreateFolder')
        element(component, 'RemoveFolder', Id=identifier('R', relative), On='uninstall')
        if relative == '.':
            element(component, 'RegistryValue', Root='HKCU', Key=r'Software\WeBanWebUI',
                    Name='InstallDirectory', Type='string', Value='[INSTALLFOLDER]')
            element(component, 'RemoveFolder', Id='RemoveProgramsIfEmpty', Directory='USERPROGRAMSFOLDER', On='uninstall')
    menu_root = element(target, 'Directory', Id='ProgramMenuFolder')
    menu = element(menu_root, 'Directory', Id='ProgramMenuAppDirectory', Name='WeBan WebUI')
    menu_component = element(menu, 'Component', Id='MenuShortcuts', Guid=str(uuid.uuid5(NAMESPACE, 'menu')).upper(), Win64='yes')
    for key, name, args in [('Open', '打开 WeBan WebUI', ''), ('Stop', '停止 WeBan WebUI', '--stop'), ('Data', '打开账号数据目录', '--open-data')]:
        shortcut = element(menu_component, 'Shortcut', Id='Shortcut' + key, Name=name,
                           Target='[INSTALLFOLDER]WeBanWebUI.exe', WorkingDirectory='INSTALLFOLDER', Icon='AppIcon')
        if args:
            shortcut.set('Arguments', args)
    element(menu_component, 'RegistryValue', Root='HKCU', Key=r'Software\WeBanWebUI', Name='MenuInstalled', Type='integer', Value='1', KeyPath='yes')
    element(menu_component, 'RemoveFolder', Id='RemoveMenu', On='uninstall')
    components.append('MenuShortcuts')
    desktop = element(target, 'Directory', Id='DesktopFolder')
    desktop_component = element(desktop, 'Component', Id='DesktopShortcut', Guid=str(uuid.uuid5(NAMESPACE, 'desktop')).upper(), Win64='yes')
    element(desktop_component, 'Shortcut', Id='OpenDesktop', Name='WeBan WebUI（安装版）',
            Target='[INSTALLFOLDER]WeBanWebUI.exe', WorkingDirectory='INSTALLFOLDER', Icon='AppIcon')
    element(desktop_component, 'RegistryValue', Root='HKCU', Key=r'Software\WeBanWebUI', Name='DesktopInstalled', Type='integer', Value='1', KeyPath='yes')
    components.append('DesktopShortcut')
    feature = element(product, 'Feature', Id='Complete', Title='WeBan WebUI', Level='1', Absent='disallow')
    for key in components:
        element(feature, 'ComponentRef', Id=key)
    # 从安装数据库启动停止程序，已安装的启动器丢失时也能完成卸载。
    element(product, 'Binary', Id='DesktopStopLauncher', SourceFile='$(var.StageDir)\\WeBanWebUI.exe')
    element(product, 'CustomAction', Id='StopDesktopServer', BinaryKey='DesktopStopLauncher',
            ExeCommand='--stop --quiet --data-dir "[LocalAppDataFolder]WeBanWebUI\\Data" '
                       '--installed-directory "[INSTALLFOLDER]."',
            Execute='immediate', Impersonate='yes', Return='check')
    sequence = element(product, 'InstallExecuteSequence')
    action = element(sequence, 'Custom', Action='StopDesktopServer', Before='RemoveFiles')
    action.text = 'Installed AND REMOVE="ALL"'
    element(product, 'Property', Id='WIXUI_INSTALLDIR', Value='INSTALLFOLDER')
    element(product, 'WixVariable', Id='WixUILicenseRtf', Value='$(var.LicenseRtf)')
    element(product, 'UIRef', Id='WixUI_InstallDir')
    element(product, 'UIRef', Id='WixUI_ErrorProgressText')
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    return len(grouped), len(components)


def write_rtf(path):
    text = 'WeBan WebUI\n\n本软件及修改后的项目代码遵循 GNU GPL v3。项目源码随程序一并提供。\n\n' + (ROOT / 'LICENSE').read_text(encoding='utf-8')
    escaped = []
    for character in text:
        if character in '{}\\': escaped.append('\\' + character)
        elif character == '\n': escaped.append('\\par\n')
        elif ord(character) > 127: escaped.append('\\u' + str(ord(character) if ord(character) < 32768 else ord(character)-65536) + '?')
        else: escaped.append(character)
    path.write_text('{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Segoe UI;}}\\f0\\fs18 ' + ''.join(escaped) + '}', encoding='ascii')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    options = parser.parse_args()
    if sys.version_info[:2] != (3, 12) or os.name != 'nt':
        raise RuntimeError('请使用 Windows x64 的项目 Python 3.12 环境构建。')
    cache = ROOT / 'build' / 'msi-tools'
    fetch_tools(cache)
    wix = cache / 'wix314'
    if not (wix / 'light.exe').is_file(): extract(cache / 'wix314-binaries.zip', wix)
    work = ROOT / 'build' / ('msi-' + time.strftime('%Y%m%d-%H%M%S'))
    stage = work / 'payload'
    versions = stage_application(stage, cache)
    print('独立运行环境和干净配置已准备。', flush=True)
    license_rtf = work / 'license.rtf'
    write_rtf(license_rtf)
    wxs = work / 'Product.wxs'
    write_wix(stage, wxs)
    options.output.mkdir(parents=True, exist_ok=True)
    output = options.output.resolve() / f'WeBan-WebUI-{VERSION}-x64.msi'
    if output.exists():
        output = output.with_stem(output.stem + '-' + time.strftime('%Y%m%d-%H%M%S'))
    common = ['-nologo', '-ext', str(wix / 'WixUIExtension.dll'),
              '-dStageDir=' + str(stage.resolve()), '-dLicenseRtf=' + str(license_rtf.resolve())]
    obj = work / 'Product.wixobj'
    subprocess.run([str(wix / 'candle.exe'), '-arch', 'x64', *common, '-out', str(obj), str(wxs)], check=True)
    print('正在生成并校验 MSI 安装数据库和内嵌 CAB。', flush=True)
    with (work / 'light.log').open('w', encoding='utf-8') as log:
        linked = subprocess.run([str(wix / 'light.exe'), *common, '-cultures:zh-cn', '-out', str(output), str(obj)],
                                stdout=log, stderr=subprocess.STDOUT)
    build_log = (work / 'light.log').read_text(encoding='utf-8', errors='replace')
    warnings = [line for line in build_log.splitlines() if 'warning ' in line]
    unexpected = [line for line in warnings if 'ICE91:' not in line]
    if linked.returncode:
        print('\n'.join(build_log.splitlines()[-25:]), flush=True)
        raise RuntimeError(f'MSI 链接或校验失败，详情见 {work / "light.log"}')
    print(f'ICE 校验无错误；按用户安装的 ICE91 提示 {len(warnings)-len(unexpected)} 条，其他警告 {len(unexpected)} 条。', flush=True)
    if unexpected:
        print('\n'.join(unexpected[:10]), flush=True)
    files = [{'path': file.relative_to(stage).as_posix(), 'size': file.stat().st_size, 'sha256': sha256(file)}
             for file in sorted(stage.rglob('*')) if file.is_file()]
    manifest = {'product': 'WeBan WebUI', 'version': VERSION, 'architecture': 'x64',
                'python': '3.12.10', 'msi': output.name, 'msi_sha256': sha256(output),
                'msi_size': output.stat().st_size, 'user_accounts_included': False,
                'dependencies': versions, 'files': files,
                'download_sources': {name: {'url': url, 'sha256': digest} for name, (url, digest) in DOWNLOADS.items()}}
    manifest_path = output.with_suffix('.manifest.json')
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    output.with_suffix('.sha256').write_text(manifest['msi_sha256'] + '  ' + output.name + '\n', encoding='ascii')
    print(json.dumps({'msi': str(output), 'size_mib': round(output.stat().st_size/1024**2, 1),
                      'payload_files': len(files), 'manifest': str(manifest_path)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
