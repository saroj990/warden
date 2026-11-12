"""Unit tests for the Ollama provider (mocked HTTP)."""

from __future__ import annotations

import json

import httpx
import pytest

from pr_review.providers import (
    ChatMessage,
    ChatRole,
    OllamaProvider,
    ProviderConnectionError,
    ProviderResponseError,
    ProviderTimeoutError,
)


def _mock_transport(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, base_url="http://ollama.test")


def test_check_connection_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={"models": [{"name": "llama3:latest"}, {"name": "qwen2.5:7b"}]},
        )

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(base_url="http://ollama.test", client=client)
    result = provider.check_connection()

    assert result.ok is True
    assert result.provider == "ollama"
    assert result.details["model_count"] == 2
    assert "llama3:latest" in result.details["models"]


def test_check_connection_http_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)
    result = provider.check_connection()

    assert result.ok is False
    assert "Could not reach Ollama" in result.message or result.ok is False


def test_check_connection_malformed_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)
    result = provider.check_connection()

    assert result.ok is False
    assert "non-JSON" in result.message


def test_chat_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/chat"
        body = json.loads(request.content.decode())
        assert body["model"] == "llama3"
        assert body["stream"] is False
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "model": "llama3",
                "message": {"role": "assistant", "content": "Looks good."},
                "done": True,
                "eval_count": 12,
            },
        )

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)
    response = provider.chat(
        [ChatMessage(role=ChatRole.USER, content="Review this diff.")],
        model="llama3",
    )

    assert response.content == "Looks good."
    assert response.model == "llama3"
    assert response.provider == "ollama"
    assert response.elapsed_seconds >= 0.0
    assert response.raw_metadata["done"] is True


def test_chat_timeout_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)

    with pytest.raises(ProviderTimeoutError):
        provider.chat(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            model="llama3",
            timeout_seconds=1.0,
        )


def test_chat_connection_error_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)

    with pytest.raises(ProviderConnectionError):
        provider.chat(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            model="llama3",
        )


def test_chat_missing_assistant_content_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "llama3", "message": {}})

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)

    with pytest.raises(ProviderResponseError):
        provider.chat(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            model="llama3",
        )


def test_chat_unknown_model_404_raises_response_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": "model 'YOUR_MODEL' not found"},
        )

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)

    with pytest.raises(ProviderResponseError) as exc_info:
        provider.chat(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            model="YOUR_MODEL",
        )
    assert "404" in str(exc_info.value)
    assert "YOUR_MODEL" in str(exc_info.value)


def test_chat_stream_success() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["stream"] is True
        lines = [
            json.dumps({"message": {"content": "Hel"}, "done": False}),
            json.dumps(
                {
                    "model": "llama3",
                    "message": {"content": "lo"},
                    "done": True,
                    "eval_count": 2,
                }
            ),
        ]
        return httpx.Response(200, content="\n".join(lines).encode())

    client = _mock_transport(httpx.MockTransport(handler))
    provider = OllamaProvider(client=client)
    response = provider.chat(
        [ChatMessage(role=ChatRole.USER, content="Review this diff.")],
        model="llama3",
        stream=True,
        stream_writer=captured.append,
    )

    assert response.content == "Hello"
    assert response.model == "llama3"
    assert captured == ["Hel", "lo"]


def test_chat_requires_model_and_messages() -> None:
    provider = OllamaProvider(
        client=_mock_transport(httpx.MockTransport(lambda r: httpx.Response(200)))
    )

    with pytest.raises(ProviderResponseError):
        provider.chat([], model="llama3")

    with pytest.raises(ProviderResponseError):
        provider.chat(
            [ChatMessage(role=ChatRole.USER, content="hi")],
            model="   ",
        )
