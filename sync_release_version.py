#!/usr/bin/env python3
"""
Sync release version across agent/server version metadata.

Usage:
  python sync_release_version.py --version 2.8.0
  python sync_release_version.py --version 2.8.0 --min-agent-version 2.2.0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
INIT_VERSION_RE = re.compile(r"(__version__\s*=\s*['\"])([^'\"]+)(['\"])")


def _require_version(name: str, value: str) -> str:
    version = (value or "").strip()
    if not VERSION_RE.match(version):
        raise ValueError(f"{name} must match x.y.z (got: {value!r})")
    return version


def _write_agent_version_txt(path: Path, version: str) -> None:
    content = (
        "SentinelEdge Agent\n"
        f"Version: {version}\n"
        f"Build Date: {datetime.now().strftime('%Y%m%d')}\n"
        "\n"
        "Installation:\n"
        "  1. Extract all files\n"
        "  2. Right-click install.bat, Run as Administrator\n"
        "  3. Enter server URL and registration secret\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _update_latest_json(
    path: Path,
    version: str,
    min_agent_version: str | None,
    changelog: str | None,
    release_date: str | None,
) -> bool:
    if not path.exists():
        return False

    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    data["changelog"] = changelog or f"Agent version {version}"
    if min_agent_version:
        data["min_agent_version"] = min_agent_version
    data["release_date"] = release_date or datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def _update_init_version(path: Path, version: str) -> bool:
    if not path.exists():
        return False

    original = path.read_text(encoding="utf-8")
    updated, count = INIT_VERSION_RE.subn(rf"\g<1>{version}\g<3>", original, count=1)
    if count == 0:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync release version metadata")
    parser.add_argument("--version", required=True, help="Release version (x.y.z)")
    parser.add_argument(
        "--min-agent-version",
        default=None,
        help="Optional min compatible agent version (x.y.z)",
    )
    parser.add_argument(
        "--changelog",
        default=None,
        help="Optional changelog text to store in latest.json",
    )
    parser.add_argument(
        "--release-date",
        default=None,
        help="Optional ISO8601 release_date for latest.json",
    )
    args = parser.parse_args()

    try:
        version = _require_version("version", args.version)
        min_version = (
            _require_version("min-agent-version", args.min_agent_version)
            if args.min_agent_version
            else None
        )
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return 2

    root = Path(__file__).resolve().parent
    changed: list[str] = []
    warnings: list[str] = []

    # Agent version markers used by build/installer.
    for marker in (root / "agent" / "VERSION.txt", root / "agent" / "dist" / "VERSION.txt"):
        _write_agent_version_txt(marker, version)
        changed.append(str(marker))

    # Server update metadata files.
    for latest_path in (
        root / "server" / "updates" / "latest.json",
        root / "server" / "scripts" / "updates" / "latest.json",
    ):
        try:
            if _update_latest_json(
                latest_path,
                version,
                min_version,
                args.changelog,
                args.release_date,
            ):
                changed.append(str(latest_path))
            else:
                warnings.append(f"Missing file: {latest_path}")
        except Exception as exc:
            warnings.append(f"Failed to update {latest_path}: {exc}")

    # Keep __version__ fields aligned.
    for init_path in (root / "agent" / "core" / "__init__.py", root / "agent" / "helper" / "__init__.py"):
        if _update_init_version(init_path, version):
            changed.append(str(init_path))
        else:
            warnings.append(f"Could not patch __version__ in {init_path}")

    print(f"[OK] Version sync complete for {version}")
    print("[CHANGED]")
    for item in changed:
        print(f"  - {item}")
    if warnings:
        print("[WARN]")
        for item in warnings:
            print(f"  - {item}")

    print("\n[NOTE] DB target_version is runtime state.")
    print("Use dashboard/API /dashboard/api/updates/set-target for rollout targets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
