# WeBan WebUI Desktop

基于 [wu-xiao-ya/WeBan-webui](https://github.com/wu-xiao-ya/WeBan-webui) 修改的多账号 WebUI 与 Windows 安装版。面向本机使用，增加持续队列、批量导入、按账号查看日志、实时章节进度、完成归档和独立 MSI 安装包。

## 项目来源与开源许可

本项目直接基于 **wu-xiao-ya/WeBan-webui** 的提交 [`fe844a8`](https://github.com/wu-xiao-ya/WeBan-webui/commit/fe844a893f3e2f80522a74717184fbecb26f13a6) 修改。该项目的底层运行程序来自 **[hangone/WeBan](https://github.com/hangone/WeBan)**。

课程处理、考试、题库同步、验证码处理等基础能力来自上游，本项目不将这些能力声明为原创。本次修改主要围绕 WebUI 的多账号管理、状态核验、进度展示和 Windows 部署。具体对照见 [UPSTREAM.md](UPSTREAM.md)，版本变更见 [CHANGELOG.md](CHANGELOG.md)。

保留上游 [GNU GPL v3 许可证](LICENSE)，继续以相同许可证提供本项目的修改代码。感谢两个上游项目及其贡献者。本项目不是课程平台官方软件。

## 下载 Windows 安装包

前往 [Releases](https://github.com/gk1927729093-maker/WeBan-WebUI-Desktop/releases/latest) 选择 Windows 10/11 x64 安装包。

- `WeBan-WebUI-1.0.2-x64-Setup.exe` 可一键安装或升级。升级时会自动修复旧版缺失或损坏的启动器，避免 Windows Installer 错误 1721。
- `WeBan-WebUI-1.0.2-x64.msi` 支持标准 Windows Installer 部署和自定义安装目录。
- 安装包各附 SHA256 校验文件。`INSTALL.zh-CN.txt` 提供安装与数据目录说明。

已安装 1.0.0 或 1.0.1 时，直接运行 1.0.2 的 EXE 即可升级。程序沿用原安装目录，账号、进度、题库和日志仍在用户数据目录。

安装包内置 Python 3.12 和应用依赖，不需要另外安装 Python。平台相关功能还需要联网，并使用电脑上已有的 Microsoft Edge 或 Google Chrome。当前安装包未做代码签名，Windows 可能显示发布者未知。

安装后通过桌面的 **WeBan WebUI（安装版）** 或开始菜单打开。开始菜单还提供“停止 WeBan WebUI”和“打开账号数据目录”。重复打开不会重复创建后台。

| 项目 | 安装版行为 |
| --- | --- |
| 安装范围 | 当前 Windows 用户 |
| 默认程序位置 | `%LOCALAPPDATA%\Programs\WeBan WebUI`，可在向导中修改 |
| 账号、进度、题库和日志 | `%LOCALAPPDATA%\WeBanWebUI\Data` |
| 本机端口 | 默认 8088，被占用时在 8089–8097 内选择 |
| 卸载 | 停止安装版后台并移除程序，保留用户数据 |
| 发布内容 | 不包含维护者的账号、密码、Token、API Key、运行日志和完成记录 |

关闭网页不会停止后台，暂时不用时请使用开始菜单的停止入口。

### 验证码故障排查

自 1.0.1 起，验证码模型支持包含中文的安装路径。此前遇到 `Can't read ONNX file` 的用户可升级到当前版本。

如果报错提示缺少 `MFPlat.dll`、`MF.dll` 或 `MFReadWrite.dll`，请按 Windows 版本检查媒体组件。在 Windows 10/11 N 上，可从系统的可选功能安装媒体功能包并重启。[Microsoft 支持说明](https://support.microsoft.com/zh-cn/windows/experience/platform-variants/media-feature-pack-for-windows-n)

## 本次新增与修复

| 功能 | 修改后的行为 |
| --- | --- |
| 批量导入 | 支持 CSV、TXT、TSV，以及从 Excel 直接粘贴两列；可按行指定学校，重复账号跳过并报告格式错误行 |
| 持续队列 | 运行中新增账号会自动接入，有空余名额就开始；不会重启其他账号 |
| 并发设置 | 默认 5，可设置 1–50；超过并发数的账号排队 |
| 默认跳过完成账号 | 停止、重启或重开任务后保留已完成状态，只重新处理未完成账号 |
| 完成状态核验 | 按最终服务端课程与考试结果判断完成，普通模式按及格判定；保留已经恢复的错误日志 |
| 账号日志 | 实时日志和历史日志均可按账号筛选；不同学校的相同学号分别记录 |
| 最终成绩 | 完成账号显示最终考试分数；多个考试分别展示 |
| 实时章节进度 | 查看项目、章节和每节课程的状态，约 10 秒同步，可暂停、手动刷新及仅显示未完成课程 |
| 运行状态分组 | 章节页分为“运行中”和“未运行”，显示数量，随任务状态自动更新 |
| 完成归档 | 完成超过 24 小时的进度移到独立归档页；24 小时内完成的暂留控制台；保留成绩、章节和日志入口 |
| 查询与学习协调 | 查询运行中账号时复用登录 Token，使用独立只读会话，不重新登录该账号 |
| AI 异常处理 | 区分模型不可用、鉴权失败、额度耗尽与临时错误；AI 请求不携带学习平台 Cookie/Token |
| Windows MSI | 中文安装向导、内置运行环境、开始菜单和桌面快捷方式、标准卸载、自定义安装路径记忆 |

这些修改不会扩展为无限并发。当前队列实现的上限是 50，100–500 个账号的稳定并发未经过实际压力测试。

## 批量导入示例

在“账号管理”先填写默认学校，再粘贴：

```csv
学号,密码
示例账号A,示例密码A
示例账号B,示例密码B
```

也可每行使用 `学校,学号,密码` 混合导入不同学校。学校名称需要与平台一致。密码留空会按程序约定使用学号；导入时请确认自己的输入。

## 从源码运行

需要 Python `>=3.12,<3.13`。在项目目录中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r installer\requirements-installed.txt
Copy-Item config.example.toml config.toml
.\start_webui.bat
```

已有 `config.toml` 时保留自己的配置，首次使用才复制示例。源码部署默认打开 `http://127.0.0.1:8080`，停止使用 `stop_webui.bat`。

更多操作见 [使用说明.txt](使用说明.txt)。安装版与源码版使用独立的数据位置；安装包不会自动导入其他部署中的账号。

## 测试与构建

Python 测试使用模拟账号，不登录真实学习平台：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_archive_progress.js tests/test_chapter_groups.js
```

本地构建 MSI：

```powershell
.\.venv\Scripts\python.exe installer\build_msi.py
```

构建流程与依赖来源见 [installer/README.md](installer/README.md)。GitHub Actions 中的验证流程会运行测试；Windows MSI 构建可手动触发，产物保存为 Actions artifact。

首个 Windows MSI 已在本机验证自定义目录安装、独立运行环境加载、启动、重复启动、停止和卸载。卸载后会保留用户数据。其他电脑与平台的兼容性仍需使用者反馈。

## 数据与安全

账号配置和 API Key 保存在本机文件中，配置文件不是加密保险箱。界面默认只监听 `127.0.0.1`，没有内置登录鉴权，不适合直接暴露到公网。

提交 Issue 或分享文件前，请移除账号、密码、Token、API Key、姓名和学号。不要上传实际配置或整个数据目录。相关说明见 [SECURITY.md](SECURITY.md)。
