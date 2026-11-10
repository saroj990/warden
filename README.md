# pr-review-agent

Local-first CLI that reviews Git diffs for **real, newly introduced defects**, with evidence-backed findings. Designed to run against a local working tree first (Ollama), and later integrate with GitHub and Bitbucket without rewriting the core engine.

> **Status:** Local reviews work against a git diff or a saved unified diff. When a work tree is available, the pipeline loads surrounding source lines around changed hunks and searches the repo for definitions and callers of symbols added in the diff. It asks the configured Ollama model for findings, drops anything the diff does not support, and writes Markdown or JSON. `warden eval` scores that pipeline against labeled fixture diffs. `warden github review` can preview comments on a pull request and posts them only with `--publish`. Bitbucket is not implemented yet.

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
warden --help
warden --version
warden doctor

# Working tree, including staged and unstaged changes, against a base revision.
# Untracked files are not included. Requires a local Ollama model.
warden review --repo . --base main --model <installed-model>

# Committed range from the merge base of base and head.
warden review --repo . --base main --head HEAD --model <installed-model>

# Saved diff, JSON report. A run with no published findings says
# "No actionable findings identified" and does not claim the change is defect-free.
warden review --diff ./changes.diff --model <installed-model> \
  --format json --output ./review.json

# Score the built-in labeled diffs. Exit 1 when a defect is missed or a
# clean or suppressed case publishes a finding. Context is not loaded.
# Results depend on the model.
warden eval --model <installed-model> --timeout 180

# Preview GitHub pull request comments. This does not post anything.
# GITHUB_TOKEN is required and is not printed. Add --publish to post a
# COMMENT review. The command never approves or merges.
warden github review --repository owner/name --pr 123 \
  --model <installed-model> --timeout 180
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
