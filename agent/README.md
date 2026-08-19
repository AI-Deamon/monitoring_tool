# SentinelEdge Agent

**Endpoint monitoring agent for Windows.**

SentinelEdge Agent collects user activity and asset data (screen time, application usage,
domain visits, hardware/software inventory, and security posture) and reports it to the
SentinelEdge Server. It runs as two Windows processes and buffers data locally when offline.

> Current shipped version lives in [`VERSION.txt`](VERSION.txt) — this document intentionally
> doesn't hardcode a version number or a change history; both go stale immediately. For what
> changed and when, use `git log`.

---

## Table of Contents

- [Features](#features)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Collected Data](#collected-data)
- [Architecture](#architecture)
- [Security](#security)
- [Management](#management)
- [Diagnostics](#diagnostics)
- [Updates](#updates)
- [Uninstallation](#uninstallation)
- [Support](#support)

---

## Features

| Feature | Description |
|---------|-------------|
| Screen Time Tracking | Active / idle / locked / away state, session-lock-aware |
| Application Usage | Active-window tracking |
| Domain Monitoring | Browser tab/domain visits (Chrome, Edge, Firefox) |
| App Inventory | Installed applications, drivers, browser extensions, VS Code extensions, CLI tools, portable apps |
| Hardware Inventory | CPU/RAM/GPU/disk/motherboard, battery health (design vs. full-charge capacity) |
| Security Posture | Antivirus, firewall, BitLocker, Windows Update status |
| EOL / Lifecycle Tracking | OS and installed-software end-of-life status |
| Network Monitoring | Interface/connection visibility |
| Offline Buffering | SQLite-based local queue; survives restarts and network loss |
| Auto-Update | Server-driven, no manual reinstall — see [Updates](#updates) |

The exact set of collectors is defined in `helper/collector.py`; source modules are listed in
[Architecture](#architecture) below.

---

## System Requirements

| Requirement | Specification |
|-------------|---------------|
| OS | Windows 10/11 (x64) |
| Privileges | Administrator (for install/uninstall only; the service itself runs as SYSTEM/user) |
| Disk | ~50 MB (Core + Helper + Swapper executables) |
| Network | Access to the SentinelEdge server (default port 5050) |

No system Python installation is required — the shipped `.exe` files are self-contained
(built with PyInstaller via [`build_exe.py`](build_exe.py)).

---

## Installation

1. Extract the deployment package (built via `agent/build_exe.py` + the server's
   `create_update_package.py`) to a temporary folder.
2. Right-click **`install_exe.bat`** → **Run as administrator**.
3. Enter the server URL (e.g. `http://192.168.1.100:5050`) and the registration secret
   provided by your administrator when prompted.
4. Verify:
   ```cmd
   sc query WinDiagSvc
   schtasks /query /tn "SysHealthMon"
   ```

`install_exe.bat` also detects and cleans up an older pre-rename install (service
`SentinelEdgeCore`, paths under `SentinelEdge`) if present, migrating to the current layout
below.

### What Gets Installed

| Component | Location | Purpose |
|-----------|----------|---------|
| Core service (`windiag.exe`) | `C:\Program Files\WinDiagSvc\` | System-level collector, buffer, uploader — runs as SYSTEM via NSSM |
| Helper (`syshealth.exe`) | Scheduled task, user session | Window/idle/domain/inventory collection |
| Swapper (`swapper.exe`) | `C:\Program Files\WinDiagSvc\tools\` | Applies EXE-bundle auto-updates |
| Data directory | `C:\ProgramData\WinDiagSvc\` | Config, logs, offline buffer, certs |

The Core service name is `WinDiagSvc`; the Helper scheduled task is `SysHealthMon`. The
executable names and service naming are deliberately unremarkable (see `build_exe.py`'s
`CORE_EXE_NAME`/`HELPER_EXE_NAME`) so the agent doesn't stand out from ordinary Windows system
processes — this is by design for an endpoint-monitoring agent, not an oversight.

---

## Configuration

Config file: `C:\ProgramData\WinDiagSvc\config.json`.

The authoritative schema is `core/config_schema.py` / `core/config.py` — consult those before
hand-editing, since the schema has grown well past a flat key/value list. Confirmed top-level
sections as of this writing:

- `server` — `url`, `registration_secret`, `cert_pinning_fingerprint`, `ssl_enabled`,
  `allow_insecure_http`, client/CA cert paths
- `agent` — `agent_id`, `local_agent_key`, `agent_name`, `current_version`

Most values are set once at install time via `install_exe.bat`'s prompts and shouldn't need
manual editing afterward.

---

## Collected Data

### Data Privacy

- Tracks **active window titles**, not window content
- Domain tracking is limited to **visited domains**, not full URLs or page content
- **No keystroke logging, no screen captures** (verified: no keyboard-hook or key-state code
  anywhere in this tree)
- Payloads are HMAC/cert-pinned in transit — see [Security](#security)

For exact fields collected, the collector source modules under `helper/` are the source of
truth (see [Architecture](#architecture)) — this section intentionally stays high-level rather
than re-listing every field, which drifts out of sync with the code quickly.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         Windows System                            │
├──────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────┐        ┌────────────────────────────┐ │
│  │  Core (windiag.exe)   │        │  Helper (syshealth.exe)    │ │
│  │  SYSTEM service        │◄───────│  Scheduled task, user      │ │
│  │  (WinDiagSvc)          │        │  session (SysHealthMon)    │ │
│  │                        │        │                            │ │
│  │  • buffer.py            │        │  • window.py, idle.py     │ │
│  │  • uploader.py          │        │  • domain.py               │ │
│  │  • aggregator.py        │        │  • state_detector.py       │ │
│  │  • integrity.py         │        │  • inventory.py            │ │
│  │  • updater.py           │        │  • hardware_collector.py   │ │
│  │  • secure_store.py      │        │  • security_collector.py   │ │
│  │  • state_machine.py     │        │  • eol_collector.py        │ │
│  │                        │        │  • extended_inventory.py   │ │
│  │                        │        │  • network_watcher.py      │ │
│  └───────────┬────────────┘        └────────────────────────────┘ │
│              │                                                     │
│              ▼                                                     │
│  ┌───────────────────────┐                                        │
│  │  SQLite Buffer        │                                        │
│  │  (offline queue)      │                                        │
│  └───────────┬────────────┘                                       │
└──────────────┼──────────────────────────────────────────────────┘
               │ HTTPS + cert pinning + registration secret
               ▼
┌───────────────────────────┐
│  SentinelEdge Server      │
│  (PostgreSQL backend)     │
└───────────────────────────┘
```

| Component | File | Role |
|-----------|------|------|
| Core entry point | `sentinel_core.py` | Runs as SYSTEM |
| Helper entry point | `sentinel_helper.py` | Runs in the user session |
| Buffer | `core/buffer.py` | SQLite offline storage |
| Uploader | `core/uploader.py` | Server communication, cert pinning |
| Updater | `core/updater.py` | Auto-update orchestration |
| Secure storage | `core/secure_store.py` | DPAPI (Windows) / `cryptography` fallback for secrets at rest |
| Collector orchestration | `helper/collector.py` | Wires up all Helper-side collectors |
| Swapper | `tools/swapper.py` | Detached process that applies EXE-bundle updates |

---

## Security

| Mechanism | Notes |
|-----------|-------|
| Certificate pinning | `server_cert_fingerprint`/`cert_pinning_fingerprint` in config; validated in `core/uploader.py` (tagged `SEC-021`) |
| Registration secret | Required to register a new agent against the server |
| Secure local storage | Windows DPAPI first, `cryptography` library fallback; **refuses to run with neither** rather than storing secrets insecurely (`core/secure_store.py`, `SEC-004`) |
| SYSTEM service | Core runs elevated; Helper runs in the user session, not elevated |
| Integrity monitoring | `core/integrity.py` self-verifies critical files |
| No plaintext-only fallback | See Secure local storage above — there is deliberately no insecure fallback path |

---

## Management

```cmd
:: Core service
sc query WinDiagSvc
net start WinDiagSvc
net stop WinDiagSvc

:: Helper task
schtasks /query /tn "SysHealthMon"
schtasks /run /tn "SysHealthMon"
```

### Logs

| Log | Location |
|-----|----------|
| Core | `C:\ProgramData\WinDiagSvc\logs\core.log` (rotates at 5MB, 3 backups) |
| Helper | `C:\ProgramData\WinDiagSvc\logs\helper.log` (same rotation) |

---

## Diagnostics

Standalone ops/support tools live in [`diagnostics/`](diagnostics/) — run manually, not
invoked by the install/update flow:

| Tool | Purpose |
|------|---------|
| `diagnostics/collect_diagnostics.bat` | Packages recent logs + system info into a zip for support |
| `diagnostics/quick_restart.bat` | Restarts Core/Helper without a full reinstall |
| `diagnostics/verify_buffer_health.py` | Inspects the offline SQLite buffer (`python verify_buffer_health.py --db <path>`) |
| `diagnostics/verify_runtime_syntax.py` | Compile-checks the entry points and `core/`/`helper/` before shipping a build |

### Common Issues

**Service won't start** — check `core.log` first; common causes are a wrong server URL, a
firewall blocking port 5050, or an expired registration secret.

**No data in dashboard** — confirm the service is running (`sc query WinDiagSvc`) and the
Helper task is present (`schtasks /query /tn "SysHealthMon"`); the Helper only collects while a
user is logged in interactively (console or RDP).

**Suspected buffer backlog** — run `diagnostics/verify_buffer_health.py` against
`C:\ProgramData\WinDiagSvc\buffer\core_buffer.db`.

---

## Updates

Updates are **server-driven and automatic**, not a manual script the operator runs:

1. Core polls the server's update endpoint and downloads a new package when one is published.
2. `core/updater.py` verifies the package, then hands off to `tools/swapper.py` — a detached
   process that waits for Core to exit, replaces the `.exe` files, and restarts the service
   (a running `.exe` can't overwrite itself).
3. Config, agent ID, registration, and buffered data are preserved across the swap.

There is no `update.bat` — that described an older manual packaging flow that no longer
exists.

---

## Uninstallation

```cmd
:: Run as Administrator
uninstall_exe.bat
```

Manual removal, if needed:

```cmd
net stop WinDiagSvc
"C:\Program Files\WinDiagSvc\nssm\win64\nssm.exe" remove WinDiagSvc confirm
schtasks /delete /tn "SysHealthMon" /f
rmdir /s /q "C:\Program Files\WinDiagSvc"
rmdir /s /q "C:\ProgramData\WinDiagSvc"
```

---

## Support

1. Check logs: `C:\ProgramData\WinDiagSvc\logs\`
2. Run `diagnostics/collect_diagnostics.bat` and send the resulting zip
3. Dashboard: Server → Agents → Agent Details
4. Version info: `C:\Program Files\WinDiagSvc\VERSION.txt`

---

## License

Proprietary — Internal Use Only.
