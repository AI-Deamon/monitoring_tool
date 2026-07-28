#!/usr/bin/env python3
"""
One-command agent release.

Replaces the manual sequence of: bump VERSION.txt by hand -> run
build_exe.py -> run build_package.bat -> run create_update_package.py with
the right flags -> copy the zip into the folder the server actually serves.

Usage:
    python release_agent.py 4.2.0 --changelog "Stop retrying rejected telemetry"
    python release_agent.py 4.2.0 --dry-run          # show the plan, touch nothing
    python release_agent.py 4.2.0 --skip-build       # republish the current dist/

What it does:
    1. Preflight  - version format, signing key, PyInstaller, clean agent/ tree
    2. Sync       - VERSION.txt + __version__ markers (sync_release_version.py)
    3. Build      - windiag.exe / syshealth.exe / tools/swapper.exe
    4. Stage      - copy install_exe.bat + nssm/ into dist/ for the installer zip
    5. Publish    - update package -> server/updates/ (the dir the server serves)
    6. Installer  - fresh-install zip for new machines
    7. Verify     - re-read what was written and prove it is consistent

Artifacts land in release/<version>/, and the update package is also copied
into server/updates/ where /api/v1/updates/latest serves it from.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
AGENT_DIR = ROOT / "agent"
DIST_DIR = AGENT_DIR / "dist"
SERVER_DIR = ROOT / "server"
# The folder server_updates.py actually serves from (UPDATES_DIR default).
# create_update_package.py's own default resolves to server/scripts/updates/,
# which the server never reads - always pass this explicitly.
SERVER_UPDATES_DIR = SERVER_DIR / "updates"
RELEASE_ROOT = ROOT / "release"
PACKAGER = SERVER_DIR / "scripts" / "admin" / "create_update_package.py"
VERSION_SYNC = ROOT / "sync_release_version.py"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
REQUIRED_EXES = ("windiag.exe", "syshealth.exe", Path("tools") / "swapper.exe")


class ReleaseError(RuntimeError):
    """A step failed in a way that should stop the release."""


def log(step: str, msg: str) -> None:
    print(f"[{step}] {msg}")


def fail(msg: str) -> NoReturn:
    raise ReleaseError(msg)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_signing_key() -> str:
    """UPDATE_SIGNING_KEY from the environment, falling back to server/.env."""
    import os

    key = os.environ.get("UPDATE_SIGNING_KEY", "").strip()
    if key:
        return key

    env_file = SERVER_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("UPDATE_SIGNING_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_packager():
    """Import create_update_package.py by path so we reuse its zip/sign logic."""
    if not PACKAGER.exists():
        fail(f"Packager not found: {PACKAGER}")
    spec = importlib.util.spec_from_file_location("create_update_package", PACKAGER)
    if spec is None or spec.loader is None:
        fail(f"Could not load packager: {PACKAGER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def published_versions() -> set[str]:
    found = set()
    for zip_path in SERVER_UPDATES_DIR.glob("sentineledge-agent-*.zip"):
        match = re.match(r"sentineledge-agent-(.+)\.zip$", zip_path.name)
        if match:
            found.add(match.group(1))
    return found


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_preflight(version: str, skip_build: bool, force: bool) -> str:
    log("1/7", "Preflight")

    if not VERSION_RE.match(version):
        fail(f"Version must be x.y.z (got {version!r})")

    already = published_versions()
    if version in already and not force:
        fail(
            f"{version} is already published in {SERVER_UPDATES_DIR}. "
            f"Use --force to overwrite it."
        )

    signing_key = read_signing_key()
    if signing_key:
        log("1/7", f"  UPDATE_SIGNING_KEY found (len={len(signing_key)})")
    else:
        log("1/7", "  WARNING: no UPDATE_SIGNING_KEY - package will be UNSIGNED")

    if not skip_build:
        probe = subprocess.run(
            [sys.executable, "-c", "import PyInstaller; print(PyInstaller.__version__)"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            fail(
                "PyInstaller is not available to "
                f"{sys.executable}.\n  Install it with: "
                f'"{sys.executable}" -m pip install pyinstaller'
            )
        log("1/7", f"  PyInstaller {probe.stdout.strip()}")

    # The build compiles the working tree, so uncommitted agent code ships.
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "agent"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    changed = [ln for ln in dirty.stdout.splitlines() if ln.strip()]
    if changed:
        log("1/7", f"  WARNING: {len(changed)} uncommitted change(s) under agent/ will ship:")
        for line in changed[:10]:
            log("1/7", f"    {line}")
        if len(changed) > 10:
            log("1/7", f"    ... and {len(changed) - 10} more")
    else:
        log("1/7", "  agent/ tree is clean")

    log("1/7", f"  Releasing {version}")
    return signing_key


def step_sync_version(version: str) -> None:
    log("2/7", f"Syncing version metadata to {version}")
    if not VERSION_SYNC.exists():
        fail(f"Missing {VERSION_SYNC}")
    result = subprocess.run(
        [sys.executable, str(VERSION_SYNC), "--version", version],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"Version sync failed:\n{result.stdout}\n{result.stderr}")
    for line in result.stdout.splitlines():
        if line.startswith(("[OK]", "[WARN]", "  - ")):
            log("2/7", f"  {line}")


def step_build(version: str) -> None:
    log("3/7", "Building executables (PyInstaller, takes a few minutes)")
    result = subprocess.run(
        [sys.executable, "build_exe.py", version],
        cwd=AGENT_DIR,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        fail("build_exe.py failed - see output above")

    missing = [str(rel) for rel in REQUIRED_EXES if not (DIST_DIR / rel).exists()]
    if missing:
        fail(f"Build did not produce: {', '.join(missing)}")
    log("3/7", "  Built windiag.exe, syshealth.exe, tools/swapper.exe")


def step_strip_installer_files() -> None:
    """Keep installer-only payload out of the auto-update package.

    The packager globs *.exe recursively from dist/, so anything staged for
    the installer would ride along into the update zip. nssm.exe especially
    must not: it is the service wrapper hosting windiag.exe, and having the
    swapper overwrite it in place during an update is asking for a bricked
    service. Runs before packaging so reruns with --skip-build are safe.
    """
    log("4/7", "Excluding installer-only files from the update payload")

    nssm_dst = DIST_DIR / "nssm"
    if nssm_dst.exists():
        shutil.rmtree(nssm_dst)
        log("4/7", "  removed dist/nssm/")
    stray_installer = DIST_DIR / "install_exe.bat"
    if stray_installer.exists():
        stray_installer.unlink()
        log("4/7", "  removed dist/install_exe.bat")
    log("4/7", "  update payload is windiag.exe + syshealth.exe + tools/swapper.exe")


def step_stage_installer_files() -> None:
    """build_exe.py wipes dist/, so restore the installer-only payload.

    Runs *after* the update package is built (see step_strip_installer_files).
    """
    log("6/7", "Staging installer files into dist/")

    installer = AGENT_DIR / "install_exe.bat"
    if not installer.exists():
        fail(f"Missing {installer}")
    shutil.copy2(installer, DIST_DIR / "install_exe.bat")
    log("6/7", "  install_exe.bat")

    nssm_src = AGENT_DIR / "nssm"
    if not nssm_src.is_dir():
        fail(f"Missing {nssm_src}")
    nssm_dst = DIST_DIR / "nssm"
    if nssm_dst.exists():
        shutil.rmtree(nssm_dst)
    shutil.copytree(nssm_src, nssm_dst)
    log("6/7", "  nssm/win32 + nssm/win64")


def step_publish(version: str, signing_key: str, min_version: str,
                 changelog: str, mandatory: bool) -> dict:
    log("5/7", f"Publishing update package to {SERVER_UPDATES_DIR}")
    packager = load_packager()
    latest = packager.create_package(
        source_dir=DIST_DIR,
        version=version,
        output_dir=SERVER_UPDATES_DIR,
        signing_key=signing_key,
        min_version=min_version,
        changelog=changelog or f"Agent version {version}",
        mandatory=mandatory,
        exe_mode=True,
    )

    release_dir = RELEASE_ROOT / version
    release_dir.mkdir(parents=True, exist_ok=True)
    published = SERVER_UPDATES_DIR / f"sentineledge-agent-{version}.zip"
    shutil.copy2(published, release_dir / published.name)
    shutil.copy2(SERVER_UPDATES_DIR / "latest.json", release_dir / "latest.json")
    log("5/7", f"  Copied to {release_dir}")
    return latest


def step_installer_zip(version: str) -> Path:
    log("6/7", "Building fresh-install package")
    release_dir = RELEASE_ROOT / version
    release_dir.mkdir(parents=True, exist_ok=True)
    out = release_dir / f"SentinelEdge-Agent-{version}-installer.zip"
    if out.exists():
        out.unlink()

    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(DIST_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, str(Path("dist") / path.relative_to(DIST_DIR)))
                count += 1
    log("6/7", f"  {out.name} ({count} files, {out.stat().st_size:,} bytes)")
    return out


def step_verify(version: str, latest: dict, installer_zip: Path) -> None:
    log("7/7", "Verifying published artifacts")

    published = SERVER_UPDATES_DIR / f"sentineledge-agent-{version}.zip"
    if not published.exists():
        fail(f"Published package missing: {published}")

    actual_sha = sha256_of(published)
    if actual_sha != latest["package_sha256"]:
        fail(
            "SHA256 mismatch between package and latest.json\n"
            f"  package:     {actual_sha}\n"
            f"  latest.json: {latest['package_sha256']}"
        )
    log("7/7", f"  SHA256 matches latest.json ({actual_sha[:16]}...)")

    actual_size = published.stat().st_size
    if actual_size != latest["package_size"]:
        fail(f"Size mismatch: package {actual_size} vs latest.json {latest['package_size']}")
    log("7/7", f"  Size matches ({actual_size:,} bytes)")

    on_disk = json.loads((SERVER_UPDATES_DIR / "latest.json").read_text(encoding="utf-8"))
    if on_disk.get("version") != version:
        fail(f"latest.json says version {on_disk.get('version')!r}, expected {version!r}")
    log("7/7", f"  latest.json version = {version}")

    if not on_disk.get("signature"):
        log("7/7", "  WARNING: latest.json signature is empty (unsigned release)")
    else:
        log("7/7", "  latest.json is signed")

    with zipfile.ZipFile(published) as zf:
        names = set(zf.namelist())
        for rel in REQUIRED_EXES:
            arc = str(rel).replace("\\", "/")
            if arc not in names:
                fail(f"Update package is missing {arc}")

        # The swapper replaces these in place on a live install. nssm.exe is
        # the service wrapper currently hosting windiag.exe, and the installer
        # batch file has no business in an update, so neither may ship here.
        forbidden = sorted(
            n for n in names
            if n.startswith("nssm/") or n.endswith("install_exe.bat")
        )
        if forbidden:
            fail(
                "Update package contains installer-only files that the swapper "
                "must never overwrite in place: " + ", ".join(forbidden)
            )

        meta = json.loads(zf.read("version.json"))
        if meta.get("version") != version:
            fail(f"version.json inside package says {meta.get('version')!r}")
    log("7/7", "  Package holds only the 3 executables + matching version.json")

    with zipfile.ZipFile(installer_zip) as zf:
        names = set(zf.namelist())
        for required in ("dist/install_exe.bat", "dist/VERSION.txt",
                         "dist/nssm/win64/nssm.exe", "dist/windiag.exe"):
            if required not in names:
                fail(f"Installer zip is missing {required}")
        version_txt = zf.read("dist/VERSION.txt").decode("utf-8", "replace")
    if f"Version: {version}" not in version_txt:
        fail(f"Installer VERSION.txt does not report {version}:\n{version_txt}")
    log("7/7", f"  Installer zip is complete and reports {version}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, package and publish an agent release in one command."
    )
    parser.add_argument("version", help="Release version (x.y.z)")
    parser.add_argument("--changelog", default="", help="Changelog text for this version")
    parser.add_argument("--min-version", default="2.0.0",
                        help="Minimum agent version that may take this update")
    parser.add_argument("--mandatory", action="store_true",
                        help="Mark the update as mandatory")
    parser.add_argument("--skip-build", action="store_true",
                        help="Reuse the existing dist/ instead of rebuilding")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an already-published version")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan and exit without changing anything")
    args = parser.parse_args()

    version = args.version.strip()

    if args.dry_run:
        print(f"Would release agent {version}:")
        print(f"  1. sync VERSION.txt + __version__ markers -> {version}")
        print(f"  2. {'SKIP build' if args.skip_build else 'build windiag/syshealth/swapper exes'}")
        print(f"  3. stage install_exe.bat + nssm/ into {DIST_DIR}")
        print(f"  4. publish sentineledge-agent-{version}.zip -> {SERVER_UPDATES_DIR}")
        print(f"  5. write installer zip -> {RELEASE_ROOT / version}")
        print(f"  6. verify checksums, signature and package contents")
        print(f"  signing key: {'present' if read_signing_key() else 'MISSING (unsigned)'}")
        already = published_versions()
        print(f"  already published: {', '.join(sorted(already)) or '(none)'}")
        return 0

    try:
        signing_key = step_preflight(version, args.skip_build, args.force)
        step_sync_version(version)
        if args.skip_build:
            log("3/7", "Skipping build (--skip-build), reusing dist/")
            missing = [str(r) for r in REQUIRED_EXES if not (DIST_DIR / r).exists()]
            if missing:
                fail(f"dist/ is missing {', '.join(missing)} - cannot --skip-build")
        else:
            step_build(version)
        step_strip_installer_files()
        latest = step_publish(version, signing_key, args.min_version,
                              args.changelog, args.mandatory)
        step_stage_installer_files()
        installer_zip = step_installer_zip(version)
        step_verify(version, latest, installer_zip)
    except ReleaseError as exc:
        print()
        print("=" * 68)
        print(f"  RELEASE FAILED: {exc}")
        print("=" * 68)
        return 1

    release_dir = RELEASE_ROOT / version
    print()
    print("=" * 68)
    print(f"  RELEASED {version}")
    print("=" * 68)
    print(f"  Update package : {SERVER_UPDATES_DIR / f'sentineledge-agent-{version}.zip'}")
    print(f"  Installer zip  : {release_dir / f'SentinelEdge-Agent-{version}-installer.zip'}")
    print(f"  Metadata       : {SERVER_UPDATES_DIR / 'latest.json'}")
    print()
    print("  Agents pick this up on their next update check. The server's")
    print("  hourly 'Available versions sync' job registers it in update_versions;")
    print("  to publish immediately, restart the server or POST")
    print("  /api/v1/updates/trigger-check as an admin.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
