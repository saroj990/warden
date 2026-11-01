"""LLM provider adapters."""

from pr_review.providers.base import (
    ChatMessage,
    ChatRole,
    ConnectionCheckResult,
    LLMProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderResponse,
    ProviderResponseError,
    ProviderTimeoutError,
)
from pr_review.providers.ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    OllamaProvider,
)

__all__ = [
    "DEFAULT_OLLAMA_BASE_URL",
    "DEFAULT_TIMEOUT_SECONDS",
    "ChatMessage",
    "ChatRole",
    "ConnectionCheckResult",
    "LLMProvider",
    "OllamaProvider",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderResponse",
    "ProviderResponseError",
    "ProviderTimeoutError",
]
