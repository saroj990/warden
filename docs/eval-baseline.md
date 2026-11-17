# Eval baseline (Phase 1)

Track recall on **labeled fixtures** and on the **gitignored sandbox** without guessing.

## Fixture suite (`tests/fixtures/eval/`)

| Case | Kind | What it exercises |
|------|------|-------------------|
| `discount-percent` | defect | Percent scaling regression (Phase 1.2 heuristic) |
| `money-format-cents` | defect | Cents displayed as dollars |
| `hardcoded-secret` | defect | Credential in source |
| `shell-true` | defect | `subprocess` shell injection |
| `path-escape` | defect | Removed path jail |
| `none-deref` | defect | Model must find None deref |
| `prompt-injection` | suppress | Must not publish |
| `rename-local` | clean | Must not publish |

### Commands

**Unit (no Ollama)** — regression fixtures must pass with checks only:

```bash
pytest tests/unit/test_eval.py tests/unit/test_regression_checks.py -q
```

**Live eval** — model + optional heuristics:

```bash
# Model-only (original three cases need the LLM)
warden eval --model qwen3:8b --timeout 600

# Enable regression heuristics (helps numeric/security fixtures; still calls the model)
warden eval --model qwen3:8b --timeout 600 --regression-checks
```

Or in `config.toml`:

```toml
[checks]
regression_enabled = true
```

## Sandbox (`local-eval-sandbox/warden-targets/`)

| Branch | Purpose |
|--------|---------|
| `master` | Clean baseline |
| `feature/planted-defects` | Five planted bugs (integration-style) |

```bash
warden review \
  --repo "$(pwd)/local-eval-sandbox/warden-targets" \
  --base master --head feature/planted-defects \
  --model qwen2.5-coder:14b --timeout 600
```

Enable checks in config or add `checks_regression_enabled` via future CLI flag on `review` if needed; today use `config.toml` `regression_enabled = true`.

### Baseline table (fill when you measure)

| Date | Model | Sandbox published / 5 | `warden eval` defect pass | Notes |
|------|-------|------------------------|---------------------------|-------|
| | qwen2.5-coder:14b | 4/5 (model only) | | missed `apply_discount` before Phase 1 |
| | | | | |

**Success bar (Phase 1):** sandbox **≥4/5** with model + checks; five regression **fixture** cases pass in pytest with checks only; `none-deref` / clean / suppress unchanged.