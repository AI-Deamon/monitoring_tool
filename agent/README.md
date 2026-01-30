# 🛡️ SentinelEdge Agent v2.1.0

**Enterprise-grade endpoint monitoring agent for Windows**

SentinelEdge Agent is a lightweight, secure endpoint monitoring solution that collects user activity data including screen time, application usage, and domain visits. It runs silently as a Windows service and securely transmits telemetry to the SentinelEdge Server.

---

## 📋 Table of Contents

- [Features](#-features)
- [System Requirements](#-system-requirements)
- [Quick Start](#-quick-start)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Collected Data](#-collected-data)
- [Architecture](#-architecture)
- [Security](#-security)
- [Management](#-management)
- [Troubleshooting](#-troubleshooting)
- [Updates](#-updates)
- [Uninstallation](#-uninstallation)
- [Version History](#-version-history)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📊 **Screen Time Tracking** | Active, idle, and locked state monitoring |
| 🖥️ **Application Usage** | Real-time tracking of active applications |
| 🌐 **Domain Monitoring** | Browser domain visit tracking (Chrome, Edge, Firefox) |
| 📦 **App Inventory** | Periodic collection of installed applications |
| 🔒 **Secure Communication** | HMAC-signed payloads with HTTPS |
| 💾 **Offline Buffering** | SQLite-based local storage when offline |
| ⚡ **Low Resource Usage** | Optimized for minimal CPU/memory footprint |

---

## 💻 System Requirements

| Requirement | Specification |
|-------------|---------------|
| **OS** | Windows 10/11 (x64) |
| **Privileges** | Administrator (for installation) |
| **RAM** | 50 MB minimum |
| **Disk** | 100 MB (including bundled Python) |
| **Network** | Access to SentinelEdge server (default port 5050) |

> **Note:** Python is bundled with the agent. No system Python installation required.

---

## 🚀 Quick Start

```bash
# 1. Extract the deployment package
# 2. Run as Administrator:
install.bat

# 3. Enter server URL when prompted (e.g., http://192.168.1.100:5050)
# 4. Enter registration secret when prompted
# Done! Agent starts automatically.
```

---

## 📥 Installation

### Step-by-Step Installation

1. **Extract Package**
   - Extract `SentinelEdge-Agent-*.zip` to a temporary folder

2. **Run Installer**
   - Right-click `install.bat` → **Run as administrator**

3. **Configure Connection**
   - Enter the SentinelEdge server URL (e.g., `http://192.168.1.100:5050`)
   - Enter the registration secret provided by your administrator

4. **Verify Installation**
   ```cmd
   sc query SentinelEdgeCore
   ```

### What Gets Installed

| Component | Location | Purpose |
|-----------|----------|---------|
| **Core Service** | `C:\Program Files\SentinelEdge\` | System-level data collector |
| **Helper Process** | (User session) | Active window/app tracking |
| **Python 3.13** | `C:\Program Files\SentinelEdge\python313\` | Bundled runtime |
| **Data Directory** | `C:\ProgramData\SentinelEdge\` | Config, logs, buffer |

---

## ⚙️ Configuration

Configuration file location: `C:\ProgramData\SentinelEdge\config.json`

### Default Configuration

```json
{
    "server_url": "http://192.168.1.100:5050",
    "agent_id": "auto-generated-uuid",
    "heartbeat_interval": 10,
    "features": {
        "app_tracking": true,
        "domain_tracking": true,
        "idle_detection": true,
        "inventory": true
    },
    "performance": {
        "batch_size": 50,
        "upload_interval": 60,
        "idle_threshold": 120
    }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `server_url` | string | - | SentinelEdge server URL |
| `agent_id` | string | auto | Unique agent identifier |
| `heartbeat_interval` | int | 10 | Seconds between heartbeats |
| `features.app_tracking` | bool | true | Track active applications |
| `features.domain_tracking` | bool | true | Track browser domains |
| `features.idle_detection` | bool | true | Detect idle/locked states |
| `features.inventory` | bool | true | Collect app inventory |

---

## 📊 Collected Data

### Data Types

| Data Type | Description | Collection Frequency |
|-----------|-------------|---------------------|
| **Screen Time** | Active, idle, and locked duration | Every heartbeat (5 min) |
| **App Usage** | Active application windows | Real-time (on change) |
| **Domain Visits** | Browser tab domains | Real-time (on change) |
| **App Inventory** | Installed applications list | Every 4 hours |
| **State Changes** | Active/Idle/Locked transitions | On event |

### Data Privacy

- ✅ Only tracks **active window titles**, not content
- ✅ Domain tracking limited to **visited domains**, not full URLs
- ✅ No keystrokes or screen captures
- ✅ All data encrypted in transit

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Windows System                          │
├────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐    ┌─────────────────────────┐   │
│  │  SentinelEdge Core  │    │   SentinelEdge Helper   │   │
│  │   (SYSTEM Service)  │◄───│    (User Session)       │   │
│  │                     │    │                         │   │
│  │  • Buffer Manager   │    │  • Window Tracker       │   │
│  │  • Uploader         │    │  • Idle Detector        │   │
│  │  • Aggregator       │    │  • Domain Collector     │   │
│  │  • Integrity Check  │    │  • App Inventory        │   │
│  └──────────┬──────────┘    └─────────────────────────┘   │
│             │                                              │
│             ▼                                              │
│  ┌─────────────────────┐                                  │
│  │   SQLite Buffer     │                                  │
│  │   (Offline Queue)   │                                  │
│  └──────────┬──────────┘                                  │
└─────────────┼──────────────────────────────────────────────┘
              │ HTTPS + HMAC
              ▼
┌─────────────────────────┐
│  SentinelEdge Server    │
│  (PostgreSQL Backend)   │
└─────────────────────────┘
```

### Components

| Component | File | Role |
|-----------|------|------|
| **Core Service** | `sentinel_core.py` | Main service, runs as SYSTEM |
| **Helper** | `sentinel_helper.py` | User-session data collection |
| **Buffer** | `core/buffer.py` | SQLite offline storage |
| **Uploader** | `core/uploader.py` | Server communication |
| **Collector** | `helper/collector.py` | Data collection orchestration |
| **Idle Detector** | `helper/idle.py` | User activity monitoring |

---

## 🔒 Security

### Security Features

| Feature | Description |
|---------|-------------|
| 🔐 **HMAC Signing** | All payloads signed with agent-specific key |
| 🔒 **HTTPS Support** | TLS encryption for data in transit |
| 📜 **Certificate Pinning** | Optional server certificate validation |
| 🛡️ **SYSTEM Service** | Core runs with elevated privileges |
| 📁 **Read-Only Files** | Agent files protected from modification |
| 🐍 **Bundled Python** | No dependency on system Python |
| 🔢 **Integrity Monitoring** | Self-verification of critical files |

### File Permissions

After installation, agent files are protected:
- `C:\Program Files\SentinelEdge\` - Read-only for non-admins
- `C:\ProgramData\SentinelEdge\config.json` - Read-only for users
- `C:\ProgramData\SentinelEdge\logs\` - Write access for service only

---

## 🔧 Management

### Service Commands

```cmd
# Check service status
sc query SentinelEdgeCore

# Start service
net start SentinelEdgeCore

# Stop service
net stop SentinelEdgeCore

# Restart service
net stop SentinelEdgeCore && net start SentinelEdgeCore
```

### Helper Task Commands

```cmd
# Check helper task status
schtasks /query /tn "SentinelEdgeUserHelper"

# Manually run helper
schtasks /run /tn "SentinelEdgeUserHelper"
```

### Log Files

| Log | Location | Contents |
|-----|----------|----------|
| **Core Log** | `C:\ProgramData\SentinelEdge\logs\core_stderr.log` | Service errors |
| **Helper Log** | `C:\ProgramData\SentinelEdge\logs\helper_stderr.log` | Helper errors |

### View Logs

```cmd
# Quick log viewer
view_logs.bat

# Or manually
type "C:\ProgramData\SentinelEdge\logs\core_stderr.log"
```

---

## 🐛 Troubleshooting

### Common Issues

#### Service Won't Start

1. Check error log:
   ```cmd
   type "C:\ProgramData\SentinelEdge\logs\core_stderr.log"
   ```

2. Common causes:
   - ❌ Server URL incorrect
   - ❌ Firewall blocking port 5050
   - ❌ Registration secret expired

#### No Data in Dashboard

1. Verify service running:
   ```cmd
   sc query SentinelEdgeCore
   ```

2. Check helper task:
   ```cmd
   schtasks /query /tn "SentinelEdgeUserHelper"
   ```

3. Ensure user is logged in interactively (RDP or console)

#### High CPU Usage

Normal: 0.1% - 2%

If higher:
1. Check logs for errors
2. Restart service: `net stop SentinelEdgeCore && net start SentinelEdgeCore`
3. Check for stuck Helper process in Task Manager

#### Connection Errors

1. Test server connectivity:
   ```cmd
   curl http://YOUR_SERVER:5050/
   ```

2. Check firewall rules
3. Verify server is running

---

## 🔄 Updates

### Update Procedure

1. Copy new package to the machine
2. Right-click `update.bat` → **Run as administrator**
3. Service restarts automatically

### What's Preserved

- ✅ Configuration (`config.json`)
- ✅ Agent ID
- ✅ Registration
- ✅ Buffered data

---

## 🗑️ Uninstallation

### Complete Removal

```cmd
# Run as Administrator
uninstall.bat
```

### Manual Removal

```cmd
# 1. Stop and remove services
net stop SentinelEdgeCore
nssm remove SentinelEdgeCore confirm

# 2. Remove scheduled task
schtasks /delete /tn "SentinelEdgeUserHelper" /f

# 3. Remove files
rmdir /s /q "C:\Program Files\SentinelEdge"
rmdir /s /q "C:\ProgramData\SentinelEdge"
```

---

## 📜 Version History

### v2.1.0 (2026-01-01)
- ⚡ Performance optimizations (SQLite WAL, adaptive polling)
- 🔒 Enhanced HMAC signing with timestamp validation
- 🖥️ Improved idle/away detection accuracy
- 🐛 Better error handling and recovery
- 📊 Reduced memory footprint

### v2.0.0 (2025-12-01)
- 🐍 Bundled Python 3.13 (no system dependency)
- 🌐 Session-based domain tracking
- 📊 State change events (active/idle/locked)
- 🔐 File integrity monitoring

### v1.0.0 (2025-10-01)
- 🎉 Initial release

---

## 📞 Support

For issues:

1. **Check Logs**: `C:\ProgramData\SentinelEdge\logs\`
2. **Dashboard**: Server → Agents → Agent Details
3. **Version Info**: `C:\Program Files\SentinelEdge\VERSION.txt`

---

## 📄 License

Proprietary - Internal Use Only

© 2026 SentinelEdge. All Rights Reserved.
