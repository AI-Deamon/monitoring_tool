# SentinelEdge Agent - Installation Instructions

## Quick Install

1. **Download** the `SentinelEdge_Release.zip` package
2. **Extract** to any folder
3. **Right-click** `install.bat` → **Run as Administrator**
4. **Enter server URL** when prompted: `http://192.168.1.101:5050`
5. Wait for installation to complete (~30 seconds)

## What Gets Installed

- **Core Service** - Runs in background, sends telemetry to server
- **Helper Process** - Tracks your active apps and browser usage

## After Installation

The agent will automatically:
- ✅ Start on boot
- ✅ Track screen time (active/idle/locked)
- ✅ Monitor app usage
- ✅ Track browser domains visited
- ✅ Report app inventory (every 4 hours)

## Verification

Open Command Prompt and run:
```batch
sc query SentinelEdgeCore
```

You should see `STATE: RUNNING`

## Uninstall

Right-click `uninstall.bat` → Run as Administrator

---

## ⚠️ Antivirus Exclusions (Recommended)

To ensure optimal performance and prevent false positives, add these exclusions to your antivirus software:

### Folders to Exclude:
```
C:\ProgramData\SentinelEdge\
C:\Program Files\SentinelEdge\
```

### Processes to Exclude:
```
pythonw.exe       (Helper process)
python.exe        (Core service)
nssm.exe          (Service manager)
```

### Why This Is Important:
- Antivirus real-time scanning can cause high CPU usage
- May interfere with browser history reading (domain tracking)
- Can slow down app inventory collection

---

## Performance Notes

The agent is designed to be lightweight:

| State | CPU Usage | Memory |
|-------|-----------|--------|
| Active | < 5% | < 100 MB |
| Idle | < 2% | < 100 MB |
| Locked | < 1% | < 80 MB |

If you notice high CPU/memory usage, check:
1. Antivirus exclusions configured?
2. Multiple browser tabs with history access?
3. Large app inventory (1000+ apps)?

---

**Questions?** Contact the IT team.

