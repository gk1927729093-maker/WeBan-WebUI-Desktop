# WeBan WebUI 快速入门

## 一键启动

双击运行：
```
start_webui.bat
```

或命令行：
```bash
python webui.py
```

## 首次使用

### 1. 访问界面

浏览器打开：http://127.0.0.1:8080

### 2. 添加账号

1. 点击左侧 **Account Management**
2. 填写用户名和密码
3. 点击 **Add Account**

### 3. 配置设置

1. 点击左侧 **Global Settings**
2. 勾选启用学习/考试模式
3. 调整并发数、重试次数等
4. 点击 **Save Settings**

### 4. 启动任务

1. 返回 **Dashboard**
2. 点击 **Start Task** 按钮
3. 实时日志会自动显示
4. 需要停止时点击 **Stop Task**

### 5. 查看历史日志

1. 点击左侧 **Log Viewer**
2. 选择要查看的日志文件
3. 点击 **View** 在新窗口打开

## 功能说明

### Dashboard（仪表盘）
- 绿色状态：任务运行中
- 红色状态：任务已停止
- 实时日志自动刷新
- 每2秒更新状态

### Account Management（账号管理）
- 支持多账号批量管理
- 自动检测重复账号
- 删除操作需确认
- 密码显示为 *** 保护隐私

### Global Settings（全局设置）
- **Enable Learning Mode**：启用自动学习
- **Enable Exam Mode**：启用自动考试
- **Concurrent Tasks**：同时运行的任务数（1-10）
- **Retry Attempts**：失败后重试次数（0-10）
- **Timeout**：单个任务超时时间（秒）

### Log Viewer（日志查看器）
- 按账号分类显示
- 显示文件大小和修改时间
- 支持在新窗口查看完整日志
- 自动排序（最新在前）

## 常见问题

### Q: 无法启动 WebUI？

**A:** 检查以下几点：
1. Python 版本是否 3.11+
2. 运行 `pip install -r requirements.txt`
3. 确认 8080 端口未被占用

### Q: 点击 Start Task 无反应？

**A:** 确保：
1. `main.py` 存在于同一目录
2. 已添加至少一个账号
3. 已保存全局设置

### Q: 实时日志不显示？

**A:** 尝试：
1. 刷新页面重新连接 WebSocket
2. 检查浏览器控制台是否有错误
3. 确认防火墙未阻止 WebSocket 连接

### Q: 配置保存失败？

**A:** 检查：
1. 文件权限（确保可写）
2. 磁盘空间是否充足
3. config.toml 语法是否正确

### Q: 如何更改端口？

**A:** 设置环境变量：
```bash
set WEBUI_PORT=9000
python webui.py
```

### Q: 如何远程访问？

**A:** 修改绑定地址：
```bash
set WEBUI_HOST=0.0.0.0
python webui.py
```

⚠️ **安全提示**：远程访问时建议配置防火墙规则或添加认证机制

## 技术支持

- 详细文档：[README_WEBUI.md](README_WEBUI.md)
- 项目目录结构：
  ```
  WeBan-webui-main/
  ├── webui.py           # 主程序（单文件完整实现）
  ├── start_webui.bat    # Windows 启动脚本
  ├── requirements.txt   # Python 依赖
  ├── config.toml        # 配置文件（自动生成）
  ├── main.py            # WeBan 主程序
  └── logs/              # 日志目录（自动创建）
      └── {account}/     # 按账号分类
  ```

## 键盘快捷键

- `Ctrl + C`：停止 WebUI 服务器
- `F5`：刷新页面
- `Ctrl + Shift + I`：打开浏览器开发者工具（调试用）

## 下一步

1. ✅ 添加你的第一个账号
2. ✅ 配置学习和考试模式
3. ✅ 启动任务并观察实时日志
4. ✅ 定期检查历史日志了解执行情况

---

**祝使用愉快！** 🚀
