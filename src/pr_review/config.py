"""Load review settings from defaults, config.toml, and the environment."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

DEFAULT_EXCLUDE_GLOBS = [
    ".env",
    ".env.*",
    "**/*.pem",
    "**/secrets/**",
    "**/node_modules/**",
    "**/.git/**",
]

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


class ConfigError(Exception):
    """The review configuration is missing or invalid."""


class Settings(BaseModel):
    base: str = "main"
    max_diff_bytes: int = Field(default=200_000, ge=1)
    max_files: int = Field(default=0, ge=0)
    parse_retries: int = Field(default=1, ge=0)
    provider_name: str = "ollama"
    model: str = ""
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    timeout_seconds: float = Field(default=120.0, gt=0)
    report_format: str = "markdown"
    fail_on_severity: str = "none"
    exclude_globs: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXCLUDE_GLOBS)
    )


def load_settings(
    config_path: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> Settings:
    """Load settings.

    Precedence for model and base URL is environment, then the TOML file,
    then built-in defaults. CLI flags are applied by the caller.
    """
    root = Path.cwd() if cwd is None else Path(cwd)
    path = Path(config_path) if config_path is not None else root / "config.toml"
    payload = _defaults()

    if path.is_file():
        _overlay_toml(payload, path)
    elif config_path is not None:
        raise ConfigError(f"config file not found: {path}")

    try:
        settings = Settings.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc

    model = os.environ.get("OLLAMA_MODEL", "").strip()
    base_url = os.environ.get("OLLAMA_BASE_URL", "").strip()
    updates: dict[str, str] = {}
    if model:
        updates["model"] = model
    if base_url:
        updates["base_url"] = base_url
    if updates:
        settings = settings.model_copy(update=updates)
    return settings


def _defaults() -> dict[str, object]:
    return {
        "base": "main",
        "max_diff_bytes": 200_000,
        "max_files": 0,
        "parse_retries": 1,
        "provider_name": "ollama",
        "model": "",
        "base_url": DEFAULT_OLLAMA_BASE_URL,
        "timeout_seconds": 120.0,
        "report_format": "markdown",
        "fail_on_severity": "none",
        "exclude_globs": list(DEFAULT_EXCLUDE_GLOBS),
    }


def _overlay_toml(payload: dict[str, object], path: Path) -> None:
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid config file {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigError(f"invalid config file {path}: expected a table")

    review = _section(loaded, "review")
    _copy_keys(
        payload,
        review,
        ("base", "max_diff_bytes", "max_files", "parse_retries"),
    )

    provider = _section(loaded, "provider")
    if "name" in provider:
        payload["provider_name"] = provider["name"]
    _copy_keys(payload, provider, ("model", "base_url", "timeout_seconds"))

    report = _section(loaded, "report")
    if "format" in report:
        payload["report_format"] = report["format"]
    if "fail_on_severity" in report:
        payload["fail_on_severity"] = report["fail_on_severity"]

    security = _section(loaded, "security")
    globs = security.get("exclude_globs")
    if globs is not None:
        if not isinstance(globs, list) or not all(
            isinstance(item, str) for item in globs
        ):
            raise ConfigError("security.exclude_globs must be a list of strings")
        payload["exclude_globs"] = list(globs)


def _section(loaded: dict[str, object], name: str) -> dict[str, object]:
    raw = loaded.get(name, {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config section [{name}] must be a table")
    return raw


def _copy_keys(
    payload: dict[str, object],
    source: dict[str, object],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if key in source:
            payload[key] = source[key]
