"""Asynchronous HTTP client for an external LightRAG Server REST API."""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

SUPPORTED_MODES = ("mix", "local", "global", "hybrid", "naive")
DEFAULT_MODE = "mix"


def _extract_sources(references: Any) -> List[str]:
    """Parse reference sources list into clean file/document strings."""
    if not isinstance(references, list):
        return []
    sources: list[str] = []
    for ref in references:
        if isinstance(ref, str) and ref.strip():
            sources.append(ref.strip())
        elif isinstance(ref, dict):
            name = ref.get("file") or ref.get("source") or ref.get("doc_name") or ref.get("id")
            if name and str(name).strip() and str(name).strip() not in sources:
                sources.append(str(name).strip())
    return sources


class LightRagClient:
    """Client for querying a standalone LightRAG Server."""

    def __init__(
        self,
        base_url: str = "http://localhost:9621",
        api_key: str = "",
        workspace: str = "",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.workspace = (workspace or "").strip()
        self.timeout = timeout

    def _headers(self, workspace_override: str = "") -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        ws = workspace_override or self.workspace
        if ws:
            headers["LIGHTRAG-WORKSPACE"] = ws
        return headers

    async def query(
        self,
        query: str,
        mode: str = DEFAULT_MODE,
        workspace: str = "",
    ) -> dict[str, Any]:
        """Query LightRAG Server and return context + sources."""
        query_str = (query or "").strip()
        if not query_str:
            return {"retrieved": False, "error": "Query cannot be empty."}

        target_mode = mode if mode in SUPPORTED_MODES else DEFAULT_MODE
        url = f"{self.base_url}/query"
        payload = {
            "query": query_str,
            "mode": target_mode,
            "only_need_context": True,
        }

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers(workspace))
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

                if resp.status_code >= 400:
                    return {
                        "retrieved": False,
                        "error": f"LightRAG server returned HTTP {resp.status_code}: {resp.text[:300]}",
                        "latency_ms": latency_ms,
                    }

                data = resp.json()
                content = str(data.get("response") or data.get("content") or "")
                sources = _extract_sources(data.get("references"))

                return {
                    "retrieved": True,
                    "mode": target_mode,
                    "content": content,
                    "sources": sources,
                    "latency_ms": latency_ms,
                }
        except httpx.ConnectError:
            return {
                "retrieved": False,
                "error": f"Cannot connect to LightRAG Server at {self.base_url}. Service may be offline.",
            }
        except httpx.TimeoutException:
            return {
                "retrieved": False,
                "error": f"LightRAG Server query timed out after {self.timeout}s.",
            }
        except Exception as exc:
            return {
                "retrieved": False,
                "error": f"Unexpected error while querying LightRAG Server: {exc}",
            }

    async def health(self) -> dict[str, Any]:
        """Check reachability and server status."""
        url = f"{self.base_url}/health"
        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers={"Accept": "application/json"})
                latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "reachable": resp.status_code < 400,
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                }
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}
