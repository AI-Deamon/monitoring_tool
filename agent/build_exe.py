import os
import sys
import importlib
import platform
import shutil
import subprocess
import tempfile
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

    Flags are skipped rather than read as a version: argv[1] used to be taken
    verbatim, so `build_exe.py --allow-missing-deps` would stamp the exe with
    the flag as its version.
    """
    default_version = _read_default_version()

    version = _positional_version()
    if version:
        return version

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
        # Statically imported by helper/main.py, so Analysis would normally
        # find it — listed explicitly because every other helper module is,
        # and a module missing from this list is invisible until someone
        # notices the feature is absent from a shipped binary.
        "helper.network_watcher",
    ]


def get_swapper_imports():
    """Minimal hidden imports for swapper build."""
    return [
        "psutil",
    ]


# ---------------------------------------------------------------------------
# Dependency verification (build-time only)
#
# AUDIT (2026-10-15): a shipped build was produced by an interpreter that had
# requests/urllib3 but not psutil or pywin32. PyInstaller treats an
# unresolvable --hidden-import as a WARNING rather than an error, and
# build_exe() captured stdout/stderr and printed it only when the build itself
# failed, so those warnings were discarded and the run printed BUILD SUCCESSFUL.
# The resulting exes shipped with neither library: inspecting them found zero
# psutil and zero pywin32 entries, across every build going back to 29-09.
#
# Every endpoint running those exes then logged "pywin32 not available" and
# "psutil not available". Neither message depends on the endpoint — the modules
# were absent from the binary, so the outcome was identical on every machine.
# Two consequences beyond the warnings: core/service.py's HelperMonitor.start()
# returns immediately without psutil, so nothing watched the Helper or ever
# reported DEGRADED, and state_detector.py lost its WTS lock/unlock event loop.
#
# The two checks below close that hole and report at BUILD time only:
#   _preflight()   the libraries must import in THIS interpreter
#   _verify_exe()  they must actually be present inside the finished .exe
# _verify_exe() is the one that matters. An installed library can still fail to
# bundle, so only reading the shipped binary proves anything. That is precisely
# the step that was never performed, which is why a broken build looked green.
# ---------------------------------------------------------------------------

# Third-party runtime dependencies, as declared in agent/requirements.txt.
AGENT_RUNTIME_DEPS = ["psutil", "pytz", "requests", "urllib3"]

# The pywin32 surface the agent imports directly.
WIN32_RUNTIME_DEPS = [
    "win32api",
    "win32con",
    "win32gui",
    "winerror",
    "pywintypes",
    "win32service",
    "win32serviceutil",
    "servicemanager",
]

# The DLL pywintypes loads at runtime. The Python names above prove nothing
# about this: pywin32 ships as a .pyd plus a version-stamped DLL under
# pywin32_system32 (pywintypes3XX.dll), and that DLL is what actually fails to
# resolve inside a --onefile bundle.
#
# pythoncom.dll is deliberately NOT required. It only backs `import pythoncom`
# for COM, which the agent never uses (verified: no pythoncom/win32com import
# anywhere under agent/), so demanding it would fail every build for a library
# nothing loads.
WIN32_REQUIRED_DLLS = ["pywintypes"]

# Set on this process when --bootstrap actually installed something. Drives a
# one-time re-exec, because newly installed packages are not visible to an
# interpreter that was already running.
BOOTSTRAP_ENV = "SENTINELEDGE_BUILD_BOOTSTRAPPED"

_BOOTSTRAPPED = False


def _allow_missing_deps() -> bool:
    """--allow-missing-deps downgrades every dependency failure to a warning."""
    return "--allow-missing-deps" in sys.argv


def _bootstrap_requested() -> bool:
    """--bootstrap installs any missing build dependencies instead of failing."""
    return "--bootstrap" in sys.argv


def _positional_version():
    """The version argument, if one was passed. Skips flags (--bootstrap etc.)."""
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    return positional[0].strip() if positional and positional[0].strip() else ""


def _probe_dependencies(pure, win32):
    """
    Try to import every build dependency, reporting each as it goes.

    Returns the list of modules that could not be imported.
    """
    missing = []
    for label, modules in (("third-party", pure), ("win32", win32)):
        for mod in modules:
            try:
                importlib.import_module(mod)
                print(f"[PREFLIGHT] OK    {label:<12} {mod}")
            except Exception as exc:
                missing.append(mod)
                print(f"[PREFLIGHT] FAIL  {label:<12} {mod}  ({type(exc).__name__}: {exc})")
    return missing


def _install_requirements():
    """
    Install agent/requirements.txt into THIS interpreter.

    Uses sys.executable deliberately: installing into some other Python would
    recreate the exact original bug, where the library is present on the machine
    but absent from the interpreter PyInstaller is launched with.
    """
    requirements = AGENT_DIR / "requirements.txt"
    print()
    print("[BOOTSTRAP] Missing dependencies - installing them now.")
    print(f"[BOOTSTRAP]   \"{sys.executable}\" -m pip install -r \"{requirements}\"")
    print()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        print(f"[BOOTSTRAP] FAIL  could not run pip: {type(exc).__name__}: {exc}")
        return False

    if result.returncode != 0:
        # pip puts the actionable part on stderr. Surface it rather than a bare
        # exit code - network failures and locked-down build agents land here,
        # and both need the actual message to be fixable.
        print(f"[BOOTSTRAP] FAIL  pip exited {result.returncode}")
        for line in (result.stderr or result.stdout or "").strip().split("\n")[-15:]:
            print(f"  {line}")
        return False

    print("[BOOTSTRAP] Install completed.")
    print()
    return True


def _required_deps(imports):
    """
    Split a build's hidden-import list into (pure_python, win32) requirements.

    Driven by what the build actually asked for rather than a fixed list, so
    the swapper — which is built with psutil only and genuinely needs no
    pywin32 — is not failed for not carrying it.
    """
    wanted = list(imports)
    pure = [m for m in AGENT_RUNTIME_DEPS if m in wanted]
    win32 = [m for m in WIN32_RUNTIME_DEPS if m in wanted]
    return pure, win32


def _preflight():
    """
    Verify the building interpreter can import everything the build bundles.

    Aborts before any PyInstaller run, so a missing dependency is a build
    failure rather than a silently under-populated exe.
    """
    imports = get_hidden_imports()
    pure, win32 = _required_deps(imports)

    print("=" * 70)
    print("[PREFLIGHT] Build environment")
    print("=" * 70)
    print(f"[PREFLIGHT] Python : {sys.executable}")
    print(f"[PREFLIGHT] Version: {platform.python_version()}")

    missing = _probe_dependencies(pure, win32)

    # The bundler is part of the toolchain this script provisions, so --bootstrap
    # has to be able to supply it too — otherwise a genuinely fresh interpreter
    # cannot be bootstrapped at all, since pyinstaller is what does the bundling.
    try:
        importlib.import_module("PyInstaller")
        print("[PREFLIGHT] OK    tool         PyInstaller")
    except Exception as exc:
        missing.append("PyInstaller")
        print(f"[PREFLIGHT] FAIL  tool         PyInstaller  ({type(exc).__name__}: {exc})")

    # Only install when something is genuinely missing, so the common case on a
    # prepared machine stays a fast no-op.
    if missing and _bootstrap_requested() and not _allow_missing_deps():
        if _install_requirements():
            global _BOOTSTRAPPED
            _BOOTSTRAPPED = True
            print("[PREFLIGHT] Installed. Restarting this build in a fresh")
            print("[PREFLIGHT] interpreter so the new packages are importable:")
            print()
            print("[PREFLIGHT]   (pywin32 registers its DLL directory through a")
            print("[PREFLIGHT]    .pth file that Python only processes at startup,")
            print("[PREFLIGHT]    so re-checking in this process would report a")
            print("[PREFLIGHT]    false failure.)")
            print()

    if missing:
        if _BOOTSTRAPPED:
            # The install succeeded; main() re-runs this whole check in a fresh
            # interpreter. Reporting the pre-install state here would abort a
            # bootstrap that in fact worked.
            return True

        message = (
            f"{len(missing)} required dependenc"
            f"{'y is' if len(missing) == 1 else 'ies are'} missing: "
            + ", ".join(missing)
        )
        if _allow_missing_deps():
            print(f"[PREFLIGHT] [WARN] {message} — continuing (--allow-missing-deps)")
            return True
        print()
        print("[ERROR] Cannot build a working agent without these libraries.")
        print("[ERROR] A build that omits them ships an exe that logs")
        print("[ERROR]   'pywin32 not available' / 'psutil not available' on")
        print("[ERROR]   every endpoint, while still reporting BUILD SUCCESSFUL.")
        print()
        print("[FIX] Either run this yourself:")
        print(f'  "{sys.executable}" -m pip install -r "{AGENT_DIR / "requirements.txt"}"')
        print()
        print("[FIX] Or let the builder do it for you:")
        version_arg = f" {_positional_version()}" if _positional_version() else ""
        print(f'  "{sys.executable}" build_exe.py{version_arg} --bootstrap')
        print()
        print("[NOTE] --allow-missing-deps bypasses this check if a partial build")
        print("       is genuinely intended.")
        return False

    print("[PREFLIGHT] All build dependencies present.")
    print()
    return True


def _reexec_after_bootstrap():
    """
    Re-run this build script in a fresh interpreter, then exit with its status.

    pywin32 makes itself importable via a .pth file that site.py processes only
    at interpreter startup, and pip cannot activate it for an already-running
    process. Without this restart --bootstrap would install correctly and then
    still report every pywin32 module missing, leaving the caller stuck
    re-running a command that had already succeeded.

    Guarded by BOOTSTRAP_ENV so a genuine problem reports one clear failure
    rather than looping forever.
    """
    if os.environ.get(BOOTSTRAP_ENV):
        print()
        print("[ERROR] Dependencies are still not importable after a restart.")
        print("[ERROR] Check the earlier [BOOTSTRAP] output for the pip failure.")
        print(f'[ERROR] Or install manually: "{sys.executable}" -m pip install '
              f'-r "{AGENT_DIR / "requirements.txt"}"')
        sys.exit(1)

    env = dict(os.environ)
    env[BOOTSTRAP_ENV] = "1"
    command = [sys.executable, str(Path(__file__).resolve())] + sys.argv[1:]
    print(f"[BOOTSTRAP] Restarting: {' '.join(command)}")
    print()
    sys.exit(subprocess.run(command, env=env).returncode)


def _collect_bundle_names(exe_path):
    """
    Every module and extension name present inside a PyInstaller onefile exe.

    PyInstaller splits a bundle in two: native extensions and DLLs land in the
    outer archive as .pyd/.dll entries, while pure-Python modules are compiled
    into a single PYZ archive. psutil and pywin32 straddle both, so checking
    only one of them gives a false negative — and a false "all clear".

    This import is build-time only and is suppressed from the type checker:
    PyInstaller is a build dependency (agent/requirements.txt:17), not an agent
    runtime dependency, so it is legitimately absent from whatever interpreter
    an editor or linter happens to resolve against. main() has already proven
    PyInstaller is importable before any build runs, so by the time this is
    called the import cannot fail — and _verify_exe() reports it clearly if it
    somehow does.
    """
    # pyrefly: ignore[missing-import]
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    names = set()
    outer = CArchiveReader(str(exe_path))

    for key in outer.toc:
        normalized = key.replace("\\", "/")
        stem = os.path.splitext(normalized)[0]
        names.add(stem)
        names.add(os.path.basename(stem))

    pyz_key = next((k for k in outer.toc if k.startswith("PYZ")), None)
    if pyz_key:
        payload = outer.extract(pyz_key)
        if not isinstance(payload, bytes):
            payload = payload[1]
        tmp_path = os.path.join(tempfile.gettempdir(), "_build_exe_verify.pyz")
        with open(tmp_path, "wb") as handle:
            handle.write(payload)
        try:
            names.update(ZlibArchiveReader(tmp_path).toc.keys())
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return names


def _module_in_bundle(module, names):
    """
    Match a dotted module name against collected bundle names.

    Handles the three shapes a dependency can take: a plain PYZ entry
    ("psutil"), a native extension under a package dir ("psutil/_psutil_windows"
    → psutil), and pywin32's pure-Python modules, which live under the
    "win32.lib." prefix ("win32.lib.winerror" → winerror).
    """
    for name in names:
        dotted = name.replace("/", ".")
        if dotted == module:
            return True
        if dotted.startswith(module + "."):
            return True
        if dotted.endswith("." + module):
            return True
    return False


def _verify_exe(exe_path, imports):
    """
    Confirm the finished exe actually carries the dependencies it needs.

    This is the check that was missing. Preflight can only prove the library is
    installed on the build machine; only the shipped binary proves it is
    installed on the endpoint.
    """
    exe_path = Path(exe_path)
    print("=" * 70)
    print(f"[VERIFY] {exe_path.name}")
    print("=" * 70)

    if not exe_path.exists():
        print(f"[VERIFY] FAIL  binary not produced at {exe_path}")
        return False

    try:
        names = _collect_bundle_names(exe_path)
    except ImportError as exc:
        # Distinct from a corrupt bundle: PyInstaller itself is unreachable.
        # main() guards against this, so reaching here means build_exe.py was
        # imported and called directly rather than run as a script.
        print(f"[VERIFY] FAIL  PyInstaller is not importable, so the binary "
              f"cannot be inspected: {exc}")
        print(f"[VERIFY]       Run: \"{sys.executable}\" -m pip install -r "
              f"\"{AGENT_DIR / 'requirements.txt'}\"")
        return False
    except Exception as exc:
        print(f"[VERIFY] FAIL  could not read the bundle: {type(exc).__name__}: {exc}")
        return False

    pure, win32 = _required_deps(imports)

    missing = []
    for mod in pure + win32:
        if _module_in_bundle(mod, names):
            print(f"[VERIFY] OK    module  {mod}")
        else:
            missing.append(mod)
            print(f"[VERIFY] FAIL  module  {mod}  (not present in the binary)")

    if win32:
        for dll in WIN32_REQUIRED_DLLS:
            found = any(
                os.path.basename(name).lower().startswith(dll) for name in names
            )
            if found:
                versioned = next(
                    (
                        os.path.basename(name)
                        for name in sorted(names)
                        if os.path.basename(name).lower().startswith(dll)
                    ),
                    dll,
                )
                print(f"[VERIFY] OK    dll     {dll}  ({versioned})")
            else:
                missing.append(dll)
                print(f"[VERIFY] FAIL  dll     {dll}  (not present in the binary)")

    if missing:
        print()
        print(f"[VERIFY] FAIL  {len(missing)} dependenc"
              f"{'y' if len(missing) == 1 else 'ies'} missing from {exe_path.name}: "
              + ", ".join(missing))
        if _allow_missing_deps():
            print("[VERIFY] [WARN] continuing (--allow-missing-deps)")
            return True
        print("[VERIFY] This exe would log 'not available' warnings on every")
        print("[VERIFY] endpoint. Not shipping it.")
        return False

    print(f"[VERIFY] All {len(pure) + len(win32)} dependencies present in {exe_path.name}.")
    print()
    return True


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

    combined = (result.stdout + result.stderr)

    if result.returncode != 0:
        print(f"[FAIL] Failed to build {exe_name}.exe")
        # Show last 50 lines of output for debugging
        lines = combined.strip().split("\n")
        for line in lines[-50:]:
            print(f"  {line}")
        return False

    exe_path = DIST_DIR / f"{exe_name}.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"[OK] {exe_name}.exe built ({size_mb:.1f} MB)")
    else:
        print(f"[FAIL] {exe_name}.exe was not produced")
        return False

    # A build that succeeds is not the same as a build that works. PyInstaller
    # only warns when a --hidden-import cannot be resolved, and that warning
    # used to be discarded with the rest of the captured output, so an exe
    # missing its dependencies still reported success. Surface it explicitly
    # rather than relying on PyInstaller staying quiet.
    #
    # Matched against PyInstaller's own wording only ("Hidden import "x" not
    # found!"). A looser match on "hidden import" also catches the INFO line it
    # prints for every import it analyses, which is noise, not a finding.
    unresolved = [line.strip() for line in combined.split("\n")
                  if "hidden import" in line.lower() and "not found" in line.lower()]
    if unresolved:
        print(f"[WARN] PyInstaller reported {len(unresolved)} unresolved import(s):")
        for line in unresolved[:10]:
            print(f"  {line}")

    return _verify_exe(exe_path, imports_to_use)


def main():
    print("=" * 70)
    print("  SentinelEdge Agent - EXE Builder (Stealth Edition)")
    print("=" * 70)

    os.chdir(AGENT_DIR)

    # Verify the build environment before touching PyInstaller. Running this
    # first means a machine missing a dependency fails immediately with an
    # actionable message, rather than producing an under-populated exe that
    # reports success and fails on every endpoint at runtime.
    #
    # Deliberately ahead of the PyInstaller check below: pyinstaller is itself in
    # requirements.txt, so on a genuinely fresh interpreter the earlier check
    # would exit before --bootstrap ever got the chance to supply it.
    if not _preflight():
        sys.exit(1)

    if _BOOTSTRAPPED:
        _reexec_after_bootstrap()

    # Now that the environment is known good, confirm the bundler is present.
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[ERROR] PyInstaller is not installed in this interpreter:")
        print(f'[ERROR]   "{sys.executable}"')
        print(f'[ERROR] Install it, or rebuild with --bootstrap:')
        print(f'[ERROR]   "{sys.executable}" build_exe.py'
              f'{" " + _positional_version() if _positional_version() else ""} --bootstrap')
        sys.exit(1)

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
