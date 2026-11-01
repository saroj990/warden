"""Ollama local HTTP provider."""

from __future__ import annotations

import time
from typing import Any

import httpx

from pr_review.providers.base import (
    ChatMessage,
    ConnectionCheckResult,
    LLMProvider,
    ProviderConnectionError,
    ProviderResponse,
    ProviderResponseError,
    ProviderTimeoutError,
)

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_SECONDS = 120.0


class OllamaProvider(LLMProvider):
    """Chat completions via Ollama's ``/api/chat`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_timeout_seconds = default_timeout_seconds
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return "ollama"

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> OllamaProvider:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url)
        return self._client

    def check_connection(self) -> ConnectionCheckResult:
        """List local models via ``GET /api/tags`` (no generation)."""
        try:
            response = self._get_client().get(
                "/api/tags",
                timeout=min(10.0, self._default_timeout_seconds),
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            return ConnectionCheckResult(
                ok=False,
                provider=self.name,
                message="Ollama request timed out",
                base_url=self._base_url,
                details={"error": str(exc)},
            )
        except httpx.HTTPError as exc:
            return ConnectionCheckResult(
                ok=False,
                provider=self.name,
                message="Could not reach Ollama",
                base_url=self._base_url,
                details={"error": str(exc)},
            )

        try:
            payload = response.json()
        except ValueError as exc:
            return ConnectionCheckResult(
                ok=False,
                provider=self.name,
                message="Ollama returned non-JSON from /api/tags",
                base_url=self._base_url,
                details={"error": str(exc)},
            )

        models = payload.get("models")
        model_names: list[str] = []
        if isinstance(models, list):
            for entry in models:
                if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                    model_names.append(entry["name"])

        return ConnectionCheckResult(
            ok=True,
            provider=self.name,
            message="Ollama is reachable",
            base_url=self._base_url,
            details={"model_count": len(model_names), "models": model_names[:20]},
        )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        timeout_seconds: float | None = None,
    ) -> ProviderResponse:
        if not model.strip():
            raise ProviderResponseError("model name is required")
        if not messages:
            raise ProviderResponseError("at least one message is required")

        timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        body = {
            "model": model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in messages
            ],
            "stream": False,
        }

        started = time.perf_counter()
        try:
            response = self._get_client().post(
                "/api/chat",
                json=body,
                timeout=timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Ollama chat request timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = _http_error_detail(exc.response)
            if exc.response.status_code == 404:
                raise ProviderResponseError(
                    "Ollama returned 404 for /api/chat. "
                    f"Model {model!r} is likely not installed — pick a name from "
                    "check_connection() details['models'] or run `ollama list`. "
                    f"{detail}"
                ) from exc
            raise ProviderConnectionError(
                f"Ollama chat request failed: HTTP {exc.response.status_code}. "
                f"{detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderConnectionError("Ollama chat request failed") from exc

        elapsed = time.perf_counter() - started

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ProviderResponseError("Ollama returned non-JSON body") from exc

        content = _extract_assistant_content(payload)
        if content is None:
            raise ProviderResponseError("Ollama response missing assistant content")

        safe_metadata = {
            "done": payload.get("done"),
            "total_duration": payload.get("total_duration"),
            "load_duration": payload.get("load_duration"),
            "prompt_eval_count": payload.get("prompt_eval_count"),
            "eval_count": payload.get("eval_count"),
        }

        return ProviderResponse(
            content=content,
            model=str(payload.get("model") or model),
            provider=self.name,
            elapsed_seconds=elapsed,
            raw_metadata=safe_metadata,
        )


def _http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, str) and err.strip():
                return err.strip()
    except ValueError:
        pass
    text = response.text.strip()
    if text:
        return text[:500]
    return ""


def _extract_assistant_content(payload: dict[str, Any]) -> str | None:
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
    # Some endpoints return plain "response" (generate API); tolerate if present.
    legacy = payload.get("response")
    if isinstance(legacy, str) and legacy.strip():
        return legacy
    return None
