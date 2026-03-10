#!/usr/bin/env python3
"""Compile-check helper/core entrypoint files used at runtime."""
import py_compile
from pathlib import Path


TARGETS = [
    Path("sentinel_helper.py"),
    Path("sentinel_core.py"),
]


def main():
    root = Path(__file__).resolve().parent
    targets = [root / t for t in TARGETS]
    targets.extend(sorted((root / "helper").glob("*.py")))
    targets.extend(sorted((root / "core").glob("*.py")))

    failed = []
    for target in targets:
        try:
            py_compile.compile(str(target), doraise=True)
            print(f"OK: {target}")
        except Exception as exc:
            print(f"FAIL: {target} -> {exc}")
            failed.append(target)

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
