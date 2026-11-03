"""Provider-neutral LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1)


class ProviderResponse(BaseModel):
    content: str
    model: str
    provider: str
    elapsed_seconds: float = Field(ge=0.0)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ConnectionCheckResult(BaseModel):
    ok: bool
    provider: str
    message: str
    base_url: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ProviderError(Exception):
    """Base error for LLM provider failures."""


class ProviderConnectionError(ProviderError):
    """The provider endpoint could not be reached."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond in time."""


class ProviderResponseError(ProviderError):
    """The provider returned an unexpected or malformed response."""


class LLMProvider(ABC):
    """Small abstraction over chat completion backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def check_connection(self) -> ConnectionCheckResult:
        """Verify reachability without requiring a model inference call."""

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        timeout_seconds: float | None = None,
    ) -> ProviderResponse:
        """Run a chat completion and return assistant text plus safe metadata."""
