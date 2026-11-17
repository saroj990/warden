# Eval sandbox (local, gitignored)

Warden’s labeled fixtures live under `tests/fixtures/eval/`. For **real git
diffs** and future **GitHub PRs**, maintain a separate mini repo on disk:

`local-eval-sandbox/warden-targets/` (not tracked by this repository).

## Bootstrap

The sandbox is created beside the agent checkout. If missing, copy structure from
this doc or re-run setup from the Phase 1 plan in `issues/001-review-reliability-and-coverage.md`.

```bash
warden review \
  --repo "$(pwd)/local-eval-sandbox/warden-targets" \
  --base master --head feature/planted-defects \
  --model qwen3:8b --timeout 600 --stream
```

## Branches

- **`master`** — correct billing, env-based webhook token, safe paths, `shell=False`.
- **`feature/planted-defects`** — five intentional defects (see sandbox `README.md`).

## Regression checks (Phase 1)

Heuristic, diff-backed rules live in `src/pr_review/checks/regression.py`. Enable for review:

```toml
# config.toml
[checks]
regression_enabled = true
```

Eval:

```bash
warden eval --regression-checks --model YOUR_MODEL --timeout 600
```

Per-rule labeled diffs are under `tests/fixtures/eval/{discount-percent,...}/`.

## Baseline

See [eval-baseline.md](eval-baseline.md) for the measurement table and commands.

Push the sandbox to its own GitHub repo when ready; use `warden github review` the
same way as any other project.