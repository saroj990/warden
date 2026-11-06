"""Unit tests for the local review pipeline."""

from __future__ import annotations

import json
import subprocess

import pytest

from pr_review.config import ConfigError
from pr_review.git import parse_unified_diff
from pr_review.providers.base import (
    ChatMessage,
    ConnectionCheckResult,
    LLMProvider,
    ProviderResponse,
)
from pr_review.review import ReviewOptions, ReviewOutputError, run_review
from pr_review.review.chunking import render_file_diff

SAMPLE_DIFF = """\
diff --git a/src/example.py b/src/example.py
index 1111111..2222222 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,4 @@
 def run(cfg):
-    return cfg['x'].strip()
+    value = cfg.get('x')
+    return value.strip()
     return None
"""

TWO_FILE_DIFF = """\
diff --git a/src/a.py b/src/a.py
index 1111111..2222222 100644
--- a/src/a.py
+++ b/src/a.py
@@ -1 +1 @@
-old_a
+new_a
diff --git a/src/b.py b/src/b.py
index 1111111..2222222 100644
--- a/src/b.py
+++ b/src/b.py
@@ -1 +1 @@
-old_b
+new_b
"""

SECRET_DIFF = """\
diff --git a/.env b/.env
index 1111111..2222222 100644
--- a/.env
+++ b/.env
@@ -1 +1 @@
-OLD=1
+SECRET_TOKEN=abc
diff --git a/src/example.py b/src/example.py
index 1111111..2222222 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-print('old')
+print('ok')
"""


def _finding_payload(**overrides: object) -> dict:
    data: dict = {
        "severity": "high",
        "category": "correctness",
        "file": "src/example.py",
        "line": 2,
        "location_kind": "inline",
        "title": "Possible None dereference",
        "problem": "cfg.get('x') may return None",
        "scenario": "When key x is missing, strip() raises AttributeError",
        "evidence": [
            {
                "file": "src/example.py",
                "start_line": 2,
                "end_line": 3,
                "excerpt": "value = cfg.get('x')\nreturn value.strip()",
            }
        ],
        "suggestion": "Check for None before calling strip()",
        "confidence": 0.9,
    }
    data.update(overrides)
    return data


def _document(
    findings: list[dict] | None = None,
    summary: str = "Checked the chunk",
) -> str:
    return json.dumps({"summary": summary, "findings": findings or []})


class ScriptedProvider(LLMProvider):
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    @property
    def name(self) -> str:
        return "scripted"

    def check_connection(self) -> ConnectionCheckResult:
        return ConnectionCheckResult(ok=True, provider=self.name, message="ok")

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        timeout_seconds: float | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        self.prompts.append("\n".join(message.content for message in messages))
        if not self._responses:
            raise AssertionError("provider received more calls than scripted")
        content = self._responses.pop(0)
        return ProviderResponse(
            content=content,
            model=model,
            provider=self.name,
            elapsed_seconds=0.0,
        )


def _options(**overrides: object) -> ReviewOptions:
    data: dict = {
        "model": "test-model",
        "provider_name": "scripted",
        "comparison": "supplied diff",
        "diff_source": "changes.diff",
    }
    data.update(overrides)
    return ReviewOptions.model_validate(data)


def test_accepts_evidence_backed_finding() -> None:
    provider = ScriptedProvider([_document([_finding_payload()])])
    report = run_review(SAMPLE_DIFF, provider, _options())

    assert provider.calls == 1
    assert len(report.findings) == 1
    assert report.findings[0].title == "Possible None dereference"
    assert report.findings[0].fingerprint
    assert report.summary == "Checked the chunk"
    assert report.scope is not None
    assert report.scope.model == "test-model"
    assert report.scope.files == ["src/example.py"]
    assert report.checks == []
    assert any("Only the diff was sent" in item for item in report.limitations)


def test_rejects_finding_on_a_line_outside_the_diff() -> None:
    payload = _finding_payload(line=40, title="Wrong line")
    provider = ScriptedProvider([_document([payload])])
    report = run_review(SAMPLE_DIFF, provider, _options())

    assert report.findings == []
    assert report.summary == "No actionable findings identified."
    assert any(
        "Rejected" in item and "Wrong line" in item for item in report.limitations
    )


def test_retries_malformed_json_then_accepts() -> None:
    provider = ScriptedProvider(["not json", _document([_finding_payload()])])
    report = run_review(SAMPLE_DIFF, provider, _options(parse_retries=1))

    assert provider.calls == 2
    assert len(report.findings) == 1
    assert "Return only the JSON object" in provider.prompts[1]


def test_malformed_json_fails_after_retries() -> None:
    provider = ScriptedProvider(["not json", "still not json"])
    with pytest.raises(ReviewOutputError, match="not valid JSON"):
        run_review(SAMPLE_DIFF, provider, _options(parse_retries=1))
    assert provider.calls == 2


def test_empty_diff_does_not_call_the_model() -> None:
    provider = ScriptedProvider([])
    report = run_review("", provider, _options())

    assert provider.calls == 0
    assert report.findings == []
    assert report.summary == "No actionable findings identified."
    assert any("No reviewable textual changes" in item for item in report.limitations)


def test_excluded_file_is_not_sent_to_the_model() -> None:
    provider = ScriptedProvider([_document()])
    report = run_review(SECRET_DIFF, provider, _options())

    assert provider.calls == 1
    assert "SECRET_TOKEN" not in provider.prompts[0]
    assert "SECRET_TOKEN" not in report.model_dump_json()
    assert report.scope is not None
    assert report.scope.files == ["src/example.py"]
    assert any(item.path == ".env" for item in report.scope.skipped)


def test_large_diff_is_split_without_dropping_files() -> None:
    parsed = parse_unified_diff(TWO_FILE_DIFF)
    first_size = len(render_file_diff(parsed.files[0]).encode("utf-8"))
    provider = ScriptedProvider([_document(), _document()])

    report = run_review(
        TWO_FILE_DIFF,
        provider,
        _options(max_diff_bytes=first_size),
    )

    assert provider.calls == 2
    assert report.scope is not None
    assert report.scope.files == ["src/a.py", "src/b.py"]
    assert "new_a" in provider.prompts[0]
    assert "new_b" in provider.prompts[1]
    assert "new_b" not in provider.prompts[0]


def test_oversized_single_file_is_skipped() -> None:
    provider = ScriptedProvider([])
    report = run_review(SAMPLE_DIFF, provider, _options(max_diff_bytes=40))

    assert provider.calls == 0
    assert report.scope is not None
    assert report.scope.files == []
    assert any("max_diff_bytes" in item.reason for item in report.scope.skipped)


def test_binary_file_is_skipped_with_a_reason() -> None:
    diff = """\
diff --git a/image.bin b/image.bin
new file mode 100644
index 0000000..1111111
Binary files /dev/null and b/image.bin differ
"""
    provider = ScriptedProvider([])
    report = run_review(diff, provider, _options())

    assert provider.calls == 0
    assert report.scope is not None
    assert any(item.reason == "binary file" for item in report.scope.skipped)


def _git(repo, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_symbol_search_is_included_in_the_prompt(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "lib.py").write_text(
        "def apply_discount(amount):\n    return amount\n",
        encoding="utf-8",
    )
    (repo / "order.py").write_text(
        "total = apply_discount(1)\nreturn total\n",
        encoding="utf-8",
    )
    _git(repo, "add", "lib.py", "order.py")
    _git(repo, "commit", "-m", "init")
    diff = """\
diff --git a/order.py b/order.py
--- a/order.py
+++ b/order.py
@@ -1 +1,2 @@
-total = 1
+total = apply_discount(1)
+return total
"""
    provider = ScriptedProvider([_document()])
    report = run_review(
        diff,
        provider,
        _options(repo_root=str(repo), context_surrounding_lines=0),
    )

    assert "symbol context: apply_discount" in provider.prompts[0]
    assert report.scope is not None
    assert any(
        item.path == "lib.py" and "apply_discount" in item.reason
        for item in report.scope.context_inspected
    )


def test_missing_model_raises_before_a_call() -> None:
    provider = ScriptedProvider([_document()])
    with pytest.raises(ConfigError, match="model is required"):
        run_review(SAMPLE_DIFF, provider, _options(model="  "))
    assert provider.calls == 0
