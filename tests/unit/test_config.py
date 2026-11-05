"""Unit tests for settings loading."""

from __future__ import annotations

import pytest

from pr_review.config import ConfigError, load_settings


def test_defaults_when_config_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    settings = load_settings(cwd=tmp_path)
    assert settings.base == "main"
    assert settings.model == ""
    assert settings.provider_name == "ollama"
    assert settings.report_format == "markdown"
    assert settings.fail_on_severity == "none"
    assert settings.parse_retries == 1
    assert ".env" in settings.exclude_globs


def test_toml_then_environment_override(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.toml").write_text(
        """
[review]
base = "develop"
max_diff_bytes = 1000
parse_retries = 2

[provider]
name = "ollama"
model = "from-file"
base_url = "http://127.0.0.1:9"
timeout_seconds = 15

[report]
format = "json"
fail_on_severity = "high"

[security]
exclude_globs = ["*.secret"]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_MODEL", "from-env")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    settings = load_settings(cwd=tmp_path)

    assert settings.base == "develop"
    assert settings.max_diff_bytes == 1000
    assert settings.parse_retries == 2
    assert settings.model == "from-env"
    assert settings.base_url == "http://127.0.0.1:9"
    assert settings.timeout_seconds == 15
    assert settings.report_format == "json"
    assert settings.fail_on_severity == "high"
    assert settings.exclude_globs == ["*.secret"]


def test_missing_explicit_config_raises(tmp_path: object) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(config_path=f"{tmp_path}/missing.toml")


def test_invalid_toml_raises(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("this is not = [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid config"):
        load_settings(config_path=path)
