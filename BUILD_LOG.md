# DocSentry Build Log

## Part 0 — Environment Setup ✅

### Completed:
- [x] Created `docsentry/` project folder
- [x] Created Python virtual environment (`.venv`) with Python 3.11.9
- [x] Upgraded pip to latest
- [x] Installed all 14 Python dependencies (fastapi, uvicorn, anthropic, gitpython, PyGithub, tree-sitter, tree-sitter-python, sentence-transformers, chromadb, python-dotenv, pydantic, pydantic-settings, httpx, pytest)
- [x] Created `.env` with API keys (Anthropic + GitHub PAT)
- [x] Created `.gitignore`
- [x] Created `__init__.py` files in all subpackages
- [x] Created `docsentry-testbed` repo on GitHub (mannas632006/docsentry-testbed)
- [x] Cloned testbed repo as sibling directory
- [x] Created `calculator.py` and `README.md` in testbed with initial documented code
- [x] Pushed initial commit to testbed
- [x] Initialized git in `docsentry/` project
- [x] Sanity check: all packages import OK, all env vars set, testbed repo found

### Changes from guide:
- None — followed the guide exactly

### User-provided:
- GitHub Username: mannas632006
- GitHub PAT: provided
- Anthropic API Key: provided

## Part 1 — Diff Analyzer ✅
- [x] `config.py`, `core/git_ops.py`, `agents/diff_analyzer.py` (tree-sitter signature diffing)
- [x] `tests/test_diff_analyzer.py` passes

## Part 2 — Code↔Doc Linker ✅
- [x] `core/parser.py` (markdown → sections), `core/vector_store.py` (ChromaDB + all-MiniLM-L6-v2)
- [x] `agents/doc_linker.py` (hybrid dense + exact-name boost)
- [x] `tests/test_doc_linker.py` passes (validated: reindex = 4 sections, top hit = README divide, exact=True)

## Part 3 — Divergence Detector ✅
- [x] `agents/divergence.py`

## Part 4 — Agentic Actions ✅
- [x] `agents/auto_fixer.py` (branch → patch → push → PR via GitPython + PyGithub)
- [x] `agents/alerter.py` (opens "Docs Lie" issue; `labels=` dropped to avoid missing-label 422)
- [x] `agents/verifier.py` (re-runs divergence on the patched doc)
- [x] `pipeline.py` (PERCEIVE → REASON → ACT → VERIFY; `python -m docsentry.pipeline`)

## Part 5 — Webhook Server + Dashboard ✅
- [x] `core/db.py` (SQLite run history — fixed guide bug: `r["commit"]` → `r["commit_hash"]`)
- [x] `main.py` (FastAPI: signed `/webhook/github`, `/api/runs`, `/api/stats`, self-branch skip guard)
- [x] `dashboard/` (hand-scaffolded Vite + React: package.json, vite.config.js, index.html, src/main.jsx, src/App.jsx). Run `npm install && npm run dev`.

## Part 6 — Polish & Ship ✅
- [x] `Dockerfile`, `cli.py` (`python -m docsentry.cli init`), `requirements.txt` (pip freeze)

---

## KEY DEVIATIONS FROM GUIDE

1. **LLM = local Ollama, not Anthropic API.** The Anthropic key ran out of credits (400: "credit balance is too low"). `agents/divergence.py` now uses the `openai` client pointed at `http://localhost:11434/v1` with model `orca-mini:latest` (see `divergence_model` in `config.py`). Zero API credits; requires Ollama running locally. `config.py` no longer requires `anthropic_api_key`.
2. **Dashboard hand-scaffolded** instead of `npm create vite` (avoids a large interactive download). Fully runnable after `npm install`.
3. **Alerter drops `labels=`** so the first issue doesn't 422 on a non-existent label.

## HOW TO RUN (launch-environment note)

The package dir and project root are the same folder (flattened, no nested `docsentry/docsentry/`). So `import docsentry` needs the PARENT on the path, while the relative paths (`../docsentry-testbed`, `./chroma_db`, `docsentry.db`) assume CWD = the `docsentry/` folder. Working invocation (matches how pytest runs):

```bash
cd docsentry
PYTHONPATH=.. .venv/Scripts/python -m docsentry.pipeline           # full agent on latest testbed commit
PYTHONPATH=.. .venv/Scripts/python -m docsentry.cli init           # index docs
PYTHONPATH=.. .venv/Scripts/python -m uvicorn docsentry.main:app --port 8000
```

Validated so far (no GitHub side effects): imports of full graph OK, DB round-trip OK, reindex=4, doc-linker exact match OK, Ollama reachable (HTTP 200) and `orca-mini:latest` present.

## LIVE RUN — SUCCESS (2026-07-04)

- **Ollama JSON fix:** `orca-mini` understood divergence but replied in prose → parser fell back to "clean". Fixed `divergence.py` to (a) send `response_format={"type":"json_object"}` (Ollama honors it) and (b) use `_parse_verdict()` which strips fences and extracts the first `{...}` block, with typed coercion. Now returns `diverged=True, confidence≈0.5`.
- **Full pipeline ran** `python -m docsentry.pipeline` on testbed commit `cffe6c2` ("Change divide default to unsafe"). Result: opened real GitHub issues **#1 and #2** on `mannas632006/docsentry-testbed` (one `low_confidence_skip` in between). The agent judges each of the top-3 linked doc sections independently, so one code change can raise multiple alerts.
- **Server verified:** `uvicorn docsentry.main:app --port 8000` → `/api/stats` = `{total_runs:1, alerted:2}`, `/api/runs` returns the run, `/docs` = 200. Run persisted to `docsentry.db`.

## OUTSTANDING (as of v1)

- **Dashboard needs Node.js 20+** (not installed). Source is complete under `dashboard/`. After installing Node: `cd docsentry/dashboard && npm install && npm run dev` → http://localhost:5173 (server must be running for data).
- **Confidence tuning:** orca-mini caps around 0.5, so everything routes to *alert* (issue), never *auto-fix* (needs ≥0.85). To see auto-fix PRs, lower `AUTOFIX_THRESHOLD` in `.env` or use a stronger local model. The multi-alert-per-change noise can be reduced by having the pipeline act only on the single top doc.

---

# v2 — Runnable, Deployable, Tested (2026-07-17)

Everything above is the v1 record and is kept as history. Both outstanding items are resolved
below.

## Starting state

The project did not run. Not "had bugs" — could not start:

- **No `.env`, and `config.py` had no defaults** for `github_token` / `target_repo` /
  `local_repo_path`, so `Settings()` raised at *import*. Every module that imported config died.
- **`import docsentry` was impossible.** Every file imported `docsentry.*`, but the folder was
  named `docsentry-github` — not a valid Python identifier — and no package of that name existed.
  The documented `PYTHONPATH=.. python -m docsentry.pipeline` could not have worked.
- **The testbed was gone.** `../docsentry-testbed` did not exist, so all three tests and the whole
  pipeline pointed at nothing.
- **Not a git repo.** No `.git`, despite the folder name.
- **`Dockerfile` couldn't build** — `COPY docsentry/ docsentry/` referenced a path that didn't exist.
- **`test_divergence` asserted `confidence >= 0.7`** against a model this log records as capping at
  0.5. It was documented to fail.

## Changes

**Layout.** Flattened the repo (was nested under `docsentry-github/`), moved the package into
`docsentry/` — the layout every import already assumed — and added `pyproject.toml`. Deleted dead
`api/` and `webhooks/` packages, the stale `check_deps.py`/`check_setup.py` (still probing for the
long-removed anthropic key), and two committed pytest output dumps.

**LLM = Groq, provider is config.** v1's second pivot (Anthropic → Ollama) hardcoded
`localhost:11434`, which meant it could only ever run on a laptop. New `docsentry/llm` speaks to
`groq` | `gemini` | `ollama` — all OpenAI-compatible, so it's a config value. Measured on the
canonical flipped-default case: `orca-mini` caps at ~0.5 (never auto-fixes), **`llama3.2:1b` misses
the drift entirely and reports *clean***, Groq's `llama-3.3-70b-versatile` detects it with
calibrated confidence. Verdict quality is the product; Groq's free tier costs nothing.

**Retrieval = BM25.** Dropped ChromaDB + sentence-transformers, which dragged in PyTorch (~800MB
installed) — no free tier accepts that. BM25 is also a better fit: the signal is the literal token
`divide`, and unlike a vector store it returns *nothing* when nothing matches. Chroma kept behind
the `[chroma]` extra.

**Bugs found and fixed** (several latent — waiting for a capable model to trigger them):

1. **The doc-eating splice.** The prompt asked for "ONLY the false lines"; `auto_fixer` spliced
   that over the section's *whole* line range. A one-line fix would have deleted the rest of the
   section. Never fired only because confidence never reached 0.85.
2. **The fail-open verifier.** `return not recheck["diverged"]` — an LLM error gives
   `diverged=False`, so an outage read as a PASS, shipping an unverified fix exactly when the
   verifier was broken.
3. **Code fences parsed as headings** — `# comment` inside a ```python block split sections, in
   docs that are mostly code samples.
4. **`default_changed` never emitted** despite being declared and being the flagship demo case.
5. **Method collisions** — functions keyed by bare name, so `Foo.divide` overwrote `Bar.divide`.
6. **Root commits inverted** — `commit.diff(None)` compares against the working tree, not the empty
   tree.
7. **Duplicate issues** — top-3 docs judged *and acted on*; plus no dedup across runs.
8. **Stranded checkouts** — no `try/finally` around the fix branch.
9. **CWD-dependent database** — bare relative `docsentry.db`.
10. **`UnicodeEncodeError` on Windows** — printing a finding containing `→` crashed the CLI on a
    cp1252 console. Found by running it, not by the tests.
11. **`AttributeError` on remoteless repos** — `repo.remotes.origin` raises `AttributeError`, not
    `GitCommandError`, so it slipped the error handling. Also found by running it.

**Deployability.** Runtime clone (a host has no sibling checkout); absolute paths from the package
location; `/health` that reports readiness instead of crashing; write endpoints disabled unless
`admin_token` is set; fixed multi-stage Dockerfile; `render.yaml`; `vercel.json`.

**Interface.** Rewrote the dashboard: filtering, free-text search, pagination, run detail with
confidence meters and the proposed fix, manual trigger with per-run threshold overrides, settings
panel (API URL + admin token, stored per browser), health indicator, light/dark theme, configurable
auto-refresh, and real empty/loading/error states.

**Tests.** 152 hermetic tests, ~20s, no network and no API key. Fixtures build a real git repo per
test and script the model.

## Verified

- `docsentry doctor` → READY (77 sections indexed from this repo)
- `docsentry run --dry-run` against a rebuilt calculator testbed → full loop with a live LLM
- API driven end to end: signature rejection (401), ping, own-branch skip, signed push queues,
  stats, filters, search, run detail, admin guard (401/403)
- Render-style UPPERCASE env vars bind to the lowercase settings fields
- `npm run build` → 53KB gzipped
- UTF-8 round-trips through SQLite and JSON

## Outstanding

- **The Groq path is unverified end to end** — no API key was available at the time of writing. All
  other providers and the full pipeline were exercised. Add `llm_api_key` and run
  `docsentry doctor`.
- **`DocSentry_Documentation.docx` is stale** — it predates v2 and describes the v1 architecture
  (ChromaDB, local-only LLM). Regenerate it from `DOCUMENTATION.md` if it's still needed.