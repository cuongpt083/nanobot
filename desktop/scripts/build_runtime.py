#!/usr/bin/env python3
"""
Orchestrator to prepare the full standalone Python runtime bundle:
1. Fetch python-build-standalone (if not already cached)
2. Build nanobot wheel
3. Install nanobot + dependencies into desktop/runtime/site-packages/
4. Verify package assets and import
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure desktop/scripts is on sys.path
scripts_dir = Path(__file__).resolve().parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from fetch_python_runtime import fetch_runtime
from build_python_runtime import (
    build_wheel,
    install_into_target,
    verify_installation,
)


def build_full_runtime(
    extras: str | None = "api",
    force: bool = False,
    py_ver: str | None = None,
    tag: str | None = None,
):
    desktop_dir = scripts_dir.parent
    repo_root = desktop_dir.parent
    cache_dist_dir = desktop_dir / ".cache" / "dist"
    target_site_packages = desktop_dir / "runtime" / "site-packages"

    start_time = time.perf_counter()
    print("=== Step 1: Resolving standalone Python runtime ===")
    kwargs = {}
    if py_ver:
        kwargs["py_ver"] = py_ver
    if tag:
        kwargs["tag"] = tag
    python_exe = fetch_runtime(desktop_dir=desktop_dir, **kwargs)

    print("\n=== Step 2: Building nanobot wheel ===")
    wheel_path = build_wheel(repo_root, cache_dist_dir)

    print("\n=== Step 3: Installing dependencies into site-packages ===")
    changed = install_into_target(
        python_exe,
        wheel_path,
        target_site_packages,
        extras=extras,
        force=force,
    )

    print("\n=== Step 4: Verifying runtime ===")
    verify_installation(python_exe, target_site_packages)

    elapsed = time.perf_counter() - start_time
    print(f"\n[OK] Runtime preparation complete in {elapsed:.2f}s (reinstall={changed})")


def main():
    parser = argparse.ArgumentParser(description="Orchestrate Nanobot desktop Python runtime build")
    parser.add_argument("--extras", type=str, default="api", help="Optional package extras to install (default: 'api')")
    parser.add_argument("--force", action="store_true", help="Force reinstall even if wheel hash matches")
    parser.add_argument("--py-version", type=str, default=None, help="Override Python version")
    parser.add_argument("--tag", type=str, default=None, help="Override python-build-standalone tag")
    args = parser.parse_args()

    try:
        build_full_runtime(
            extras=args.extras,
            force=args.force,
            py_ver=args.py_version,
            tag=args.tag,
        )
    except Exception as exc:
        print(f"Error building runtime: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
