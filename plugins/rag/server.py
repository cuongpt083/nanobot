#!/usr/bin/env python3
"""Pure Python stdio MCP Server for LightRAG & Laya Decision Integration."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure local plugin directory is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from laya_client import LayaClient
from lightrag_client import LightRagClient

# Read configuration from environment
LIGHTRAG_BASE_URL = os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621")
LIGHTRAG_API_KEY = os.getenv("LIGHTRAG_API_KEY", "")
LIGHTRAG_WORKSPACE = os.getenv("LIGHTRAG_WORKSPACE", "")

LAYA_ENABLED = os.getenv("LAYA_ENABLED", "true").lower() in ("true", "1", "yes")
LAYA_SERVICE_URL = os.getenv("LAYA_SERVICE_URL", "http://localhost:8000/v1/decide")
LAYA_THRESHOLD = float(os.getenv("LAYA_THRESHOLD", "0.70"))
LAYA_TIMEOUT = float(os.getenv("LAYA_TIMEOUT_SECONDS", "0.50"))

laya_client = LayaClient(
    service_url=LAYA_SERVICE_URL,
    threshold=LAYA_THRESHOLD,
    timeout=LAYA_TIMEOUT,
    enabled=LAYA_ENABLED,
)

lightrag_client = LightRagClient(
    base_url=LIGHTRAG_BASE_URL,
    api_key=LIGHTRAG_API_KEY,
    workspace=LIGHTRAG_WORKSPACE,
)

TOOLS_METADATA = [
    {
        "name": "rag_search",
        "description": "Tra cứu tài liệu và đồ thị tri thức từ LightRAG Server với cổng kiểm soát Laya. Hỗ trợ 5 mode: mix (mặc định), local (thực thể), global (khái quát), hybrid, naive.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung câu hỏi cần tra cứu tri thức."},
                "mode": {
                    "type": "string",
                    "enum": ["mix", "local", "global", "hybrid", "naive"],
                    "default": "mix",
                    "description": "Chế độ tra cứu: local (chi tiết thực thể), global (tổng quan bức tranh rộng), mix (kết hợp đồ thị + vector).",
                },
                "bypass_decision": {
                    "type": "boolean",
                    "default": False,
                    "description": "Đặt true nếu muốn ép buộc truy vấn LightRAG bỏ qua kiểm tra Laya.",
                },
                "workspace": {
                    "type": "string",
                    "default": "",
                    "description": "Chỉ định workspace cụ thể trên LightRAG Server.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "rag_check_decision",
        "description": "Kiểm tra nhanh xem câu hỏi có thuộc phạm vi cần tra cứu tri thức hay không thông qua Laya Decision Service.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung câu hỏi cần kiểm tra."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "rag_health",
        "description": "Kiểm tra trạng thái kết nối tới máy chủ LightRAG Server và dịch vụ Laya Decision.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


async def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "rag_search":
        query = str(arguments.get("query", "")).strip()
        mode = str(arguments.get("mode", "mix")).strip()
        bypass = bool(arguments.get("bypass_decision", False))
        workspace = str(arguments.get("workspace", "")).strip()

        # Step 1: Laya Decision Check
        if not bypass and LAYA_ENABLED:
            should_ret, conf, reason = await laya_client.should_retrieve(query, workspace)
            if not should_ret:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "retrieved": False,
                                    "decision": "skipped",
                                    "confidence": conf,
                                    "reason": "Laya xác định truy vấn này là hội thoại thông thường, không cần tra cứu Knowledge Base.",
                                    "guidance": "Bạn có thể trả lời trực tiếp người dùng. Nếu bắt buộc cần tìm kiếm, hãy gọi lại với bypass_decision=true.",
                                },
                                ensure_ascii=False,
                                indent=2,
                            ),
                        }
                    ]
                }

        # Step 2: LightRAG Query Execution
        result = await lightrag_client.query(query, mode=mode, workspace=workspace)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ]
        }

    if name == "rag_check_decision":
        query = str(arguments.get("query", "")).strip()
        should_ret, conf, reason = await laya_client.should_retrieve(query)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "should_retrieve": should_ret,
                            "confidence": conf,
                            "status_reason": reason,
                            "circuit_status": laya_client.circuit_status,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            ]
        }

    if name == "rag_health":
        lightrag_status = await lightrag_client.health()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "online",
                            "lightrag": {
                                "base_url": LIGHTRAG_BASE_URL,
                                **lightrag_status,
                            },
                            "laya": {
                                "enabled": LAYA_ENABLED,
                                "service_url": LAYA_SERVICE_URL,
                                "circuit_status": laya_client.circuit_status,
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            ]
        }

    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break
        raw = line.decode("utf-8").strip()
        if not raw:
            continue

        try:
            req = json.loads(raw)
        except Exception:
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "nanobot-rag-server", "version": "1.0.0"},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS_METADATA},
            }
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                tool_res = await handle_tool_call(name, arguments)
                resp = {"jsonrpc": "2.0", "id": msg_id, "result": tool_res}
            except Exception as exc:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": str(exc)},
                }
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
