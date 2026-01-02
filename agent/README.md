# SentinelEdge Agent v2.1.0

Enterprise-grade endpoint monitoring agent for Windows.

## 📦 Quick Start

### Prerequisites
- Windows 10/11 (x64)
- Administrator privileges
- Network access to SentinelEdge server

### Installation (3 steps)

1. **Extract** the deployment package to a folder
2. **Right-click** `install.bat` → **Run as administrator**
3. **Enter** server URL and registration secret when prompted

That's it! The agent will start automatically.

---

## 🔧 What Gets Installed

| Component | Location | Purpose |
|-----------|----------|---------|
| Core Service | `C:\Program Files\SentinelEdge` | System-level data collector |
| Helper Process | (User session) | Active window/app tracking |
| Python 3.13 | Bundled | No system dependency needed |
| Data | `C:\ProgramData\SentinelEdge` | Config, logs, buffer |

---

## 📊 Collected Data

| Data Type | Description | Frequency |
|-----------|-------------|-----------|
| **Screen Time** | Active, idle, locked duration | Every heartbeat |
| **App Usage** | Which apps were active | Real-time |
| **Domain Visits** | Active browser domains | Real-time |
| **App Inventory** | Installed applications | Every 4 hours |

---

## 🛡️ Security Features

- ✅ **Bundled Python** - No user Python dependency
- ✅ **Compiled .pyc** - Source code not exposed
- ✅ **Read-only** - Users cannot modify agent files
- ✅ **SYSTEM Service** - Tamper-resistant
- ✅ **HMAC Signing** - Data integrity verification
- ✅ **Certificate Pinning** - HTTPS validation

---

## 📁 Package Contents

```
SentinelEdge-Agent-2.1.0/
├── install.bat          # Main installer
├── uninstall.bat        # Clean removal
├── update.bat           # In-place update
├── view_logs.bat        # Quick log viewer
├── sentinel_core.py     # Core entry point
├── sentinel_helper.py   # Helper entry point
├── core/                # Core module
│   ├── service.py       # Service framework
│   ├── buffer.py        # SQLite buffering
│   ├── uploader.py      # Server communication
│   └── ...
├── helper/              # Helper module
│   ├── main.py          # Helper main loop
│   ├── collector.py     # Data collection
│   ├── idle.py          # Idle detection
│   └── ...
├── nssm/                # Service manager
│   └── win64/nssm.exe
├── python313/           # Bundled Python 3.13
└── VERSION.txt          # Version info
```

---

## 🔌 Configuration

After installation, config is at: `C:\ProgramData\SentinelEdge\config.json`

```json
{
    "server_url": "http://192.168.1.101:5050",
    "agent_id": "auto-generated",
    "heartbeat_interval": 300,
    "features": {
        "app_tracking": true,
        "domain_tracking": true,
        "idle_detection": true,
        "inventory": true
    }
}
```

---

## 📋 Management Commands

### Check service status
```cmd
sc query SentinelEdgeCore
```

### View logs
```cmd
type "C:\ProgramData\SentinelEdge\logs\core_stderr.log"
```

### Restart service
```cmd
net stop SentinelEdgeCore && net start SentinelEdgeCore
```

### Start helper manually
```cmd
schtasks /run /tn "SentinelEdgeUserHelper"
```

### Uninstall
```cmd
# Run as Administrator
uninstall.bat
```

---

## 🔄 Updates

To update an existing installation:

1. Copy new package to the machine
2. Right-click `update.bat` → **Run as administrator**
3. Service will restart with new version

Configuration and agent ID are preserved during updates.

---

## 🐛 Troubleshooting

### Service won't start

Check the error log:
```cmd
type "C:\ProgramData\SentinelEdge\logs\core_stderr.log"
```

Common issues:
- Server URL incorrect
- Firewall blocking port 5050
- Registration secret expired

### No data in dashboard

1. Verify service is running: `sc query SentinelEdgeCore`
2. Check helper task: `schtasks /query /tn "SentinelEdgeUserHelper"`
3. Verify user logged in interactively (RDP or console)

### High CPU usage

Normal CPU usage: 0.1% - 2%

If higher:
1. Check logs for errors
2. Restart with: `net stop SentinelEdgeCore && net start SentinelEdgeCore`
3. Check for stuck Helper process

---

## 📞 Support

For issues, check:

1. **Logs**: `C:\ProgramData\SentinelEdge\logs\`
2. **Dashboard**: Server → Agents → Agent Details
3. **Version**: `C:\Program Files\SentinelEdge\VERSION.txt`

---

## 📜 Version History

### v2.1.0 (2025-12-31)
- Performance optimizations (SQLite, adaptive polling)
- Enhanced HMAC signing
- Improved idle detection
- Better error handling

### v2.0.0
- Bundled Python 3.13
- Session-based domain tracking
- State change events
- Integrity monitoring

### v1.0.0
- Initial release
