"""安装版入口：将可写数据放到用户目录，使用内置 Python 启动 WebUI。"""
import os
from pathlib import Path
import sys


def main():
    data = Path(os.environ['WB_DATA_DIR']).resolve()
    logs = data / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    sys.stdout = (logs / 'webui.stdout.log').open('a', encoding='utf-8', buffering=1)
    sys.stderr = (logs / 'webui.stderr.log').open('a', encoding='utf-8', buffering=1)
    sys.dont_write_bytecode = True

    import uvicorn
    import webui

    # 子任务也使用随安装包提供的解释器，不依赖系统 Python，不写安装目录缓存。
    python = Path(__file__).resolve().parents[1] / 'runtime' / 'python.exe'
    webui._get_weban_python_command = lambda: [str(python), '-B']

    @webui.app.get('/api/desktop/identity')
    def desktop_identity():
        return {'application': 'WeBanWebUI', 'version': '1.0.0',
                'instance_id': os.environ['WB_DESKTOP_INSTANCE']}

    uvicorn.run(webui.app, host='127.0.0.1', port=int(os.environ['WEBUI_PORT']),
                access_log=False, log_level='info')


if __name__ == '__main__':
    main()
