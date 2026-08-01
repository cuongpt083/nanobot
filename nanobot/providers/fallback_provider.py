"""Provider wrapper that transparently fails over to fallback models on error."""

# pyright: reportIncompatibleMethodOverride=false, reportIncompatibleVariableOverride=false

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from nanobot.pilot.circuit import ALL_CANDIDATES_UNAVAILABLE, CircuitKey, CircuitRegistry
from nanobot.pilot.presentation import PresentationPolicy
from nanobot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    ProviderAttempt,
    ProviderCallContext,
    ProviderConversationState,
)

_FALLBACK_ERROR_KINDS = frozenset({
    "timeout",
    "connection",
    "server_error",
    "rate_limit",
    "overloaded",
})
_AUTHENTICATION_ERROR_KINDS = frozenset({
    "authentication",
    "auth",
    "permission",
})
_AUTHENTICATION_ERROR_TOKENS = (
    "authentication_error",
    "authentication error",
    "invalid_api_key",
    "invalid api key",
    "incorrect_api_key",
    "incorrect api key",
    "expired_api_key",
    "expired api key",
    "invalid credential",
    "expired credential",
    "credential has expired",
    "credentials have expired",
    "invalid_token",
    "invalid token",
    "expired_token",
    "expired token",
    "unauthorized",
    "permission_denied",
    "permission denied",
    "access_denied",
    "account_deactivated",
    "organization_deactivated",
)
_NON_FALLBACK_ERROR_KINDS = frozenset({
    "content_filter",
    "refusal",
    "context_length",
    "invalid_request",
})
_FALLBACK_ERROR_TOKENS = (
    "rate_limit",
    "rate limit",
    "too_many_requests",
    "too many requests",
    "overloaded",
    "server_error",
    "server error",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "connection",
    "empty",  # API returned empty choices (e.g. DeepSeek peak hours), transient
    "insufficient_quota",
    "insufficient quota",
    "quota_exceeded",
    "quota exceeded",
    "quota_exhausted",
    "quota exhausted",
    "billing_hard_limit",
    "insufficient_balance",
    "balance",
    "out of credits",
)


FallbackModelObserver = Callable[[str], Awaitable[None]]


class FallbackProvider(LLMProvider):
    """Wrap a primary provider and transparently failover to fallback models.

    When the primary model returns a fallbackable error before content has been
    streamed, the wrapper tries each fallback model in order. Streamed timeout
    errors are the recovery exception: the caller may close the current stream
    segment, then the wrapper continues failover with later deltas in a new
    segment. Each fallback model may reside on a different provider — a factory
    callable creates the underlying provider on-the-fly.

    Key design:
    - Failover is request-scoped (the wrapper itself is stateless between turns).
    - Candidate content, thinking, and tool callbacks are buffered until success.
    - Skipped when content was already streamed to avoid duplicate output,
      except timeout recovery can resume in a new stream segment.
    - Recursive failover is prevented by the factory returning plain providers.
    - Primary provider is circuit-broken after repeated failures to avoid
      wasting requests on a known-bad endpoint.
    """

    supports_stream_recover_callback = True

    def __init__(
        self,
        primary: LLMProvider,
        fallback_presets: list[Any],
        provider_factory: Callable[[Any], LLMProvider],
        fallback_model_observer: FallbackModelObserver | None = None,
        primary_context_window_tokens: int | None = None,
        circuit: CircuitRegistry | None = None,
        fallback_circuit_key: Callable[[Any], CircuitKey] | None = None,
    ):
        self._primary = primary
        self._fallback_presets = list(fallback_presets)
        self._provider_factory = provider_factory
        self._fallback_model_observer = fallback_model_observer
        self._primary_context_window_tokens = primary_context_window_tokens
        self._circuit = circuit or CircuitRegistry()
        self._fallback_circuit_key = fallback_circuit_key or self._default_fallback_circuit_key

    @property
    def generation(self) -> GenerationSettings:
        return self._primary.generation

    @generation.setter
    def generation(self, value: GenerationSettings) -> None:
        self._primary.generation = value

    def get_default_model(self) -> str:
        return self._primary.get_default_model()

    def set_fallback_model_observer(self, observer: FallbackModelObserver | None) -> None:
        """Attach a process-level observer without changing request call signatures."""
        self._fallback_model_observer = observer

    @property
    def supports_progress_deltas(self) -> bool:
        return bool(getattr(self._primary, "supports_progress_deltas", False))

    def can_resume_conversation_state(
        self,
        state: ProviderConversationState,
        model: str | None = None,
    ) -> bool:
        return self._primary.can_resume_conversation_state(state, model)

    def supports_native_compaction(self, model: str | None = None) -> bool:
        return self._primary.supports_native_compaction(model)

    def _primary_call_context(
        self,
        provider_context: ProviderCallContext,
        model: str | None,
    ) -> ProviderCallContext:
        context_window_tokens = (
            self._primary_context_window_tokens
            if self._primary_context_window_tokens is not None
            else provider_context.context_window_tokens
        )
        if not self._primary.supports_native_compaction(model):
            context_window_tokens = None
        return ProviderCallContext(
            conversation_state=provider_context.conversation_state,
            context_window_tokens=context_window_tokens,
        )

    async def chat(self, **kwargs: Any) -> LLMResponse:
        return await self._try_with_fallback(
            lambda p, kw: p.chat(**kw), kwargs, has_streamed=None
        )

    async def chat_with_context(
        self,
        *,
        provider_context: ProviderCallContext,
        **kwargs: Any,
    ) -> LLMResponse:
        call_kwargs: dict[str, Any] = dict(kwargs)
        call_kwargs["provider_context"] = self._primary_call_context(
            provider_context,
            kwargs.get("model"),
        )
        return await self._try_with_fallback(
            lambda p, kw: p.chat_with_context(**kw),
            call_kwargs,
            has_streamed=None,
        )

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        kwargs.pop("on_stream_recover", None)
        has_streamed: list[bool] = [False]
        original_delta = kwargs.get("on_content_delta")
        original_thinking_delta = kwargs.get("on_thinking_delta")
        original_tool_call_delta = kwargs.get("on_tool_call_delta")
        candidate_events: list[tuple[str, Any]] = []

        async def _tracking_delta(text: str) -> None:
            if text:
                has_streamed[0] = True
            candidate_events.append(("content", text))

        async def _tracking_thinking_delta(text: str) -> None:
            candidate_events.append(("thinking", text))

        async def _tracking_tool_call_delta(event: dict[str, Any]) -> None:
            candidate_events.append(("tool_call", event))

        async def _discard_candidate() -> None:
            candidate_events.clear()

        kwargs["on_content_delta"] = _tracking_delta
        if original_thinking_delta:
            kwargs["on_thinking_delta"] = _tracking_thinking_delta
        if original_tool_call_delta:
            kwargs["on_tool_call_delta"] = _tracking_tool_call_delta
        response = await self._try_with_fallback(
            lambda p, kw: p.chat_stream(**kw),
            kwargs,
            has_streamed=has_streamed,
            on_stream_recover=_discard_candidate,
        )
        if response.finish_reason != "error":
            callbacks = {
                "content": original_delta,
                "thinking": original_thinking_delta,
                "tool_call": original_tool_call_delta,
            }
            for event_name, event_value in candidate_events:
                if callback := callbacks[event_name]:
                    await callback(event_value)
        return response

    async def chat_stream_with_context(
        self,
        *,
        provider_context: ProviderCallContext,
        **kwargs: Any,
    ) -> LLMResponse:
        kwargs.pop("on_stream_recover", None)
        call_kwargs: dict[str, Any] = dict(kwargs)
        call_kwargs["provider_context"] = self._primary_call_context(
            provider_context,
            kwargs.get("model"),
        )
        has_streamed: list[bool] = [False]
        original_delta = call_kwargs.get("on_content_delta")
        original_thinking_delta = call_kwargs.get("on_thinking_delta")
        original_tool_call_delta = call_kwargs.get("on_tool_call_delta")
        candidate_events: list[tuple[str, Any]] = []

        async def _tracking_delta(text: str) -> None:
            if text:
                has_streamed[0] = True
            candidate_events.append(("content", text))

        async def _tracking_thinking_delta(text: str) -> None:
            candidate_events.append(("thinking", text))

        async def _tracking_tool_call_delta(event: dict[str, Any]) -> None:
            candidate_events.append(("tool_call", event))

        async def _discard_candidate() -> None:
            candidate_events.clear()

        call_kwargs["on_content_delta"] = _tracking_delta
        if original_thinking_delta:
            call_kwargs["on_thinking_delta"] = _tracking_thinking_delta
        if original_tool_call_delta:
            call_kwargs["on_tool_call_delta"] = _tracking_tool_call_delta
        response = await self._try_with_fallback(
            lambda p, kw: p.chat_stream_with_context(**kw),
            call_kwargs,
            has_streamed=has_streamed,
            on_stream_recover=_discard_candidate,
        )
        if response.finish_reason != "error":
            callbacks = {
                "content": original_delta,
                "thinking": original_thinking_delta,
                "tool_call": original_tool_call_delta,
            }
            for event_name, event_value in candidate_events:
                if callback := callbacks[event_name]:
                    await callback(event_value)
        return response

    async def _try_with_fallback(
        self,
        call: Callable[[LLMProvider, dict[str, Any]], Awaitable[LLMResponse]],
        kwargs: dict[str, Any],
        has_streamed: list[bool] | None,
        on_stream_recover: Callable[[], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        primary_model = kwargs.get("model") or self._primary.get_default_model()
        primary_alias = self._provider_alias(self._primary)
        primary_key = CircuitKey(primary_alias, primary_model)
        primary_was_attempted = False
        primary_error = "unknown error"
        primary_response: LLMResponse | None = None
        accumulated_attempts: list[Any] = []

        async def _reject_stream_candidate() -> None:
            if has_streamed is None:
                return
            has_streamed[0] = False
            if on_stream_recover:
                await on_stream_recover()
            else:
                kwargs["on_content_delta"] = None

        if self._circuit.allow(primary_key):
            primary_was_attempted = True
            setattr(self._primary, "_fallback_index", 0)
            response = await call(self._primary, kwargs)
            primary_response = response
            primary_attempts = getattr(response, "attempts", [])
            if not primary_attempts:
                err_cls = (response.error_kind or response.error_type) if response.finish_reason == "error" else None
                primary_attempts = [
                    ProviderAttempt(
                        provider=primary_alias,
                        model=primary_model,
                        sequence=len(accumulated_attempts) + 1,
                        retry_index=0,
                        fallback_index=0,
                        latency_ms=0,
                        finish_reason=response.finish_reason,
                        error_class=err_cls,
                        usage=response.usage,
                    )
                ]
            accumulated_attempts.extend(primary_attempts)
            response.attempts = list(accumulated_attempts)
            if response.finish_reason != "error":
                self._circuit.record_success(primary_key)
                return response
            primary_error = (response.content or primary_error)[:120]

            if not self._should_fallback(response):
                await _reject_stream_candidate()
                logger.warning(
                    "Primary model '{}' returned non-fallbackable error: {}",
                    primary_model,
                    (response.content or "")[:120],
                )
                return response
            self._circuit.record_failure(primary_key, self._error_class(response))

            if has_streamed is not None and has_streamed[0]:
                is_timeout = (response.error_kind or "").lower() == "timeout"
                if not is_timeout:
                    await _reject_stream_candidate()
                    logger.warning("Primary model error after content; skipping failover")
                    return response
                logger.warning(
                    "Primary model '{}' stream stalled after content was emitted; "
                    "attempting failover anyway",
                    primary_model,
                )
            await _reject_stream_candidate()

        else:
            logger.debug("Primary model '{}' circuit open; skipping", primary_model)

        last_response: LLMResponse | None = None
        primary_skipped = not primary_was_attempted
        for idx, fallback in enumerate(self._fallback_presets):
            fallback_model = fallback.model
            fallback_key = self._fallback_circuit_key(fallback)
            if not self._circuit.allow(fallback_key):
                logger.debug("Fallback model '{}' circuit open; skipping", fallback_model)
                continue
            if has_streamed is not None and has_streamed[0]:
                is_timeout = (
                    last_response is not None
                    and (last_response.error_kind or "").lower() == "timeout"
                )
                if is_timeout and on_stream_recover:
                    logger.warning(
                        "Fallback model '{}' stream stalled after content was emitted; "
                        "starting a new stream segment and trying next fallback",
                        self._fallback_presets[idx - 1].model if idx > 0 else primary_model,
                    )
                    has_streamed[0] = False
                    await on_stream_recover()
                else:
                    break
            if idx == 0 and primary_skipped:
                logger.info(
                    "Primary model '{}' circuit open, trying fallback '{}'",
                    primary_model, fallback_model,
                )
            elif idx == 0:
                logger.info(
                    "Primary model '{}' failed: {}; trying fallback '{}'",
                    primary_model, primary_error, fallback_model,
                )
            else:
                logger.info(
                    "Fallback '{}' also failed, trying next fallback '{}'",
                    self._fallback_presets[idx - 1].model, fallback_model,
                )
            try:
                fallback_provider = self._provider_factory(fallback)
            except Exception as exc:
                logger.warning(
                    "Failed to create provider for fallback '{}': {}", fallback_model, exc
                )
                continue

            await self._notify_fallback_model(fallback_model)

            setattr(fallback_provider, "_fallback_index", idx + 1)
            fallback_kwargs = {
                **kwargs,
                "model": fallback_model,
                "max_tokens": fallback.max_tokens,
                "temperature": fallback.temperature,
            }
            provider_context = fallback_kwargs.get("provider_context")
            if isinstance(provider_context, ProviderCallContext):
                state = provider_context.conversation_state
                if state is not None and not fallback_provider.can_resume_conversation_state(
                    state,
                    fallback_model,
                ):
                    state = None
                context_window_tokens = (
                    fallback.context_window_tokens
                    if fallback_provider.supports_native_compaction(fallback_model)
                    else None
                )
                fallback_kwargs["provider_context"] = ProviderCallContext(
                    conversation_state=state,
                    context_window_tokens=context_window_tokens,
                )
            if fallback.reasoning_effort is None:
                fallback_kwargs.pop("reasoning_effort", None)
            else:
                fallback_kwargs["reasoning_effort"] = fallback.reasoning_effort
            fallback_response = await call(fallback_provider, fallback_kwargs)
            fb_attempts = getattr(fallback_response, "attempts", [])
            if not fb_attempts:
                fallback_alias = getattr(fallback_provider, "provider_alias", fallback_provider.__class__.__name__)
                err_cls = (fallback_response.error_kind or fallback_response.error_type) if fallback_response.finish_reason == "error" else None
                fb_attempts = [
                    ProviderAttempt(
                        provider=fallback_alias,
                        model=fallback_model,
                        sequence=len(accumulated_attempts) + 1,
                        retry_index=0,
                        fallback_index=idx + 1,
                        latency_ms=0,
                        finish_reason=fallback_response.finish_reason,
                        error_class=err_cls,
                        usage=fallback_response.usage,
                    )
                ]
            accumulated_attempts.extend(fb_attempts)
            fallback_response.attempts = list(accumulated_attempts)

            if fallback_response.finish_reason != "error":
                self._circuit.record_success(fallback_key)
                logger.info(
                    "Fallback '{}' succeeded after primary '{}' failed",
                    fallback_model, primary_model,
                )
                return fallback_response

            if self._should_fallback(fallback_response):
                self._circuit.record_failure(fallback_key, self._error_class(fallback_response))
            last_response = fallback_response
            await _reject_stream_candidate()
            logger.warning(
                "Fallback '{}' also failed: {}",
                fallback_model,
                (fallback_response.content or "")[:120],
            )

        logger.warning(
            "All {} fallback model(s) failed",
            len(self._fallback_presets),
        )
        # At least one configured fallback was attempted and rejected.
        if last_response is not None:
            return self._exhausted_response(accumulated_attempts)
        # Primary was tripped and we have no fallbacks — synthesize an error.
        if primary_response is not None and not self._fallback_presets:
            return primary_response
        return self._exhausted_response(accumulated_attempts)

    @staticmethod
    def _exhausted_response(attempts: list[Any]) -> LLMResponse:
        """Return the fixed, presentation-safe terminal failure for exhaustion."""
        content = PresentationPolicy().sanitize(ALL_CANDIDATES_UNAVAILABLE, {}).content
        response = LLMResponse(
            content=content,
            finish_reason="error",
            preserve_provider_state_on_error=True,
        )
        response.attempts = list(attempts)
        return response

    @staticmethod
    def _provider_alias(provider: LLMProvider) -> str:
        return str(getattr(provider, "provider_alias", provider.__class__.__name__))

    @staticmethod
    def _default_fallback_circuit_key(fallback: Any) -> CircuitKey:
        return CircuitKey(str(getattr(fallback, "provider", "unknown")), str(fallback.model))

    @staticmethod
    def _error_class(response: LLMResponse) -> str:
        if FallbackProvider._is_authentication_response(response):
            return "authentication"
        for value in (response.error_kind, response.error_type, response.error_code):
            if value:
                return str(value)
        if response.error_status_code in {401, 403}:
            return "authentication"
        return "unknown"

    @staticmethod
    def _is_authentication_response(response: LLMResponse) -> bool:
        if response.error_status_code in {401, 403}:
            return True
        values = (response.error_kind, response.error_type, response.error_code, response.content)
        return any(
            token in str(value).lower()
            for value in values
            if value
            for token in _AUTHENTICATION_ERROR_TOKENS
        ) or any(
            str(value).strip().lower() in _AUTHENTICATION_ERROR_KINDS
            for value in values[:3]
            if value
        )

    async def _notify_fallback_model(self, model: str) -> None:
        if self._fallback_model_observer is None:
            return
        try:
            await self._fallback_model_observer(model)
        except Exception:
            logger.exception("fallback model observer failed for '{}'", model)

    @staticmethod
    def _should_fallback(response: LLMResponse) -> bool:
        if LLMProvider.is_arrearage_response(response):
            return True
        status = response.error_status_code
        kind = (response.error_kind or "").strip().lower()
        error_type = (response.error_type or "").strip().lower()
        code = (response.error_code or "").strip().lower()
        text = (response.content or "").lower()
        structured_values = (kind, error_type, code)

        non_fallback_kinds = _NON_FALLBACK_ERROR_KINDS | {
            "invalid_request", "invalid_parameter", "content_filter", "refusal", "safety", "policy", "context_length",
        }

        if any(v in non_fallback_kinds for v in structured_values if v):
            return False

        if FallbackProvider._is_authentication_response(response):
            return True

        if status in {400, 404, 422}:
            return False

        if response.error_should_retry is False:
            return False

        if status is not None and (status in {408, 409, 429} or 500 <= status <= 599):
            return True

        if response.error_should_retry is True:
            return True

        if any(v in _FALLBACK_ERROR_KINDS for v in structured_values if v):
            return True

        return any(token in value for value in (kind, error_type, code, text) for token in _FALLBACK_ERROR_TOKENS)
