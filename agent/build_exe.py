import os
import sys
import subprocess
import shutil
from pathlib import Path

# ============================================================================
# SentinelEdge Agent - EXE Build Script (Stealth Edition)
# ============================================================================
# Uses PyInstaller to bundle the Agent into standalone executables.
# Output names are disguised to blend with Windows system services:
#   1. windiag.exe     (Core - Admin context, runs as SYSTEM service via NSSM)
#   2. syshealth.exe   (Helper - User context, runs as logged-in user)
# ============================================================================

AGENT_DIR = Path(__file__).parent.absolute()
DIST_DIR = AGENT_DIR / "dist"
BUILD_DIR = AGENT_DIR / "build"

# Stealth output names
CORE_EXE_NAME = "windiag"
HELPER_EXE_NAME = "syshealth"


def clean_build():
    """Remove previous build artifacts"""
    print("[INFO] Cleaning build directories...")
    for d in [DIST_DIR, BUILD_DIR]:
        if d.exists():
            try:
                shutil.rmtree(d)
            except PermissionError:
                print(f"[WARN] Cannot remove {d.name}/ (locked) - will overwrite files in place")
            except Exception as e:
                print(f"[WARN] Cannot remove {d.name}/: {e}")

    for spec in AGENT_DIR.glob("*.spec"):
        try:
            spec.unlink()
        except Exception:
            pass
    print("[OK] Clean complete.")


def get_hidden_imports():
    """Common hidden imports needed by the agent"""
    return [
        "psutil",
        "requests",
        "urllib3",
        "json",
        "hashlib",
        "hmac",
        "logging",
        "pathlib",
        "ctypes",
        "ctypes.wintypes",
        # pywin32
        "win32api",
        "win32con",
        "win32security",
        "win32process",
        "win32event",
        "win32gui",
        "win32ts",
        "pywintypes",
        "winerror",
        # core modules
        "core",
        "core.service",
        "core.config",
        "core.config_schema",
        "core.ingest",
        "core.buffer",
        "core.uploader",
        "core.aggregator",
        "core.state_machine",
        "core.live_telemetry",
        "core.integrity",
        "core.secure_store",
        "core.updater",
        # helper modules
        "helper",
        "helper.main",
        "helper.collector",
        "helper.comm",
        "helper.config",
        "helper.idle",
        "helper.window",
        "helper.domain",
        "helper.inventory",
        "helper.extended_inventory",
        "helper.eol_collector",
        "helper.hardware_collector",
        "helper.security",
        "helper.performance",
        "helper.persistence",
        "helper.state_detector",
        "helper.state_detector_spans",
        "helper.identity_sync",
        "helper.app_names",
    ]


def build_exe(script_name, exe_name, admin=False, noconsole=False, icon=None):
    """Run PyInstaller for a specific entry point"""
    print(f"\n{'='*70}")
    print(f"[BUILD] {script_name} -> {exe_name}.exe (admin={admin}, noconsole={noconsole})")
    print(f"{'='*70}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--name", exe_name,
        "--paths", str(AGENT_DIR),
        "--clean",
    ]

    # Add all hidden imports
    for mod in get_hidden_imports():
        cmd.extend(["--hidden-import", mod])

    if admin:
        cmd.append("--uac-admin")

    if noconsole:
        cmd.append("--noconsole")

    if icon and (AGENT_DIR / icon).exists():
        cmd.extend(["--icon", str(AGENT_DIR / icon)])

    cmd.append(str(AGENT_DIR / script_name))

    print(f"[CMD] {' '.join(cmd[:10])}... ({len(cmd)} args)")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[FAIL] Failed to build {exe_name}.exe")
        # Show last 50 lines of output for debugging
        lines = (result.stdout + result.stderr).strip().split("\n")
        for line in lines[-50:]:
            print(f"  {line}")
        return False

    exe_path = DIST_DIR / f"{exe_name}.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"[OK] {exe_name}.exe built ({size_mb:.1f} MB)")
    else:
        print(f"[OK] {exe_name}.exe build completed")

    return True


def main():
    print("=" * 70)
    print("  SentinelEdge Agent - EXE Builder (Stealth Edition)")
    print("=" * 70)

    # Ensure PyInstaller is installed
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[ERROR] PyInstaller not found. Run: pip install pyinstaller")
        sys.exit(1)

    os.chdir(AGENT_DIR)

    # Clean before build
    clean_build()

    success = True

    # 1. Build Core (Admin context - runs as SYSTEM service via NSSM) -> windiag.exe
    if not build_exe("sentinel_core.py", CORE_EXE_NAME, admin=True):
        success = False

    # 2. Build Helper (User context - runs as logged-in user, no console window) -> syshealth.exe
    if success:
        if not build_exe("sentinel_helper.py", HELPER_EXE_NAME, admin=False, noconsole=True):
            success = False

    print()
    print("=" * 70)
    if success:
        print("  BUILD SUCCESSFUL")
        print(f"  Core:   dist/{CORE_EXE_NAME}.exe")
        print(f"  Helper: dist/{HELPER_EXE_NAME}.exe")
    else:
        print("  BUILD FAILED - Check errors above")
    print("=" * 70)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
