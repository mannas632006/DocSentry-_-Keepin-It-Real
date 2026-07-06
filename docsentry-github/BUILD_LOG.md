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

## OUTSTANDING

- **Dashboard needs Node.js 20+** (not installed). Source is complete under `dashboard/`. After installing Node: `cd docsentry/dashboard && npm install && npm run dev` → http://localhost:5173 (server must be running for data).
- **Confidence tuning:** orca-mini caps around 0.5, so everything routes to *alert* (issue), never *auto-fix* (needs ≥0.85). To see auto-fix PRs, lower `AUTOFIX_THRESHOLD` in `.env` or use a stronger local model. The multi-alert-per-change noise can be reduced by having the pipeline act only on the single top doc.