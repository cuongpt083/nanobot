"""HTTP Server for Nanobot LLM Proxy."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.llm_proxy.budget import BudgetTracker
from nanobot.llm_proxy.keys import KeyStore, ProxyApiKey
from nanobot.llm_proxy.router import ProxyRouter
from nanobot.llm_proxy.surfaces.anthropic import handle_anthropic_messages
from nanobot.llm_proxy.surfaces.openai_chat import handle_openai_chat

DEFAULT_PROXY_PORT = 23334
DEFAULT_PROXY_HOST = "127.0.0.1"


class LLMProxyServer:
    """Standalone aiohttp server providing OpenAI and Anthropic API surfaces."""

    def __init__(
        self,
        host: str = DEFAULT_PROXY_HOST,
        port: int = DEFAULT_PROXY_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self.key_store = KeyStore()
        self.budget_tracker = BudgetTracker()
        self.router = ProxyRouter()
        self.app = web.Application()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        self.app.router.add_get("/health", self._handle_health)
        self.app.router.add_get("/v1/models", self._handle_models)
        self.app.router.add_post("/v1/chat/completions", self._dispatch_openai_chat)
        self.app.router.add_post("/v1/messages", self._dispatch_anthropic)

        # Admin key management endpoints
        self.app.router.add_get("/api/proxy/keys", self._handle_list_keys)
        self.app.router.add_post("/api/proxy/keys", self._handle_create_key)
        self.app.router.add_delete("/api/proxy/keys/{id}", self._handle_delete_key)

    def _authenticate(self, request: web.Request) -> ProxyApiKey | None:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[len("Bearer ") :].strip()
            return self.key_store.validate_secret(token)

        # Anthropic x-api-key header
        x_key = request.headers.get("x-api-key", "").strip()
        if x_key:
            return self.key_store.validate_secret(x_key)

        return None

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "nanobot-llm-proxy"})

    async def _handle_models(self, request: web.Request) -> web.Response:
        key = self._authenticate(request)
        if not key:
            return web.json_response(
                {"error": {"message": "Unauthorized API key", "type": "auth_error"}},
                status=401,
            )

        models = [
            {"id": "claude-3-7-sonnet", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-3-5-sonnet", "object": "model", "owned_by": "anthropic"},
            {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
            {"id": "gemini-2.5-pro", "object": "model", "owned_by": "google"},
            {"id": "gemini-2.5-flash", "object": "model", "owned_by": "google"},
        ]
        return web.json_response({"object": "list", "data": models})

    async def _dispatch_openai_chat(self, request: web.Request) -> web.StreamResponse:
        key = self._authenticate(request)
        if not key:
            return web.json_response(
                {"error": {"message": "Invalid API key", "type": "authentication_error"}},
                status=401,
            )
        return await handle_openai_chat(request, key, self.budget_tracker, self.router)

    async def _dispatch_anthropic(self, request: web.Request) -> web.StreamResponse:
        key = self._authenticate(request)
        if not key:
            return web.json_response(
                {"error": {"type": "authentication_error", "message": "Invalid API key"}},
                status=401,
            )
        return await handle_anthropic_messages(request, key, self.budget_tracker, self.router)

    async def _handle_list_keys(self, request: web.Request) -> web.Response:
        keys = self.key_store.list_keys()
        for k in keys:
            dummy_key = ProxyApiKey(
                id=k["id"],
                name=k["name"],
                key_hash="",
                created_at=k["created_at"],
                budget_period=k.get("budget_period", "none"),
                budget_tokens=k.get("budget_tokens"),
            )
            k["budget_status"] = self.budget_tracker.get_status(dummy_key)
        return web.json_response({"keys": keys})

    async def _handle_create_key(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = body.get("name", "New Key")
        period = body.get("budget_period", "none")
        tokens = body.get("budget_tokens")
        secret, key = self.key_store.create_key(
            name=name,
            budget_period=period,
            budget_tokens=tokens,
        )
        return web.json_response({
            "status": "ok",
            "secret": secret,
            "key": key.to_public_dict(),
        })

    async def _handle_delete_key(self, request: web.Request) -> web.Response:
        key_id = request.match_info.get("id", "")
        ok = self.key_store.delete_key(key_id)
        return web.json_response({"status": "ok" if ok else "not_found"})

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("Nanobot LLM Proxy running on http://{}:{}", self.host, self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.info("Nanobot LLM Proxy stopped.")
