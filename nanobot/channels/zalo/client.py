"""JSONL Node sidecar client for zca-js."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from nanobot.config.paths import get_runtime_subdir

_BRIDGE_PACKAGE = {
    "name": "nanobot-zalo-bridge",
    "private": True,
    "type": "module",
    "dependencies": {
        "jsqr": "1.4.0",
        "pngjs": "7.0.0",
        "zca-js": "2.1.2",
    },
}
_ZCA_JS_VERSION = "2.1.2"
_REQUEST_TIMEOUT_S = 180.0
_NPM_INSTALL_TIMEOUT_S = 180.0


class ZaloBridgeError(RuntimeError):
    """Raised when the zca-js sidecar cannot complete a request."""


def _json_object(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    # json.loads objects always have string keys; the isinstance check is the
    # runtime gate for this cast.
    return dict(cast(dict[str, Any], value))


def _node_missing_message() -> str:
    return (
        "Zalo requires Node.js 18+ (zca-js, the same library OpenClaw zalouser uses). "
        "Install Node.js, then retry."
    )


def resolve_node_bin(node_path: str = "") -> str:
    configured = node_path.strip()
    if configured:
        return configured
    found = shutil.which("node")
    if found:
        return found
    raise ZaloBridgeError(_node_missing_message())


def resolve_npm_bin() -> str:
    found = shutil.which("npm")
    if found:
        return found
    raise ZaloBridgeError(
        "Zalo requires npm to install zca-js. Install Node.js (which includes npm), then retry."
    )


def _bridge_source_text() -> str:
    return files("nanobot.channels.zalo").joinpath("bridge", "zalo-bridge.mjs").read_text(
        encoding="utf-8"
    )


def ensure_bridge_install(runtime_dir: Path | None = None) -> Path:
    """Copy the sidecar script and install zca-js into a writable runtime directory."""
    dest = runtime_dir or get_runtime_subdir("zalo-bridge")
    dest.mkdir(parents=True, exist_ok=True)
    script = _bridge_source_text()
    script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
    stamp = dest / ".nanobot-bridge-stamp"
    package_json = dest / "package.json"
    bridge_js = dest / "zalo-bridge.mjs"
    expected_stamp = (
        f"{_ZCA_JS_VERSION}:{script_hash}:"
        f"{json.dumps(_BRIDGE_PACKAGE['dependencies'], sort_keys=True)}"
    )
    current_stamp = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
    node_modules = dest / "node_modules" / "zca-js"
    if current_stamp != expected_stamp or not node_modules.is_dir() or not bridge_js.is_file():
        package_json.write_text(
            json.dumps(_BRIDGE_PACKAGE, indent=2) + "\n",
            encoding="utf-8",
        )
        bridge_js.write_text(script, encoding="utf-8")
        npm = resolve_npm_bin()
        try:
            result = subprocess.run(
                [npm, "install", "--omit=dev", "--no-fund", "--no-audit"],
                cwd=dest,
                capture_output=True,
                text=True,
                timeout=_NPM_INSTALL_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ZaloBridgeError("Timed out installing zca-js via npm") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ZaloBridgeError(
                f"Failed to install zca-js via npm: {detail or f'exit {result.returncode}'}"
            )
        stamp.write_text(expected_stamp + "\n", encoding="utf-8")
    return bridge_js


class ZaloBridge:
    """Async JSONL client for the zca-js sidecar."""

    def __init__(
        self,
        credentials_path: Path,
        *,
        node_path: str = "",
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        runtime_dir: Path | None = None,
    ) -> None:
        self.credentials_path = credentials_path
        self.node_path = node_path
        self._on_event = on_event
        self._runtime_dir = runtime_dir
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._id = 0
        self._ready = asyncio.Event()

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.credentials_path.parent, 0o700)
        except OSError:
            pass
        script = ensure_bridge_install(self._runtime_dir)
        node = resolve_node_bin(self.node_path)
        process = await asyncio.create_subprocess_exec(
            node,
            str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "ZALO_CREDENTIALS_PATH": str(self.credentials_path),
            },
            cwd=str(script.parent),
        )
        self._process = process
        self._ready.clear()
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=15)
        except TimeoutError as exc:
            await self.stop()
            raise ZaloBridgeError("Zalo sidecar did not become ready") from exc

    async def stop(self) -> None:
        process = self._process
        self._process = None
        reader = self._reader_task
        stderr_task = self._stderr_task
        self._reader_task = None
        self._stderr_task = None
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (reader, stderr_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ZaloBridgeError("Zalo sidecar stopped"))
        self._pending.clear()
        self._ready.clear()

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = _REQUEST_TIMEOUT_S,
    ) -> dict[str, Any]:
        if not self.running:
            raise ZaloBridgeError("Zalo sidecar is not running")
        process = self._process
        if process is None or process.stdin is None:
            raise ZaloBridgeError("Zalo sidecar is not running")
        self._id += 1
        request_id = str(self._id)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        payload = {"id": request_id, "method": method, "params": params or {}}
        process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await process.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise ZaloBridgeError(f"Zalo sidecar timed out on {method}") from exc

    async def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    decoded: object = json.loads(text)
                except json.JSONDecodeError:
                    continue
                frame = _json_object(decoded)
                if frame is None:
                    continue
                request_id = frame.get("id")
                if isinstance(request_id, str) and request_id in self._pending:
                    future = self._pending.pop(request_id)
                    if not future.done():
                        if frame.get("ok"):
                            result = _json_object(frame.get("result")) or {}
                            future.set_result(result)
                        else:
                            error = frame.get("error")
                            future.set_exception(
                                ZaloBridgeError(
                                    error if isinstance(error, str) and error else "Zalo request failed"
                                )
                            )
                    continue
                event_name = frame.get("event")
                if isinstance(event_name, str):
                    if event_name == "ready":
                        self._ready.set()
                    parsed = _json_object(frame.get("payload")) or {}
                    if self._on_event is not None:
                        self._on_event(event_name, parsed)
        finally:
            if not self._ready.is_set():
                self._ready.set()

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
