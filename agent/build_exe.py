import os
import sys
import subprocess
import shutil
from datetime import datetime
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
SWAPPER_EXE_NAME = "swapper"


def _read_default_version() -> str:
    """Read default version from agent/VERSION.txt if available."""
    version_file = AGENT_DIR / "VERSION.txt"
    if not version_file.exists():
        return "2.0.0"

    try:
        for line in version_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("version:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    except Exception:
        pass

    return "2.0.0"


def _resolve_build_version() -> str:
    """
    Resolve build version from:
      1) CLI argument (python build_exe.py 2.7.0)
      2) interactive input prompt
      3) VERSION.txt default
    """
    default_version = _read_default_version()

    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()

    if sys.stdin.isatty():
        entered = input(f"Enter build version [{default_version}]: ").strip()
        if entered:
            return entered

    return default_version


def _write_version_file(version: str) -> bool:
    """Write dist/VERSION.txt required by install_exe.bat."""
    try:
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        build_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = (
            "SentinelEdge Agent\n"
            f"Version: {version}\n"
            f"Build Date: {build_date}\n"
            "\n"
            "Installation:\n"
            "  1. Run install_exe.bat as Administrator\n"
            "  2. Enter server URL and registration secret\n"
        )
        out_file = DIST_DIR / "VERSION.txt"
        out_file.write_text(content, encoding="utf-8")
        print(f"[OK] Version file created: dist/VERSION.txt (Version: {version})")
        return True
    except Exception as e:
        print(f"[FAIL] Could not write dist/VERSION.txt: {e}")
        return False


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
    """Common hidden imports needed by the agent.
    
    AUDIT (2026-03-11): Verified against actual module files in core/ and helper/.
    Includes lazy imports from collector.py (security_collector, extended_inventory).
    """
    return [
        # stdlib extensions (needed by PyInstaller)
        "json",
        "hashlib",
        "hmac",
        "logging",
        "pathlib",
        "ctypes",
        "ctypes.wintypes",
        "threading",
        "enum",
        
        # third-party
        "psutil",
        "requests",
        "urllib3",
        "pytz",
        
        # pywin32
        "win32api",
        "win32con",
        "win32gui",
        "win32security",
        "win32process",
        "win32event",
        "win32ts",
        "win32service",
        "win32serviceutil",
        "servicemanager",
        "pywintypes",
        "winerror",
        
        # root-level modules
        "logger",
        
        # core modules (14 files)
        "core",
        "core.service",
        "core.config",
        "core.config_schema",
        "core.agent_time",
        "core.ingest",
        "core.buffer",
        "core.uploader",
        "core.aggregator",
        "core.state_machine",
        "core.live_telemetry",
        "core.integrity",
        "core.secure_store",
        "core.updater",
        
        # helper modules (20 files)
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
        "helper.security_collector",    # lazy-imported by collector.py
        "helper.performance",
        "helper.persistence",
        "helper.state_detector",
        "helper.identity_sync",
        "helper.app_names",
    ]


def get_swapper_imports():
    """Minimal hidden imports for swapper build."""
    return [
        "psutil",
    ]


def build_exe(
    script_name,
    exe_name,
    admin=False,
    noconsole=False,
    icon=None,
    hidden_imports=None,
):
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
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--clean",
    ]

    # Add all hidden imports
    imports_to_use = hidden_imports if hidden_imports is not None else get_hidden_imports()
    for mod in imports_to_use:
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
    build_version = _resolve_build_version()
    print(f"[INFO] Build version: {build_version}")

    success = True

    # 1. Build Core (Admin context - runs as SYSTEM service via NSSM) -> windiag.exe
    if not build_exe("sentinel_core.py", CORE_EXE_NAME, admin=True):
        success = False

    # 2. Build Helper (User context - runs as logged-in user, no console window) -> syshealth.exe
    if success:
        if not build_exe("sentinel_helper.py", HELPER_EXE_NAME, admin=False, noconsole=True):
            success = False

    # 3. Build Swapper (detached helper for EXE bundle replacement) -> swapper.exe
    if success:
        swapper_src = AGENT_DIR / "tools" / "swapper.py"
        swapper_tmp = AGENT_DIR / "_swapper_build_tmp.py"
        if not swapper_src.exists():
            print(f"[FAIL] Missing swapper source: {swapper_src}")
            success = False
        else:
            shutil.copy2(swapper_src, swapper_tmp)
            try:
                if not build_exe(
                    "_swapper_build_tmp.py",
                    SWAPPER_EXE_NAME,
                    admin=False,
                    noconsole=True,
                    hidden_imports=get_swapper_imports(),
                ):
                    success = False
                else:
                    tools_dir = DIST_DIR / "tools"
                    tools_dir.mkdir(parents=True, exist_ok=True)

                    built_candidates = [
                        DIST_DIR / f"{SWAPPER_EXE_NAME}.exe",
                        DIST_DIR / "tools" / f"{SWAPPER_EXE_NAME}.exe",
                    ]
                    built_swapper = next((p for p in built_candidates if p.exists()), None)
                    target_swapper = tools_dir / f"{SWAPPER_EXE_NAME}.exe"

                    if built_swapper is None:
                        print("[FAIL] swapper.exe not found after build")
                        success = False
                    elif built_swapper == target_swapper:
                        print(f"[OK] Swapper staged: dist/tools/{SWAPPER_EXE_NAME}.exe")
                    else:
                        if target_swapper.exists():
                            target_swapper.unlink()
                        shutil.move(str(built_swapper), str(target_swapper))
                        print(f"[OK] Swapper staged: dist/tools/{SWAPPER_EXE_NAME}.exe")
            finally:
                if swapper_tmp.exists():
                    swapper_tmp.unlink()

                tmp_spec = AGENT_DIR / "_swapper_build_tmp.spec"
                if tmp_spec.exists():
                    tmp_spec.unlink()

    print()
    print("=" * 70)
    if success:
        if not _write_version_file(build_version):
            success = False

    if success:
        print("  BUILD SUCCESSFUL")
        print(f"  Core:   dist/{CORE_EXE_NAME}.exe")
        print(f"  Helper: dist/{HELPER_EXE_NAME}.exe")
        print(f"  Swapper: dist/tools/{SWAPPER_EXE_NAME}.exe")
        print("  Version: dist/VERSION.txt")
    else:
        print("  BUILD FAILED - Check errors above")
    print("=" * 70)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
