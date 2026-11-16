本目录构建 WeBan WebUI 的独立 Windows x64 MSI 和 EXE 安装器。

使用项目 Python 3.12 环境执行：

```powershell
.\.venv\Scripts\python.exe installer\build_msi.py
.\.venv\Scripts\python.exe installer\build_exe.py
```

构建使用 Python 官方嵌入式发行版和 WiX v3.14.1，构建依赖下载至 `build/msi-tools`，并按固定 SHA256 校验。应用依赖取自当前项目 `.venv/Lib/site-packages`，实际版本记录在安装包的 `installer-source/requirements-installed.txt`。

源文件通过明确清单复制，不复制本机 `config.toml`、日志、会话、账号或 `.git`。初始题库固定取上游 `fe844a893f3e2f80522a74717184fbecb26f13a6` 的公开基线，并核对 SHA256。没有 `.git` 的 GitHub 源码压缩包也可构建，但目录内的题库必须符合相同的公开基线，修改过的本机题库不会被收录。应用源码、安装器源码以及各依赖许可证随包提供。

安装器按当前用户安装，默认程序目录为 `%LOCALAPPDATA%\Programs\WeBan WebUI`，数据独立保存在 `%LOCALAPPDATA%\WeBanWebUI\Data`。卸载保留数据，升级使用固定 UpgradeCode。构建默认运行 Windows Installer 的 ICE 校验。

安装版启动器会核验后台的解释器完整路径、进程创建时间和实例标识，停止入口只管理本安装目录启动的后台。源码部署使用的端口和目录不会被接管。

EXE 封装同版本 MSI 和 MSI 内的启动器。检测到旧版时，它会先修复相关安装缺失或损坏的启动器，再由 Windows Installer 升级。MSI 卸载会使用包内的停止程序。

构建输出在 `dist`，包括 MSI、EXE、SHA256 和文件清单。未提供代码签名证书，因此产物为未签名包。

参考：

- https://docs.python.org/3.12/using/windows.html#the-embeddable-package
- https://github.com/wixtoolset/wix3/releases/tag/wix3141rtm
- https://docs.firegiant.com/wix3/wixui/dialog_reference/wixui_installdir/
