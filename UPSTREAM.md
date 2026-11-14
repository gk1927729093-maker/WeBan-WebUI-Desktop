# 上游来源与修改范围

## 直接基于的项目

- 项目：[wu-xiao-ya/WeBan-webui](https://github.com/wu-xiao-ya/WeBan-webui)。
- 本次修改起点：[fe844a893f3e2f80522a74717184fbecb26f13a6](https://github.com/wu-xiao-ya/WeBan-webui/commit/fe844a893f3e2f80522a74717184fbecb26f13a6)。
- 该提交引入的 WebUI 视觉与基础交互属于直接上游的工作。

## 更早的底层来源

[hangone/WeBan](https://github.com/hangone/WeBan) 提供课程与考试处理、题库同步、验证码处理、多账号运行等核心能力。`wu-xiao-ya/WeBan-webui` 是其派生项目。

本仓库保留上游源文件及 GPL v3 许可证。已有的基础能力不会被当作本次新增功能。

## 本仓库的修改

| 范围 | 主要文件 | 内容 |
| --- | --- | --- |
| 批量导入与账号标识 | `account_support.py`、`webui.py` | Excel/文本导入、重复与错误行处理、学校和学号共同生成账号标识 |
| 持续任务队列 | `webui_runner.py`、`main.py` | 运行中追加、并发排队、保存完成状态、默认跳过已完成账号 |
| 状态和成绩 | `client.py`、`webui_runner.py` | 核验最终服务端进度、按及格判定完成、保留最终考试分数 |
| 章节数据 | `chapter_progress.py` | 按账号缓存、分类/分页课程读取、复用运行中账号登录状态 |
| 界面 | `webui_extensions.js`、`webui_chapters.js`、`webui_extensions.css` | 按账号日志、实时章节、运行状态分组、超过 24 小时的完成归档 |
| AI 恢复 | `client.py` | 模型、鉴权和额度错误分类，独立请求，避免附带学习平台凭据 |
| 本机部署 | `manage_webui.ps1`、启动/停止批处理 | 项目虚拟环境、后台启动、进程树停止、重复启动复用 |
| 安装与分发 | `installer/` | 内置 Python 的 MSI、快捷方式、独立用户数据、自定义安装目录记忆与卸载 |
| 验证 | `tests/` | 模拟队列、导入、日志隔离、章节、归档、分组及安装器测试 |

以上为派生版本的修改范围，不代表底层功能从零实现。平台与上游项目后续变更可能影响兼容性。
