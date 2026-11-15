修复了安装路径含中文时出现的 `OpenCV DNN 初始化失败` 或 `Can't read ONNX file`。程序现在由 Python 读取验证码模型，再将文件内容交给 OpenCV。模型缺失、读取失败以及 OpenCV 加载错误会在日志里分别说明。

下载 `WeBan-WebUI-1.0.1-x64.msi` 直接升级。账号配置、进度和日志仍保存在 `%LOCALAPPDATA%\WeBanWebUI\Data`。安装包内置 Python，适用于 Windows 10/11 x64。

如果提示缺少 `MFPlat.dll`、`MF.dll` 或 `MFReadWrite.dll`，还需要补齐 Windows 媒体组件。Windows 10/11 N 可从系统的可选功能安装媒体功能包并重启。[Microsoft 支持说明](https://support.microsoft.com/zh-cn/windows/experience/platform-variants/media-feature-pack-for-windows-n)
