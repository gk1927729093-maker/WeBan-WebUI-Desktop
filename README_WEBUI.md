# WeBan WebUI Documentation

## Overview

WeBan WebUI provides a modern, dark-themed web interface for managing WeBan accounts, controlling tasks, and monitoring logs in real-time.

## Features

### 🎯 Dashboard
- **Task Control**: Start/stop main.py with one click
- **Real-time Logs**: WebSocket-powered live log streaming
- **Status Monitoring**: Visual task status indicators

### 👤 Account Management
- Add new accounts with school name, username, and password
- Search and select the complete school name from the official school list
- View all configured accounts
- Delete accounts individually
- Duplicate detection

### ⚙️ Global Settings
- Configure learning mode: `false`, `true`, or `force`
- Configure exam mode: `false`, `true`, `perfect`, or `force`
- Configure `max_workers`, study time, random answers, and video speed
- Automatic `config.toml` persistence without dropping unknown settings

### 📋 Log Viewer
- Browse all historical log files
- View logs by account
- Display file size and modification time
- Open logs in new window

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

The WeBan runtime targets Python 3.12. Required packages:
- `fastapi` - Web framework
- `uvicorn[standard]` - ASGI server
- `websockets` - Real-time communication
- `tomli-w` - TOML file writing
- `loguru` - Logging (already required by main.py)

### 2. Verify Installation

```bash
python -c "import fastapi, uvicorn, tomli_w; print('All dependencies installed')"
```

## Usage

### Start WebUI

```bash
python webui.py
```

Default: http://127.0.0.1:8080

The WebUI and `main.py` are in the same directory in this fork. The WebUI
starts the real WeBan process with that directory as its working directory.
The account section writes the format used by WeBan:

```toml
[[account]]
tenant_name = "学校登录页显示的完整名称"
username = "学号"
password = "密码"
```

The school name is required and must exactly match the school/tenant name
shown on the WeBan login page.

### Custom Host/Port

```bash
# Environment variables
set WEBUI_HOST=0.0.0.0
set WEBUI_PORT=9000
python webui.py
```

### Custom Data Directory

```bash
set WB_DATA_DIR=D:\custom\path
python webui.py
```

`WB_DATA_DIR` stores `config.toml` and `logs` in the selected directory while
the WebUI still starts the local `main.py`.

## Architecture

### Single-File Design

`webui.py` contains:
- FastAPI backend with all API endpoints
- Embedded HTML/CSS/JS frontend
- WebSocket handler for real-time logs
- Task process management
- TOML configuration handling

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve web interface |
| `/api/config` | GET | Get full configuration |
| `/api/config` | POST | Update configuration |
| `/api/accounts` | GET | List all accounts |
| `/api/accounts` | POST | Add new account |
| `/api/accounts/{username}` | DELETE | Delete account |
| `/api/settings` | GET | Get global settings |
| `/api/settings` | POST | Update settings |
| `/api/task/status` | GET | Get task running status |
| `/api/task/start` | POST | Start main.py |
| `/api/task/stop` | POST | Stop main.py |
| `/api/logs` | GET | List all log files |
| `/api/logs/{account}/{filename}` | GET | Get log content |
| `/ws/logs` | WebSocket | Real-time log streaming |

### Configuration Management

- Uses Python 3.11+ `tomllib` for reading TOML
- Uses `tomli-w` for writing TOML
- Preserves all config.toml structure
- Atomic file writes

### Task Management

- Launches main.py as subprocess
- Captures stdout/stderr
- Streams logs to WebSocket clients
- Graceful shutdown with 5s timeout
- Force kill if necessary

## UI Features

### Design System

- **Dark Theme**: Deep navy base (#0A0D12, #0F172A)
- **Accent Colors**: Cyan (#38BDF8) for interactive elements
- **Typography**: Inter font family
- **Components**: Modern cards with 8-12px radius
- **Responsive**: Mobile-friendly layout

### Navigation

- Sidebar navigation with active state
- Four main sections
- Smooth page transitions

### Real-time Updates

- WebSocket connection for live logs
- 2-second polling for task status
- Auto-scroll log container
- Color-coded log levels (error/success/warning)

## Troubleshooting

### Port Already in Use

```bash
# Use different port
set WEBUI_PORT=8081
python webui.py
```

### Cannot Find main.py

Ensure `main.py` exists in the same directory as `webui.py`, or set `WB_DATA_DIR`:

```bash
set WB_DATA_DIR=D:\Documents\ChatGPT\WeBan-webui-main
python webui.py
```

### WebSocket Connection Failed

- Check browser console for errors
- Ensure no firewall blocking WebSocket
- Try refreshing the page

### Config Not Saving

- Check file permissions on config.toml
- Verify TOML syntax is valid
- Check logs for detailed error messages

## Development

### Adding New Features

1. **Backend**: Add endpoint in `webui.py` before HTML_TEMPLATE
2. **Frontend**: Add JavaScript function in `<script>` section
3. **UI**: Add HTML elements in appropriate page section

### Testing

```bash
# Test config handling
python -c "from webui import load_config, save_config; print(load_config())"

# Test FastAPI routes
python -c "from webui import app; print([r.path for r in app.routes])"
```

### Log Locations

- WebUI logs: Console output from uvicorn
- Task logs: `logs/{account}/` directory
- Main application logs: Handled by main.py's loguru setup

## Security Notes

### Default Configuration

- Binds to `127.0.0.1` (localhost only)
- No authentication built-in
- Suitable for local development

### Production Deployment

If exposing to network:

1. **Add authentication** (JWT, OAuth, or basic auth)
2. **Use HTTPS** (reverse proxy with nginx/Caddy)
3. **Firewall rules** to restrict access
4. **Rate limiting** on API endpoints

### Sensitive Data

- Passwords stored in config.toml (plain text)
- Logs may contain sensitive information
- Consider encrypting config.toml at rest

## License

Same license as WeBan main project.

## Support

For issues or questions:
1. Check this documentation
2. Review console logs
3. Check main.py compatibility
4. Verify all dependencies installed
