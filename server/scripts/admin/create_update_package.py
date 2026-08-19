"""
SentinelEdge Update Package Creator
=====================================
Admin script to create signed update packages for agent auto-update.

Usage:
    # Python script mode (legacy):
    python create_update_package.py D:\\agent 2.5.0

    # EXE bundle mode (for PyInstaller builds):
    python create_update_package.py D:\\dist 2.5.0 --exe-mode

What it does:
    1. Validates source directory has required files
    2. Creates ZIP with EXE files (--exe-mode) or Python sources
    3. Computes SHA256 of the ZIP
    4. Signs metadata with HMAC-SHA256
    5. Writes latest.json (with artifact_type) + copies ZIP to updates/
"""

import os
import sys
import json
import hmac
import hashlib
import base64
import zipfile
import argparse
import shutil
from pathlib import Path
from datetime import datetime, timezone


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def sign_metadata(metadata: dict, signing_key: str) -> str:
    """Create HMAC-SHA256 signature of version metadata."""
    if not signing_key:
        return ''
    
    signable = {
        'version': metadata.get('version', ''),
        'package_sha256': metadata.get('package_sha256', ''),
        'package_size': metadata.get('package_size', 0),
        'min_agent_version': metadata.get('min_agent_version', '2.0.0'),
        'mandatory': metadata.get('mandatory', False),
    }
    canonical = json.dumps(signable, sort_keys=True, separators=(',', ':'))
    sig = hmac.new(
        signing_key.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(sig).decode('ascii')


#: Payload of an exe_bundle package, relative to the source dir. Anything else
#: found by a recursive glob is NOT shipped: swapper.BACKUP_ITEMS covers exactly
#: these paths, so a stray binary (e.g. nssm/win64/nssm.exe, which sits in
#: agent/dist/) would be installed onto the endpoint and then left behind by a
#: rollback that does not know about it.
EXE_BUNDLE_PAYLOAD = ('windiag.exe', 'syshealth.exe', 'tools/swapper.exe')


def check_binaries_are_current(source_dir: Path, agent_dir: Path,
                               allow_stale: bool = False) -> None:
    """Abort if the binaries predate the agent source they claim to contain.

    A PyInstaller .exe is a frozen snapshot of the source at build time. Nothing
    else in this pipeline binds a version number to binary content: the version
    comes from latest.json and the package's version.json (both supplied by
    hand), the agent reads its running version from version.json on disk rather
    than the compiled __version__, and build_exe.py stamps no commit or source
    hash. So packaging a stale dist/ makes every layer -- agent, server,
    dashboard, update_history -- report a version whose features are absent.

    That is not hypothetical. 4.2.3 was cut from binaries built 2026-08-07 and
    shipped without the battery-health collector and the D22/FR-031 primary-IP
    fix, both written on 2026-08-11/12. The rollout succeeded; the payload was
    five days old.

    Compares each packaged binary's mtime against the newest .py under the
    agent source tree. Cheap, and it catches the whole class.
    """
    if not agent_dir.is_dir():
        print(f"[WARN] Agent source not found at {agent_dir}; skipping staleness check")
        return

    sources = [
        p for p in agent_dir.rglob('*.py')
        if '__pycache__' not in p.parts
        and 'dist' not in p.parts
        and 'build' not in p.parts
    ]
    if not sources:
        print("[WARN] No agent sources found; skipping staleness check")
        return

    newest = max(sources, key=lambda p: p.stat().st_mtime)
    newest_mtime = newest.stat().st_mtime
    print(f"[INFO] Newest agent source: {newest.name} "
          f"({datetime.fromtimestamp(newest_mtime):%Y-%m-%d %H:%M})")

    stale = []
    for rel in EXE_BUNDLE_PAYLOAD:
        binary = source_dir / rel
        if not binary.exists():
            continue
        built = binary.stat().st_mtime
        mark = 'STALE' if built < newest_mtime else 'ok'
        print(f"[INFO]   {rel:<20} built "
              f"{datetime.fromtimestamp(built):%Y-%m-%d %H:%M}  [{mark}]")
        if mark == 'STALE':
            stale.append(rel)

    if not stale:
        return

    message = (
        f"{len(stale)} binary(ies) are OLDER than {newest.name}. They cannot "
        f"contain the latest source changes.\n"
        f"  Rebuild first:  cd agent && python build_exe.py <version>"
    )
    if allow_stale:
        print(f"[WARN] {message}")
        print("[WARN] --allow-stale given; packaging anyway")
        return
    print(f"[ERROR] {message}")
    sys.exit(1)


def create_package(source_dir: Path, version: str, output_dir: Path,
                   signing_key: str = '', min_version: str = '2.0.0',
                   changelog: str = '', mandatory: bool = False,
                   exe_mode: bool = False):
    """Create a signed update package.

    Args:
        exe_mode: If True, package EXE/DLL/PYD files (PyInstaller output).
                  If False, package Python source files (legacy).
    """

    if exe_mode:
        # EXE bundle mode — validate EXE outputs exist
        required_exes = ['windiag.exe', 'syshealth.exe']
        required_nested_files = [Path('tools') / 'swapper.exe']
        found = []
        for exe in required_exes:
            if (source_dir / exe).exists():
                found.append(exe)
        
        if not found:
            # Also accept any .exe file
            found = [f.name for f in source_dir.glob('*.exe')]
        
        if not found:
            print(f"[ERROR] No EXE files found in {source_dir}")
            print(f"  Expected at least: {required_exes}")
            sys.exit(1)

        missing_nested = [
            str(rel_path) for rel_path in required_nested_files
            if not (source_dir / rel_path).exists()
        ]
        if missing_nested:
            print(f"[ERROR] Missing required EXE bundle files in {source_dir}")
            for rel_path in missing_nested:
                print(f"  - {rel_path}")
            sys.exit(1)
        
        print(f"[INFO] EXE bundle mode: found {len(found)} executables")
        artifact_type = 'exe_bundle'
    else:
        # Python source mode (legacy) — validate
        required_files = ['sentinel_core.py', 'sentinel_helper.py']
        required_dirs = ['core', 'helper']
        
        for f in required_files:
            if not (source_dir / f).exists():
                print(f"[ERROR] Required file not found: {source_dir / f}")
                sys.exit(1)
        
        for d in required_dirs:
            if not (source_dir / d).is_dir():
                print(f"[ERROR] Required directory not found: {source_dir / d}")
                sys.exit(1)
        
        artifact_type = 'full_package'
    
    print(f"[INFO] Source validated: {source_dir}")
    print(f"[INFO] Artifact type: {artifact_type}")
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create ZIP
    zip_name = f'sentineledge-agent-{version}.zip'
    zip_path = output_dir / zip_name
    
    # Remove old package if exists
    if zip_path.exists():
        zip_path.unlink()
        print(f"[INFO] Removed old package: {zip_path}")
    
    file_count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        if exe_mode:
            # Explicit allow-list, NOT a recursive glob.
            #
            # rglob('*.exe') over agent/dist also matches nssm/win32/nssm.exe
            # and nssm/win64/nssm.exe. Those would be installed onto the
            # endpoint and then stranded there, because swapper.BACKUP_ITEMS
            # only restores windiag.exe, syshealth.exe, version.json and
            # tools/swapper.exe -- a rollback would not remove them.
            missing = [
                rel for rel in EXE_BUNDLE_PAYLOAD
                if not (source_dir / rel).is_file()
            ]
            if missing:
                print(f"[ERROR] Missing required payload files in {source_dir}:")
                for rel in missing:
                    print(f"  - {rel}")
                sys.exit(1)

            for rel in EXE_BUNDLE_PAYLOAD:
                # Forward slashes: the ZIP spec requires them, and str() of a
                # WindowsPath would emit backslashes.
                zf.write(source_dir / rel, rel)
                file_count += 1
                print(f"  + {rel}")
        else:
            # Package Python source files
            for script in required_files:
                src = source_dir / script
                zf.write(src, script)
                file_count += 1
                print(f"  + {script}")
            
            # Add core/ and helper/ directories
            for dir_name in required_dirs:
                dir_path = source_dir / dir_name
                for root, dirs, files in os.walk(dir_path):
                    # Skip __pycache__
                    dirs[:] = [d for d in dirs if d != '__pycache__']
                    
                    for filename in files:
                        # Skip .pyc, .pyo files — agent compiles on install
                        if filename.endswith(('.pyc', '.pyo')):
                            continue
                        
                        file_path = Path(root) / filename
                        arcname = file_path.relative_to(source_dir)
                        zf.write(file_path, arcname)
                        file_count += 1
        
        # Add version.json inside the package
        version_meta = {
            'version': version,
            'build_date': datetime.now(timezone.utc).isoformat(),
            'file_count': file_count,
            'artifact_type': artifact_type,
        }
        zf.writestr('version.json', json.dumps(version_meta, indent=2))
        file_count += 1
    
    print(f"[OK] Created {zip_name} ({file_count} files)")
    
    # Compute SHA256
    package_sha256 = compute_sha256(zip_path)
    package_size = zip_path.stat().st_size
    print(f"[OK] SHA256: {package_sha256}")
    print(f"[OK] Size: {package_size:,} bytes")
    
    # Create latest.json
    latest = {
        'version': version,
        'release_date': datetime.now(timezone.utc).isoformat(),
        'min_agent_version': min_version,
        'package_sha256': package_sha256,
        'package_size': package_size,
        'changelog': changelog or f'Agent version {version}',
        'mandatory': mandatory,
        'artifact_type': artifact_type,
    }
    
    # Sign
    if signing_key:
        latest['signature'] = sign_metadata(latest, signing_key)
        print(f"[OK] Signed with HMAC-SHA256")
    else:
        latest['signature'] = ''
        print(f"[WARN] No signing key — package is unsigned")
    
    # Write latest.json
    latest_path = output_dir / 'latest.json'
    latest_path.write_text(json.dumps(latest, indent=2))
    print(f"[OK] Written: {latest_path}")
    
    # Summary
    print()
    print("=" * 60)
    print(f"  Package: {zip_path}")
    print(f"  Version: {version}")
    print(f"  Type:    {artifact_type}")
    print(f"  SHA256:  {package_sha256}")
    print(f"  Size:    {package_size:,} bytes")
    print(f"  Files:   {file_count}")
    print(f"  Signed:  {'Yes' if signing_key else 'No'}")
    print("=" * 60)
    print()
    print("To deploy: copy this updates/ directory to your server")
    print("Agents will pick up the update on next check cycle")
    
    return latest


def main():
    parser = argparse.ArgumentParser(
        description='Create SentinelEdge agent update package'
    )
    parser.add_argument(
        'source_dir',
        help='Path to agent source directory (contains sentinel_core.py)'
    )
    parser.add_argument(
        'version',
        help='Version string (e.g., 2.5.0)'
    )
    parser.add_argument(
        '--signing-key',
        default=os.environ.get('UPDATE_SIGNING_KEY', ''),
        help='HMAC signing key (or set UPDATE_SIGNING_KEY env var)'
    )
    parser.add_argument(
        '--output-dir',
        default=None,
        help='Output directory (default: <server>/updates/)'
    )
    parser.add_argument(
        '--min-version',
        default='2.0.0',
        help='Minimum agent version compatible (default: 2.0.0)'
    )
    parser.add_argument(
        '--changelog',
        default='',
        help='Changelog text for this version'
    )
    parser.add_argument(
        '--mandatory',
        action='store_true',
        help='Mark update as mandatory'
    )
    parser.add_argument(
        '--exe-mode',
        action='store_true',
        help='Package EXE files (PyInstaller output) instead of Python sources'
    )
    parser.add_argument(
        '--allow-stale',
        action='store_true',
        help='Package even if the binaries are older than the agent source. '
             'Only for reproducing a historical build - a stale package ships '
             'a version number whose features are not in it.'
    )
    
    args = parser.parse_args()
    
    source_dir = Path(args.source_dir).resolve()
    
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    else:
        # server/updates/ -- the directory server_updates.py actually serves
        # from (UPDATES_DIR = Path(server_updates.__file__).parent / 'updates').
        #
        # This used to resolve to server/scripts/updates/, one level short,
        # which nothing reads. Packages published there were invisible to every
        # agent while appearing to have been deployed successfully.
        output_dir = Path(__file__).resolve().parents[2] / 'updates'

    # scripts/admin -> scripts -> server -> agent
    agent_dir = Path(__file__).resolve().parents[3] / 'agent'
    if args.exe_mode:
        check_binaries_are_current(source_dir, agent_dir, args.allow_stale)
    
    create_package(
        source_dir=source_dir,
        version=args.version,
        output_dir=output_dir,
        signing_key=args.signing_key,
        min_version=args.min_version,
        changelog=args.changelog,
        mandatory=args.mandatory,
        exe_mode=args.exe_mode,
    )


if __name__ == '__main__':
    main()
