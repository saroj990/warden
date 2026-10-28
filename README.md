# pr-review-agent

Local-first CLI that reviews Git diffs for **real, newly introduced defects**, with evidence-backed findings. Designed to run against a local working tree first (Ollama), and later integrate with GitHub and Bitbucket without rewriting the core engine.

> **Status:** Project scaffold only. The review pipeline is not implemented yet.

## Requirements

- Python 3.11+
- (Later) a local [Ollama](https://ollama.com) install for model inference

## Setup

```bash
python3 -m venv .venv  # or: python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Optional config templates:

- `.env.example` → copy to `.env`
- `config.example.toml` → copy to `config.toml`

## CLI (current)

```bash
pr-review --help
pr-review --version
pr-review doctor
```

## Tests

```bash
pytest
```

## Roadmap (high level)

1. Unified diff parser + unit tests
2. Finding schema and validator
3. Ollama provider + mocked tests
4. Local review pipeline and Markdown/JSON reports
5. Context gathering, evaluation harness
6. GitHub / Bitbucket adapters (opt-in publish, dry-run by default)

## Security notes

- Local mode must not send source to a remote provider unless you explicitly select one.
- Do not commit secrets; use environment variables.
- The agent must not modify, commit, push, or merge code by default.
