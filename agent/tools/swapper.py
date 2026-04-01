"""
SentinelEdge EXE Swapper
========================
External detached process that applies EXE bundle updates after core exits.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DEFAULT_DATA_DIR = Path(r"C:\ProgramData\WinDiagSvc")
FALLBACK_LOG_FILE = Path(r"C:\ProgramData\WinDiagSvc\logs\swapper_fallback.log")
STALE_MANIFEST_MINUTES = 30
PARENT_EXIT_TIMEOUT_SECONDS = 60
REPLACE_RETRIES = 3
REPLACE_RETRY_DELAY_SECONDS = 2
SERVICE_START_TIMEOUT_SECONDS = 45
SERVICE_STATE_POLL_SECONDS = 2
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LOGGER = logging.getLogger("swapper")
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


def _ensure_logger_file(log_path: Path) -> None:
    """Attach a file handler once for the given path."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    target = str(log_path.resolve()).lower()
    for handler in LOGGER.handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                if str(Path(handler.baseFilename).resolve()).lower() == target:
                    return
            except Exception:
                continue

    file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [SWAPPER] %(levelname)s %(message)s")
    )
    LOGGER.addHandler(file_handler)


_ensure_logger_file(FALLBACK_LOG_FILE)


def _run_command(command: list[str], timeout: int = 30) -> Tuple[bool, str, str]:
    """Run a command hidden; return (ok, stdout, stderr)."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return False, "", str(exc)


def _get_service_state(service_name: str) -> Optional[str]:
    """Return current SCM state text (RUNNING/STOPPED/START_PENDING/...) or None."""
    ok, out, _ = _run_command(["sc", "query", service_name], timeout=15)
    if not ok and not out:
        return None

    text = out.upper()
    # Example line: "STATE              : 4  RUNNING"
    for state in (
        "RUNNING",
        "START_PENDING",
        "STOP_PENDING",
        "STOPPED",
        "PAUSED",
        "PAUSE_PENDING",
        "CONTINUE_PENDING",
    ):
        if state in text:
            return state
    return None


def _wait_for_service_state(
    service_name: str,
    desired_state: str,
    timeout: int,
    poll_seconds: int = SERVICE_STATE_POLL_SECONDS,
) -> bool:
    """Poll SCM until service reaches desired state."""
    desired = desired_state.upper()
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = _get_service_state(service_name)
        if state == desired:
            return True
        time.sleep(poll_seconds)
    return False


def _write_failed_swap(
    data_dir: Path,
    manifest_path: Path,
    version: str,
    previous_version: str,
    backup_path: str,
    error: str,
) -> None:
    """Persist failed swap artifact for updater gating."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        failed_file = data_dir / "failed_swap.json"
        payload = {
            "version": version,
            "previous_version": previous_version,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
            "backup_path": backup_path,
            "manifest_path": str(manifest_path),
            "reported_to_server": False,
        }
        failed_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        LOGGER.error(f"failed_swap.json written: {failed_file}")
    except Exception as exc:
        LOGGER.error(f"Could not write failed_swap.json: {exc}")


def _parse_created_at(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_manifest(manifest: Dict[str, Any], manifest_path: Path) -> None:
    required = {
        "version",
        "previous_version",
        "zip_path",
        "install_dir",
        "data_dir",
        "backup_dir",
        "pid",
        "service_name",
        "helper_task",
        "created_at",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"Manifest missing required fields: {missing}")

    for key in ("zip_path", "install_dir", "data_dir", "backup_dir"):
        path_value = Path(str(manifest[key]))
        if not path_value.is_absolute():
            raise ValueError(f"Manifest field '{key}' must be absolute path")

    data_dir_path = Path(str(manifest["data_dir"]))
    if not data_dir_path.exists():
        raise ValueError(f"data_dir does not exist: {data_dir_path}")

    created_at = _parse_created_at(str(manifest["created_at"]))
    age = datetime.now(timezone.utc) - created_at
    if age > timedelta(minutes=STALE_MANIFEST_MINUTES):
        raise ValueError(
            f"Manifest is stale ({age.total_seconds():.0f}s old, "
            f"max {STALE_MANIFEST_MINUTES * 60}s): {manifest_path}"
        )


def _wait_for_process_exit(pid: int, timeout: int) -> bool:
    """Wait for process to exit."""
    if pid <= 0:
        return True

    LOGGER.info(f"Waiting for parent PID {pid} to exit (timeout={timeout}s)")

    try:
        import psutil  # type: ignore

        try:
            proc = psutil.Process(pid)
            proc.wait(timeout=timeout)
            LOGGER.info(f"Parent PID {pid} exited")
            return True
        except psutil.NoSuchProcess:
            LOGGER.info(f"Parent PID {pid} already exited")
            return True
        except psutil.TimeoutExpired:
            LOGGER.error(f"Timeout waiting for parent PID {pid}")
            return False
    except Exception:
        started = time.time()
        while time.time() - started < timeout:
            try:
                os.kill(pid, 0)
            except OSError:
                LOGGER.info(f"Parent PID {pid} exited")
                return True
            time.sleep(1)

        LOGGER.error(f"Timeout waiting for parent PID {pid}")
        return False


def _set_helper_task_disabled(task_name: str) -> bool:
    """Disable helper task. Returns True if disable command succeeded."""
    _run_command(["schtasks", "/end", "/tn", task_name], timeout=15)
    ok, _, err = _run_command(
        ["schtasks", "/change", "/tn", task_name, "/disable"], timeout=20
    )
    if ok:
        LOGGER.info(f"Helper task disabled: {task_name}")
    else:
        LOGGER.warning(f"Could not disable helper task {task_name}: {err}")
    return ok


def _set_helper_task_enabled_and_run(task_name: str) -> None:
    ok_enable, _, err_enable = _run_command(
        ["schtasks", "/change", "/tn", task_name, "/enable"], timeout=20
    )
    if ok_enable:
        LOGGER.info(f"Helper task enabled: {task_name}")
    else:
        LOGGER.warning(f"Could not enable helper task {task_name}: {err_enable}")

    ok_run, _, err_run = _run_command(
        ["schtasks", "/run", "/tn", task_name], timeout=20
    )
    if ok_run:
        LOGGER.info(f"Helper task started: {task_name}")
    else:
        LOGGER.warning(f"Could not run helper task {task_name}: {err_run}")


def _restart_service(install_dir: Path, service_name: str, mode: str) -> bool:
    """
    Restart/start service and verify it reaches RUNNING.
    Returns True only if the service is confirmed RUNNING.
    """
    nssm = install_dir / "nssm" / "win64" / "nssm.exe"
    start_requested = False

    if nssm.exists():
        ok, out, err = _run_command([str(nssm), mode, service_name], timeout=45)
        merged = f"{out}\n{err}".upper()
        if ok:
            LOGGER.info(f"Service {mode} requested via NSSM: {service_name}")
            start_requested = True
        elif mode == "start" and "SERVICE_START_PENDING" in merged:
            # NSSM may return non-zero even though start has begun.
            LOGGER.info(
                f"NSSM reported START_PENDING for {service_name}; waiting for RUNNING"
            )
            start_requested = True
        else:
            LOGGER.warning(f"NSSM {mode} failed for {service_name}: {err}")
    else:
        LOGGER.warning("NSSM not found; using net commands")

    if mode == "restart":
        _run_command(["net", "stop", service_name], timeout=45)
        ok, _, err = _run_command(["net", "start", service_name], timeout=45)
        start_requested = start_requested or ok
    else:
        ok, _, err = _run_command(["net", "start", service_name], timeout=45)
        start_requested = start_requested or ok

    if ok:
        LOGGER.info(f"Service {mode} requested via net: {service_name}")
    else:
        LOGGER.warning(f"net {mode} failed for {service_name}: {err}")

    if not start_requested and mode == "start":
        # May still be in-progress despite command status; check SCM state anyway.
        state = _get_service_state(service_name)
        if state in ("START_PENDING", "RUNNING"):
            start_requested = True

    if mode == "start":
        if _wait_for_service_state(
            service_name, "RUNNING", SERVICE_START_TIMEOUT_SECONDS
        ):
            LOGGER.info(f"Service confirmed RUNNING: {service_name}")
            return True
        final_state = _get_service_state(service_name) or "UNKNOWN"
        LOGGER.error(
            f"Service did not reach RUNNING within {SERVICE_START_TIMEOUT_SECONDS}s "
            f"(last_state={final_state})"
        )
        return False

    # For restart mode, validate RUNNING as well.
    if _wait_for_service_state(service_name, "RUNNING", SERVICE_START_TIMEOUT_SECONDS):
        LOGGER.info(f"Service confirmed RUNNING after restart: {service_name}")
        return True

    final_state = _get_service_state(service_name) or "UNKNOWN"
    LOGGER.error(
        f"Service restart did not reach RUNNING within "
        f"{SERVICE_START_TIMEOUT_SECONDS}s (last_state={final_state})"
    )
    return False


def _backup_files(install_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("windiag.exe", "syshealth.exe", "version.json"):
        src = install_dir / filename
        if src.exists():
            shutil.copy2(src, backup_dir / filename)
            LOGGER.info(f"Backed up {filename} -> {backup_dir}")


def _restore_backup(install_dir: Path, backup_dir: Path) -> None:
    for filename in ("windiag.exe", "syshealth.exe", "version.json"):
        src = backup_dir / filename
        if src.exists():
            shutil.copy2(src, install_dir / filename)
            LOGGER.info(f"Restored {filename} from backup")


def _safe_extract(zip_path: Path, staging_dir: Path) -> None:
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.namelist():
            if ".." in member or member.startswith("/") or member.startswith("\\"):
                raise ValueError(f"Suspicious ZIP entry path: {member}")
            archive.extract(member, staging_dir)


def _find_required_file(staging_dir: Path, filename: str) -> Optional[Path]:
    matches = [p for p in staging_dir.rglob(filename) if p.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda p: len(str(p)))
    return matches[0]


def _replace_with_retry(src: Path, dst: Path) -> None:
    last_exc: Optional[Exception] = None
    for attempt in range(1, REPLACE_RETRIES + 1):
        try:
            os.replace(str(src), str(dst))
            LOGGER.info(f"Replaced {dst.name} (attempt {attempt})")
            return
        except PermissionError as exc:
            last_exc = exc
            LOGGER.warning(
                f"PermissionError replacing {dst.name}, attempt {attempt}/{REPLACE_RETRIES}: {exc}"
            )
            if attempt < REPLACE_RETRIES:
                time.sleep(REPLACE_RETRY_DELAY_SECONDS)
        except Exception as exc:
            raise RuntimeError(f"Replace failed for {dst.name}: {exc}") from exc

    raise RuntimeError(f"Replace failed for {dst.name}: {last_exc}")


def _cleanup_path(path: Optional[Path]) -> None:
    if not path:
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)
    except Exception as exc:
        LOGGER.warning(f"Cleanup warning for {path}: {exc}")


def main() -> int:
    if len(sys.argv) < 2:
        LOGGER.error("Usage: swapper.py <manifest_path>")
        return 1

    manifest_path = Path(sys.argv[1])
    data_dir = DEFAULT_DATA_DIR
    install_dir = Path(r"C:\Program Files\WinDiagSvc")
    backup_dir = Path()
    staging_dir: Optional[Path] = None
    helper_task = "SysHealthMon"
    service_name = "WinDiagSvc"
    version = "unknown"
    previous_version = "unknown"
    helper_was_disabled = False
    backup_created = False

    try:
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(manifest, manifest_path)

        version = str(manifest["version"])
        previous_version = str(manifest["previous_version"])
        data_dir = Path(str(manifest["data_dir"]))
        install_dir = Path(str(manifest["install_dir"]))
        backup_dir = Path(str(manifest["backup_dir"]))
        zip_path = Path(str(manifest["zip_path"]))
        helper_task = str(manifest.get("helper_task", "SysHealthMon"))
        service_name = str(manifest.get("service_name", "WinDiagSvc"))
        parent_pid = int(manifest.get("pid", 0))

        _ensure_logger_file(data_dir / "logs" / "swapper.log")

        LOGGER.info("=" * 72)
        LOGGER.info(f"Starting EXE swap {previous_version} -> {version}")
        LOGGER.info(f"Manifest: {manifest_path}")
        LOGGER.info(f"Install dir: {install_dir}")
        LOGGER.info(f"Data dir: {data_dir}")

        if not _wait_for_process_exit(parent_pid, PARENT_EXIT_TIMEOUT_SECONDS):
            LOGGER.warning(
                f"Parent PID {parent_pid} did not exit in "
                f"{PARENT_EXIT_TIMEOUT_SECONDS}s; proceeding with forced stop"
            )

        # Step 1: Stop helper task
        helper_was_disabled = _set_helper_task_disabled(helper_task)

        # Step 2: Stop the core service BEFORE file replacement
        LOGGER.info(f"Stopping core service {service_name} before file swap...")
        nssm = install_dir / "nssm" / "win64" / "nssm.exe"
        if nssm.exists():
            _run_command([str(nssm), "stop", service_name, "60"], timeout=70)
        else:
            _run_command(["net", "stop", service_name], timeout=60)
        time.sleep(3)  # Allow SCM/task scheduler state to settle

        # Kill any stale windiag/syshealth processes
        LOGGER.info("Killing stale processes...")
        _run_command(["taskkill", "/f", "/im", "windiag.exe"], timeout=10)
        _run_command(["taskkill", "/f", "/im", "syshealth.exe"], timeout=10)
        time.sleep(2)

        # Step 3: Now safe to backup and replace files
        _backup_files(install_dir, backup_dir)
        backup_created = True

        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP package not found: {zip_path}")

        staging_dir = data_dir / "updates" / version / "staging_swap"
        _safe_extract(zip_path, staging_dir)
        LOGGER.info(f"Extracted update ZIP to staging: {staging_dir}")

        staged_core = _find_required_file(staging_dir, "windiag.exe")
        staged_helper = _find_required_file(staging_dir, "syshealth.exe")
        if not staged_core or not staged_helper:
            raise RuntimeError(
                "Required EXE files not found in staged ZIP content "
                "(windiag.exe and syshealth.exe)"
            )

        _replace_with_retry(staged_core, install_dir / "windiag.exe")
        _replace_with_retry(staged_helper, install_dir / "syshealth.exe")

        version_data = {
            "version": version,
            "previous_version": previous_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "update_method": "exe_swap",
            "items_updated": ["windiag.exe", "syshealth.exe"],
        }
        (install_dir / "version.json").write_text(
            json.dumps(version_data, indent=2), encoding="utf-8"
        )
        LOGGER.info("version.json updated")

        pending_data = {
            "version": version,
            "previous_version": previous_version,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "backup_path": str(backup_dir),
            "swapper_applied": True,
            "update_method": "exe_swap",
        }
        # Keep this before restart: core reads update_pending.json on startup.
        (data_dir / "update_pending.json").write_text(
            json.dumps(pending_data, indent=2), encoding="utf-8"
        )
        LOGGER.info("update_pending.json written")

        if helper_was_disabled:
            _set_helper_task_enabled_and_run(helper_task)

        _cleanup_path(data_dir / "failed_swap.json")
        # Service was already stopped before file swap, so use "start" not "restart"
        if not _restart_service(install_dir, service_name, mode="start"):
            raise RuntimeError(
                f"Service {service_name} failed to reach RUNNING after swap"
            )

        _cleanup_path(staging_dir)
        _cleanup_path(manifest_path)
        LOGGER.info(f"EXE swap completed successfully: {version}")
        LOGGER.info("=" * 72)
        return 0

    except Exception as exc:
        error_text = str(exc)
        LOGGER.error(f"Swap failed: {error_text}", exc_info=True)
        _write_failed_swap(
            data_dir=data_dir,
            manifest_path=manifest_path,
            version=version,
            previous_version=previous_version,
            backup_path=str(backup_dir) if str(backup_dir) else "",
            error=error_text,
        )

        if backup_created and backup_dir.exists():
            try:
                _restore_backup(install_dir, backup_dir)
            except Exception as rollback_exc:
                LOGGER.error(f"Rollback failed: {rollback_exc}", exc_info=True)

        if helper_was_disabled:
            _set_helper_task_enabled_and_run(helper_task)

        _restart_service(install_dir, service_name, mode="start")
        _cleanup_path(staging_dir)
        LOGGER.info("=" * 72)
        return 1


if __name__ == "__main__":
    sys.exit(main())
