# 🛡️ DocSentry

**An autonomous agent that keeps documentation honest.** When code changes in a way that makes
the docs *lie* — a flipped default, a renamed function, a changed signature — DocSentry detects it,
opens a GitHub issue (or a fix PR), and verifies its own fix. Powered by a **local, zero-credit LLM**.

> *"The docs defended themselves."*

---

## Why

Documentation drifts. Code changes, prose doesn't, and the README silently becomes false. CI can't
catch it — the code compiles and tests pass, but the *words* now lie. DocSentry watches a repo and,
on every push, asks: *"Does any documentation still make a claim this change just made false?"*

## How it works

A classic **PERCEIVE → REASON → ACT → VERIFY** agent loop:

```
push → diff_analyzer (tree-sitter AST) → doc_linker (ChromaDB RAG)
     → divergence (local LLM) → confidence router → fix PR / alert issue
     → verifier (self-check) → SQLite → FastAPI → React dashboard
```

- **Perceive:** tree-sitter parses before/after code into ASTs and compares *function signatures* —
  not text lines — so cosmetic edits are ignored.
- **Reason:** relevant doc sections are retrieved from a local vector store, then a local LLM judges
  whether the doc now lies, returning strict JSON.
- **Act:** confidence ≥0.85 → auto-fix PR; 0.50–0.84 → "Docs Lie" issue; below → skip.
- **Verify:** the agent re-checks its own fix before shipping it.

See **[DOCUMENTATION.md](DOCUMENTATION.md)** for the full technical deep-dive.

## Tech stack

tree-sitter · GitPython · ChromaDB · sentence-transformers · **Ollama (local LLM)** · PyGithub ·
FastAPI · SQLite · React + Vite

## Quick start

```bash
# 1. Python env + deps
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# 2. Local LLM
ollama pull orca-mini

# 3. Config
cp .env.example .env            # then fill in your GitHub token + target repo

# 4. Run the agent on the latest commit of the watched repo
#    (run from inside this folder with the parent on PYTHONPATH)
PYTHONPATH=.. python -m docsentry.cli init
PYTHONPATH=.. python -m docsentry.pipeline
```

### Live server + dashboard

```bash
# Terminal 1 — API + webhook receiver
PYTHONPATH=.. python -m uvicorn docsentry.main:app --port 8000

# Terminal 2 — dashboard
cd dashboard && npm install && npm run dev   # http://localhost:5173
```

Expose the server with a tunnel (`ngrok http 8000`) and add a GitHub webhook pointing at
`<tunnel>/webhook/github` (content type `application/json`, secret = `WEBHOOK_SECRET`, push events).

## Project layout

```
docsentry/
├── agents/          diff_analyzer, doc_linker, divergence, auto_fixer, alerter, verifier
├── core/            git_ops, parser, vector_store, db
├── main.py          FastAPI webhook + dashboard API
├── pipeline.py      the full perceive→reason→act→verify loop
├── cli.py           `python -m docsentry.cli init`
├── dashboard/       React + Vite live dashboard
├── tests/           pytest suite
├── Dockerfile
└── DOCUMENTATION.md full technical docs
```

## Notes

- **Zero API cost:** the LLM (Ollama) and embeddings (`all-MiniLM-L6-v2`) both run locally. Nothing
  is sent to a third-party API — a privacy win as well as a cost win.
- **Python + Markdown** for now; other languages/doc formats are a documented extension point.
- Requires a local [Ollama](https://ollama.com) install and a small model (`orca-mini`).

## STEP-BY-STEP GUIDE TO RUN DocSentry

### 0. Install the prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Python | 3.11+ | the agent |
| Node.js | 20+ | the dashboard only |
| Ollama | latest | the local LLM brain — ollama.com |
| Git | any | cloning + the agent's GitHub actions |

Plus a GitHub account and a fine-grained Personal Access Token scoped to the repo they want to watch (Contents / Issues / Pull requests / Webhooks → read & write).

---

### 1. Get the code + a repo to watch

DocSentry watches another repo, and the path is relative, so the layout matters:

```text
some-folder/
├── docsentry/           ← this project (cloned)
└── docsentry-testbed/   ← the repo it watches (SIBLING, not inside)
```

```bash
git clone https://github.com/mannas632006/docsentry.git
git clone https://github.com/<their-user>/<repo-to-watch>.git   # the sibling
```

---

### 2. Python environment

```bash
cd docsentry
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell
pip install -r requirements.txt   # ~2GB (pulls PyTorch); be patient
```

Windows gotcha: if activation errors with **"running scripts is disabled,"** run once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

### 3. The local LLM

```bash
ollama pull orca-mini
```

Make sure Ollama is running (it serves on localhost:11434). It needs ~2 GB free RAM to load the model.

---

### 4. Configuration

```bash
cp .env.example .env      # copy, then edit .env
```

Fill in: `github_token`, `target_repo` (e.g. `their-user/docsentry-testbed`), and confirm `local_repo_path=../docsentry-testbed` points at the sibling.

---

### 5. Run the agent (the proof-of-life)

Run from inside `docsentry/` with the parent on the path — this is the one non-obvious part:

```powershell
# Windows PowerShell
$env:PYTHONPATH = ".."
.venv\Scripts\python -m docsentry.cli init        # index the watched repo's docs
.venv\Scripts\python -m docsentry.pipeline        # run the full agent on the latest commit
```

```bash
# macOS/Linux
PYTHONPATH=.. python -m docsentry.pipeline
```

If the watched repo has a doc that a recent commit made false, this opens a real issue/PR on it. That's the whole thing working.

---

### 6. (Optional) Live server + dashboard

```powershell
# Terminal 1 — API + webhook receiver
$env:PYTHONPATH = ".."
.venv\Scripts\python -m uvicorn docsentry.main:app --port 8000
```

```bash
# Terminal 2 — dashboard
cd dashboard
npm install                 # if npm blocks esbuild's script: npm approve-scripts esbuild
npm run dev                 # http://localhost:5173
```

To make pushes trigger it automatically: expose the server with `ngrok http 8000` and add a GitHub webhook → `<tunnel-url>/webhook/github` (content type `application/json`, secret = your `WEBHOOK_SECRET`, "just the push event").

## Made By: Muhammad Anas (MM) --- For any assistance or complaints, Contact me at f240576@cfd.nu.edu.pk
