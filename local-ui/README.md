# Local review UI

Simple browser form for **`warden review`** against a git repo (Ollama). Not part of the
installable package — run from a clone where `pr_review` is installed.

## Run

```bash
source .venv/bin/activate   # from repo root
pip install -e ".[dev]"     # if needed
python local-ui/server.py
```

Open http://127.0.0.1:8765/

The report **Preview** tab renders Markdown in the browser (loads marked.js from CDN
on first page load; use **Source** for raw text if offline).

- **Source** — local folder, or **GitHub** (`owner/repo` or URL). GitHub repos are
  cloned/updated under `local-ui/cache/repos/`. Private repos need `GITHUB_TOKEN` in the
  server env or the optional token field (not saved in `form.json`).
- **Base** — compare against this ref (e.g. `main`, `master`). Match names that exist in
  the repo (many use `master`, not `main`).
- **Head** — optional for local repos (empty = working tree vs base). **Required** for
  GitHub (branch-to-branch compare only).
- **Stream** — prints model tokens in the **terminal** running `server.py`, not in the browser.
- **Refresh model list** — calls Ollama `GET /api/tags` on the host URL you enter (localhost or remote).
- **Compare selected** — same diff/settings for up to **3** checked models; runs **one model at a time**
  (queued columns show “Waiting” / “Queued (N ahead)”). Results appear in a 3-column grid.
- **Review (single model)** — uses the dropdown / Other field; classic single report + Save.
- **Save** — writes Markdown under `local-ui/reports/` (single-model review only).

Reviews run in a **background job**: the browser polls every ~1.5s so long Ollama
runs do not drop the HTTP connection. Streamed tokens still appear in the server
terminal when stream is enabled.

Form values persist in `form.json` (gitignored).
