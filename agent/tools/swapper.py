"""
SentinelEdge EXE Swapper
========================
External process that replaces locked EXE files while the main service is stopped.

Usage:
    swapper.py <manifest_path>

Flow:
    1. Read swap_manifest.json (written by AgentUpdater)
    2. Wait for the main WinDiagSvc process (PID) to exit
    3. Backup current EXE files
    4. Extract new EXE files from ZIP
    5. Write updated version.json
    6. Restart the service via NSSM or net start

This script is designed to be launched as a DETACHED_PROCESS by updater.py
so it survives the parent process exiting.
"""

import os
import sys
import json
import time
import shutil
import zipfile
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# Configure logging to file (since we have no console)
log_dir = Path(os.environ.get(
    'SENTINELEDGE_DATA_DIR',
    r'C:\ProgramData\SentinelEdge'
))
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(log_dir / 'swapper.log'),
    level=logging.INFO,
    format='%(asctime)s [SWAPPER] %(levelname)s %(message)s',
)
logger = logging.getLogger('swapper')


def wait_for_process_exit(pid: int, timeout: int = 120) -> bool:
    """Wait for a process to exit, with timeout."""
    logger.info(f"Waiting for PID {pid} to exit (timeout={timeout}s)...")

    try:
        import psutil
        try:
            proc = psutil.Process(pid)
            proc.wait(timeout=timeout)
            logger.info(f"PID {pid} exited")
            return True
        except psutil.NoSuchProcess:
            logger.info(f"PID {pid} already gone")
            return True
        except psutil.TimeoutExpired:
            logger.error(f"PID {pid} did not exit within {timeout}s")
            return False
    except ImportError:
        # Fallback without psutil: poll /proc or just wait
        start = time.time()
        while time.time() - start < timeout:
            try:
                os.kill(pid, 0)  # Check if process exists
                time.sleep(2)
            except OSError:
                logger.info(f"PID {pid} exited (os.kill check)")
                return True
        logger.error(f"PID {pid} did not exit within {timeout}s (no psutil)")
        return False


def stop_service(service_name: str) -> bool:
    """Stop the Windows service."""
    try:
        result = subprocess.run(
            ['net', 'stop', service_name],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0 or 'not started' in result.stderr.lower():
            logger.info(f"Service '{service_name}' stopped")
            return True
        logger.warning(f"Stop service output: {result.stderr}")
        return True  # Proceed anyway
    except Exception as e:
        logger.error(f"Failed to stop service: {e}")
        return True  # Proceed anyway


def start_service(service_name: str, install_dir: str) -> bool:
    """Start the Windows service via NSSM or net start."""
    try:
        nssm = Path(install_dir) / 'nssm' / 'win64' / 'nssm.exe'
        if nssm.exists():
            subprocess.run(
                [str(nssm), 'start', service_name],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            logger.info(f"Service '{service_name}' started via NSSM")
        else:
            subprocess.run(
                ['net', 'start', service_name],
                capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            logger.info(f"Service '{service_name}' started via net")
        return True
    except Exception as e:
        logger.error(f"Failed to start service: {e}")
        return False


def backup_exe_files(install_dir: Path, backup_dir: Path) -> bool:
    """Backup current EXE files before replacement."""
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)

        for item in install_dir.iterdir():
            if item.suffix.lower() in ('.exe', '.dll', '.pyd'):
                shutil.copy2(item, backup_dir / item.name)
                logger.info(f"Backed up: {item.name}")

        # Also backup version.json
        version_file = install_dir / 'version.json'
        if version_file.exists():
            shutil.copy2(version_file, backup_dir / 'version.json')

        logger.info(f"Backup complete: {backup_dir}")
        return True
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return False


def extract_exe_files(zip_path: Path, install_dir: Path) -> list:
    """Extract EXE/DLL files from update ZIP to install directory."""
    extracted = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for name in zf.namelist():
                # Security: no path traversal
                if '..' in name or name.startswith('/'):
                    logger.warning(f"Skipping suspicious path: {name}")
                    continue

                # Extract .exe, .dll, .pyd files to install dir root
                basename = Path(name).name
                if basename.lower().endswith(('.exe', '.dll', '.pyd')):
                    target = install_dir / basename
                    with zf.open(name) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    extracted.append(basename)
                    logger.info(f"Extracted: {basename}")

                # Extract version.json if present
                if basename == 'version.json':
                    target = install_dir / 'version.json'
                    with zf.open(name) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    extracted.append('version.json')

        logger.info(f"Extracted {len(extracted)} files")
        return extracted
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return []


def rollback(install_dir: Path, backup_dir: Path):
    """Restore backed up files on failure."""
    try:
        for item in backup_dir.iterdir():
            shutil.copy2(item, install_dir / item.name)
        logger.info("Rollback complete")
    except Exception as e:
        logger.error(f"CRITICAL: Rollback failed: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: swapper.py <manifest_path>")
        sys.exit(1)

    manifest_path = Path(sys.argv[1])
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    # Read manifest
    manifest = json.loads(manifest_path.read_text())
    version = manifest['version']
    previous = manifest.get('previous_version', 'unknown')
    zip_path = Path(manifest['zip_path'])
    install_dir = Path(manifest['install_dir'])
    backup_dir = Path(manifest['backup_dir'])
    pid = manifest.get('pid', 0)
    service_name = manifest.get('service_name', 'WinDiagSvc')

    logger.info("=" * 60)
    logger.info(f"EXE Swap: {previous} -> {version}")
    logger.info(f"ZIP: {zip_path}")
    logger.info(f"Install: {install_dir}")
    logger.info("=" * 60)

    # Step 1: Stop service and wait for PID to exit
    stop_service(service_name)

    if pid:
        if not wait_for_process_exit(pid, timeout=120):
            logger.error("Process did not exit — aborting swap")
            start_service(service_name, str(install_dir))
            sys.exit(1)

    # Extra safety wait
    time.sleep(3)

    # Step 2: Backup current EXEs
    if not backup_exe_files(install_dir, backup_dir):
        logger.error("Backup failed — aborting swap")
        start_service(service_name, str(install_dir))
        sys.exit(1)

    # Step 3: Extract new files
    if not zip_path.exists():
        logger.error(f"ZIP not found: {zip_path}")
        start_service(service_name, str(install_dir))
        sys.exit(1)

    extracted = extract_exe_files(zip_path, install_dir)
    if not extracted:
        logger.error("No files extracted — rolling back")
        rollback(install_dir, backup_dir)
        start_service(service_name, str(install_dir))
        sys.exit(1)

    # Step 4: Write version.json if not in ZIP
    version_file = install_dir / 'version.json'
    if 'version.json' not in extracted:
        version_data = {
            'version': version,
            'previous_version': previous,
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'update_method': 'exe_swap',
            'items_updated': extracted,
        }
        version_file.write_text(json.dumps(version_data, indent=2))
        logger.info("Wrote version.json")

    # Step 5: Write pending flag for health check on next startup
    pending_file = Path(manifest.get(
        'data_dir',
        r'C:\ProgramData\SentinelEdge'
    )) / 'update_pending.json'
    pending = {
        'version': version,
        'previous_version': previous,
        'applied_at': datetime.now(timezone.utc).isoformat(),
        'backup_path': str(backup_dir),
        'update_method': 'exe_swap',
    }
    pending_file.write_text(json.dumps(pending, indent=2))

    # Step 6: Clean up manifest and ZIP
    try:
        manifest_path.unlink()
        if zip_path.exists():
            zip_path.unlink()
    except Exception:
        pass

    # Step 7: Start service
    logger.info("Starting service...")
    start_service(service_name, str(install_dir))

    logger.info(f"EXE swap complete: {version}")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
