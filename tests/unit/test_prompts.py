"""Unit tests for review prompts (Phase 1.1 generic logical regression guidance)."""

from __future__ import annotations

from pr_review.review.prompts import (
    SYSTEM_PROMPT,
    build_messages,
)


def test_system_prompt_includes_logical_regression_guidance() -> None:
    assert "compare lines removed (-) with lines added (+)" in SYSTEM_PROMPT
    assert "divide by 100" in SYSTEM_PROMPT
    assert "cents" in SYSTEM_PROMPT.lower()


def test_build_messages_includes_diff_chunk() -> None:
    messages = build_messages(
        comparison="main...feature",
        chunk_text="file: src/billing.py\n+    return amount * (1 - percent)",
    )
    assert len(messages) == 2
    user = messages[1].content
    assert "Diff chunk:" in user
    assert "src/billing.py" in user