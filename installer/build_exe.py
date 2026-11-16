"""将 MSI 和对应的启动器封装为可修复旧版的一键 EXE 安装器。"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from build_msi import ROOT, VERSION, WIX_NS, extract, fetch_tools, make_icon, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--msi', type=Path, default=ROOT / 'dist' / f'WeBan-WebUI-{VERSION}-x64.msi')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    options = parser.parse_args()
    if os.name != 'nt':
        raise RuntimeError('请在 Windows 上构建 EXE 安装器。')

    msi = options.msi.resolve(strict=True)
    expected = msi.with_suffix('.sha256').read_text(encoding='ascii').split()[0].lower()
    if sha256(msi) != expected:
        raise ValueError('MSI 的 SHA256 与校验文件不符。')
    output = options.output.resolve() / f'WeBan-WebUI-{VERSION}-x64-Setup.exe'
    if output.exists():
        raise FileExistsError(f'输出文件已存在：{output}')

    cache = ROOT / 'build' / 'msi-tools'
    fetch_tools(cache)
    wix = cache / 'wix314'
    if not (wix / 'light.exe').is_file():
        extract(cache / 'wix314-binaries.zip', wix)

    with tempfile.TemporaryDirectory(prefix='setup-', dir=ROOT / 'build') as directory:
        work = Path(directory)
        icon = work / 'app.ico'
        make_icon(icon)
        product_wxs = work / 'Product.wxs'
        subprocess.run([str(wix / 'dark.exe'), '-nologo', '-x', str(work), '-o',
                        str(product_wxs), str(msi)], check=True)
        product = ET.parse(product_wxs).find(f'{{{WIX_NS}}}Product')
        if product is None or product.get('Version') != VERSION:
            raise ValueError(f'MSI 的产品版本应为 {VERSION}。')
        launcher = (work / 'Binary' / 'DesktopStopLauncher').resolve(strict=True)

        obj = work / 'Bundle.wixobj'
        extensions = ['-ext', str(wix / 'WixBalExtension.dll'), '-ext', str(wix / 'WixUtilExtension.dll')]
        subprocess.run(
            [str(wix / 'candle.exe'), '-nologo', *extensions, f'-dVersion={VERSION}',
             f'-dAppIcon={icon}', f'-dMsiPath={msi}', f'-dLauncherPath={launcher}',
             '-dMsiUpgradeCode=' + product.attrib['UpgradeCode'],
             '-out', str(obj), str(ROOT / 'installer' / 'Bundle.wxs')],
            check=True,
        )
        staged = work / output.name
        subprocess.run([str(wix / 'light.exe'), '-nologo', *extensions, '-cultures:zh-cn',
                        '-out', str(staged), str(obj)], check=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        staged.rename(output)

    digest = sha256(output)
    output.with_suffix('.sha256').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(f'EXE 已生成：{output}')
    print(f'SHA256：{digest}')


if __name__ == '__main__':
    main()
