# WebUI 使用与开发说明

项目概览、下载方式、来源与功能清单见 [README.md](README.md)，完整操作说明见 [使用说明.txt](使用说明.txt)。

WebUI 使用 FastAPI，持续队列在独立 Python 子进程中运行。账号配置写入采用锁和原子替换，运行中可接入新增账号。完成状态保存在数据目录的 `logs/webui-state.json`；章节快照保存在 `logs/chapter-progress`。这些文件属于用户运行数据，不应提交到仓库。

## 常用接口

| 接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/task/status` | GET | 任务与各账号状态 |
| `/api/task/start` | POST | 启动持续队列，默认跳过已完成账号 |
| `/api/task/stop` | POST | 停止队列及其子进程 |
| `/api/accounts` | GET / POST | 获取公开账号元数据或添加账号 |
| `/api/accounts/import` | POST | 批量导入账号 |
| `/api/accounts/{key}/chapters` | GET | 指定账号的只读章节进度 |
| `/api/settings` | GET / POST | 全局设置 |
| `/api/logs` | GET | 按账号筛选历史日志 |
| `/api/logs/content` | GET | 受目录限制的日志内容读取 |
| `/ws/logs` | WebSocket | 实时账号日志 |

完成归档和章节账号分组由前端根据保存的完成时间及任务状态呈现，不会触发重新学习或重新考试。

## 数据目录与监听地址

源码模式可设置 `WB_DATA_DIR` 指定配置、题库和日志位置。`WEBUI_HOST` 与 `WEBUI_PORT` 控制监听地址和端口。

```powershell
$env:WB_DATA_DIR = "D:\WeBanData"
$env:WEBUI_HOST = "127.0.0.1"
$env:WEBUI_PORT = "8080"
.\.venv\Scripts\python.exe webui.py
```

安装版由启动器设置自己的数据目录、监听端口和内置 Python。后台启动器会核验进程路径、创建时间和实例标识，避免停止其他部署。
