#!/usr/bin/env python3
"""
Download and extract a relocatable Python runtime from python-build-standalone.
Target destination: desktop/runtime/python/
"""

import os
import platform
import shutil
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

# Pinned python-build-standalone release
DEFAULT_TAG = "20261001"
DEFAULT_PYTHON_VERSION = "3.12.15"


def get_platform_triple() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if machine in ("amd64", "x86_64"):
            return "x86_64-pc-windows-msvc"
        raise RuntimeError(f"Unsupported Windows architecture: {machine}")
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        elif machine in ("x86_64", "amd64"):
            return "x86_64-apple-darwin"
        raise RuntimeError(f"Unsupported macOS architecture: {machine}")
    elif system == "linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64-unknown-linux-gnu"
        elif machine in ("arm64", "aarch64"):
            return "aarch64-unknown-linux-gnu"
        raise RuntimeError(f"Unsupported Linux architecture: {machine}")
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def download_file(url: str, dest_path: Path):
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(".tmp")

    print(f"Downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "nanobot-desktop-fetch"})
    with urllib.request.urlopen(req) as response, open(temp_path, "wb") as out_file:
        total = response.getheader("Content-Length")
        total_size = int(total) if total else None
        downloaded = 0
        chunk_size = 1024 * 512

        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)
            if total_size:
                pct = (downloaded / total_size) * 100
                print(f"\r  Progress: {pct:.1f}% ({downloaded // (1024 * 1024)}MB / {total_size // (1024 * 1024)}MB)", end="", flush=True)
            else:
                print(f"\r  Downloaded: {downloaded // (1024 * 1024)}MB", end="", flush=True)

    print()
    if temp_path.exists():
        temp_path.replace(dest_path)


def fetch_runtime(
    tag: str = DEFAULT_TAG,
    py_ver: str = DEFAULT_PYTHON_VERSION,
    desktop_dir: Path | None = None,
) -> Path:
    if desktop_dir is None:
        desktop_dir = Path(__file__).resolve().parent.parent

    triple = get_platform_triple()
    archive_name = f"cpython-{py_ver}+{tag}-{triple}-install_only.tar.gz"
    encoded_name = urllib.parse.quote(archive_name, safe="=+")
    download_url = f"https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/{encoded_name}"

    cache_dir = desktop_dir / ".cache"
    archive_path = cache_dir / archive_name
    dest_dir = desktop_dir / "runtime" / "python"
    version_marker = dest_dir / ".runtime_version"
    expected_version = f"{py_ver}+{tag}-{triple}"

    # Check executable existence
    exe_name = "python.exe" if platform.system().lower() == "windows" else "bin/python3"
    exe_path = dest_dir / exe_name

    if exe_path.is_file() and version_marker.is_file():
        try:
            if version_marker.read_text(encoding="utf-8").strip() == expected_version:
                print(f"Python runtime {expected_version} already present at {dest_dir}. Skipping download.")
                return exe_path
        except Exception:
            pass

    # 1. Download if not cached
    if not archive_path.is_file() or archive_path.stat().st_size == 0:
        download_file(download_url, archive_path)
    else:
        print(f"Using cached archive: {archive_path}")

    # 2. Extract archive
    print(f"Extracting {archive_name} to {dest_dir} ...")
    temp_extract_dir = desktop_dir / ".cache" / f"extract_{tag}_{triple}"
    if temp_extract_dir.exists():
        shutil.rmtree(temp_extract_dir, ignore_errors=True)
    temp_extract_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=temp_extract_dir)

    # In python-build-standalone tarballs, the root is usually "python"
    inner_python = temp_extract_dir / "python"
    source_dir = inner_python if inner_python.is_dir() else temp_extract_dir

    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(source_dir), str(dest_dir))
    shutil.rmtree(temp_extract_dir, ignore_errors=True)

    # Write version marker
    version_marker.write_text(expected_version, encoding="utf-8")
    print(f"Successfully installed Python runtime to {dest_dir}")

    if not exe_path.is_file():
        raise FileNotFoundError(f"Expected executable not found at: {exe_path}")

    return exe_path


def main():
    try:
        exe = fetch_runtime()
        print(f"Python executable ready at: {exe}")
    except Exception as exc:
        print(f"Error fetching Python runtime: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
