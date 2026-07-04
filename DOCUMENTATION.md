# DocSentry — Technical Documentation

> An autonomous agent that keeps documentation honest. When code changes in a way
> that makes the docs *lie*, DocSentry detects it, opens a GitHub issue (or a fix PR),
> and verifies its own fix — all driven by a **local, zero-credit LLM**.

---

## Table of Contents
1. [What it is & the use case](#1-what-it-is--the-use-case)
2. [How it works (architecture)](#2-how-it-works-architecture)
3. [The agentic loop, module by module](#3-the-agentic-loop-module-by-module)
4. [Confidence-based routing](#4-confidence-based-routing)
5. [How it was made](#5-how-it-was-made)
6. [Flow, tokenization & credit optimization](#6-flow-tokenization--credit-optimization)
7. [Data contracts](#7-data-contracts)
8. [Running it](#8-running-it)
9. [Security model](#9-security-model)
10. [Limitations & known trade-offs](#10-limitations--known-trade-offs)
11. [Future improvements](#11-future-improvements)
12. [FAQ](#12-faq)
13. [Glossary](#13-glossary)

---

## 1. What it is & the use case

### The problem
Documentation drifts. A developer flips a default (`safe=True` → `safe=False`), renames a
function, or changes a signature — and the README that describes the old behavior silently
becomes **false**. Nobody notices until a user follows the docs and gets burned. Traditional
CI can't catch this: the code compiles, the tests pass, but the *prose* now lies.

### The use case
DocSentry watches a repository. On every push it asks a single question for each code change:

> *"Does any documentation still make a claim this change just made false?"*

If yes, it acts:
- **High confidence** → opens a pull request that patches the doc.
- **Medium confidence** → opens a "Docs Lie" issue for a human to review.
- **Low confidence** → logs and moves on (no noise).

**Who it's for:** teams whose docs are the product (SDKs, APIs, developer tools, OSS libraries),
where a lying README erodes trust faster than a bug. Also a strong portfolio/learning project
for understanding **agentic AI** — it implements every stage of the agent loop as a separate,
inspectable module.

### The demo in one sentence
Flip `safe=True` to `safe=False` in the testbed, push, and within seconds a GitHub issue appears,
authored by the agent, pointing at the exact README line that is now a lie. *"The docs defended themselves."*

---

## 2. How it works (architecture)

DocSentry is a classic **PERCEIVE → REASON → ACT → VERIFY** agent. Each arrow is a module.

```
 GitHub push
     │
     ▼
┌─────────────┐   PERCEIVE
│  webhook    │   main.py verifies HMAC signature, pulls the repo,
│  (FastAPI)  │   hands the commit hash to the pipeline
└──────┬──────┘
       ▼
┌─────────────┐   PERCEIVE
│ diff_       │   GitPython pulls before/after file blobs;
│ analyzer    │   tree-sitter parses BOTH into ASTs and compares
│ (AST diff)  │   function *signatures* → a semantic ChangeReport
└──────┬──────┘
       ▼
┌─────────────┐   REASON (retrieve)
│ doc_linker  │   embeds the change, queries ChromaDB for the
│ (hybrid RAG)│   top-N doc sections + exact-name keyword boost
└──────┬──────┘
       ▼
┌─────────────┐   REASON (judge)
│ divergence  │   local LLM (Ollama) returns strict JSON:
│ (LLM brain) │   { diverged, confidence, mismatch, suggested_fix }
└──────┬──────┘
       ▼
   confidence router
   ┌────────────┬─────────────┬────────────┐
   ▼            ▼             ▼            
 ≥0.85        0.50–0.84      <0.50         ACT
 auto_fixer   alerter        skip
 (fix + PR)   (issue)
   │
   ▼
┌─────────────┐   VERIFY
│ verifier    │   re-runs divergence on the PATCHED doc;
│ (self-check)│   if it still lies → downgrade PR to an issue
└──────┬──────┘
       ▼
   SQLite history  →  FastAPI /api/runs  →  React dashboard (live)
```

### Tech stack
| Layer | Choice | Why |
|---|---|---|
| Code understanding | **tree-sitter** (`tree-sitter-python`) | Real AST parsing — understands *structure*, not text lines |
| Git access | **GitPython** | Before/after blobs for any commit, no shelling out |
| Retrieval | **ChromaDB** + **sentence-transformers** (`all-MiniLM-L6-v2`) | Local vector search; no embedding API cost |
| LLM brain | **Ollama** (`orca-mini`) via OpenAI-compatible client | **Zero API credits**, fully local |
| Actions | **PyGithub** | Opens issues/PRs on the target repo |
| Server | **FastAPI** + **uvicorn** | Async webhook receiver + dashboard API |
| Persistence | **SQLite** (stdlib) | Zero-config run history |
| Dashboard | **React** + **Vite** | Live-polling view of every run |
| Config | **pydantic-settings** | Typed `.env` loading |

---

## 3. The agentic loop, module by module

### `core/git_ops.py` — PERCEIVE (raw)
`get_commit_changes(repo, hash)` diffs a commit against its parent and returns a list of
`FileChange(path, change_type, before, after)` — the full text of each touched file *before*
and *after*. This is the only place raw file content is read.

### `agents/diff_analyzer.py` — PERCEIVE (semantic)
The heart of the "understanding." Instead of diffing text lines, it:
1. Parses both versions with tree-sitter into ASTs.
2. Extracts a `FunctionSig(name, params, docstring)` snapshot for every function.
3. Compares snapshots and emits `SemanticChange` objects: `function_added`, `function_removed`,
   `params_changed`, `docstring_changed`.

**Why this matters:** a whitespace or comment change produces *zero* semantic changes, so the
expensive downstream LLM is never called for noise. Only meaningful structural changes flow on.

### `core/parser.py` + `core/vector_store.py` — REASON (retrieve)
- `parser.py` splits every markdown file into heading-anchored `DocSection`s (with line ranges).
- `vector_store.py` embeds each section locally and stores it in ChromaDB. `reindex()` rebuilds
  the index; `search(query, n)` returns the top-N most similar sections.

### `agents/doc_linker.py` — REASON (retrieve, hybrid)
`link_change_to_docs(change)` builds a query from the changed function's name + the human-readable
detail, runs the vector search, then applies an **exact-name keyword boost**: any section that
literally mentions the function name is ranked above pure-similarity hits. This hybrid approach
(dense embeddings + sparse keyword signal) makes a small `n` (3) reliable.

### `agents/divergence.py` — REASON (judge) — the brain
Sends the change + one doc section to the local LLM and demands strict JSON:
```json
{ "diverged": true, "confidence": 0.0-1.0, "mismatch": "...", "suggested_fix": "..." }
```
Robustness built in:
- `response_format={"type": "json_object"}` forces the model to emit JSON (small models otherwise
  reply in prose).
- `_parse_verdict()` strips code fences, extracts the first `{...}` block if the model wraps it in
  text, and coerces types — so a chatty model never crashes the pipeline.
- Uses the **OpenAI client pointed at Ollama** (`http://localhost:11434/v1`), so it costs nothing.

### `agents/auto_fixer.py` — ACT (autonomous)
For high-confidence verdicts: creates a `docsentry/fix-<timestamp>` branch, replaces the offending
doc lines with `suggested_fix`, commits, pushes, and opens a PR via PyGithub. Returns to the base
branch so the working tree stays clean.

### `agents/alerter.py` — ACT (human-in-the-loop)
For medium confidence: opens a "📄🔥 Docs Lie" issue with the code change, the suspected lie, the
confidence score, and a suggested fix. (Labels were intentionally dropped so a fresh repo without
predefined labels doesn't 422.)

### `agents/verifier.py` — VERIFY (self-check)
Before a fix ships, re-runs `check_divergence` on the *patched* content. If the doc still lies,
the auto-fix is downgraded to an issue. This is the guardrail against LLM overconfidence — the
agent grades its own homework before submitting it.

### `pipeline.py` — the orchestrator
Wires all of the above into `run_pipeline(commit_hash)` and returns a list of result dicts
(`auto_fixed` / `alerted` / `clean` / `low_confidence_skip` / `fix_failed_verification`).
Runnable standalone: `python -m docsentry.pipeline`.

### `main.py` — the server
FastAPI app exposing:
- `POST /webhook/github` — HMAC-verified push receiver; skips the agent's own fix branches to
  prevent infinite self-triggering; runs the pipeline as a background task.
- `GET /api/runs` — recent run history from SQLite.
- `GET /api/stats` — aggregate counts for the dashboard tiles.

---

## 4. Confidence-based routing

The single most important design idea: **thresholded autonomy**. The agent doesn't act with the
same authority on every verdict — it scales its autonomy to its certainty.

| Confidence | Action | Rationale |
|---|---|---|
| **≥ 0.85** (`AUTOFIX_THRESHOLD`) | Auto-fix → open PR (after self-verify) | Certain enough to propose a concrete change |
| **0.50 – 0.84** (`ALERT_THRESHOLD`) | Alert → open issue | Probably wrong, but a human should decide |
| **< 0.50** | Log & skip | Too uncertain to be worth anyone's attention |

Both thresholds are tunable in `.env`. With the small local `orca-mini` model, verdicts cap around
~0.5, so everything currently routes to **alert** — a deliberate, safe default. Lowering
`AUTOFIX_THRESHOLD` (or swapping in a stronger local model) unlocks auto-fix PRs.

---

## 5. How it was made

Built in six phases, each ending in a runnable checkpoint (test-driven, "always working"):

| Phase | Deliverable | Proof of life |
|---|---|---|
| **0** | Env, venv, deps, testbed repo, `.env` | `check_setup.py` all-green |
| **1** | Diff analyzer (tree-sitter) | Detects `divide` default flip |
| **2** | Code↔doc linker (ChromaDB) | Finds the README `divide` section, exact match |
| **3** | Divergence detector (LLM) | Returns `diverged=true` verdict |
| **4** | Agentic actions (fix / alert / verify) | Opens a real GitHub issue/PR |
| **5** | Webhook server + React dashboard | Push → auto-caught, shown live |
| **6** | Dockerfile, CLI, `requirements.txt` | Containerized, one-command onboarding |

### The key pivot: Anthropic → local Ollama
Phase 3 was originally written against the **Anthropic API**. Mid-build the API returned
`400: "credit balance is too low"`. Rather than pay, the LLM layer was rewired to a **local Ollama
model** through the OpenAI-compatible client. This kept the exact same JSON contract while dropping
the per-token cost to **zero**. `config.py` no longer requires an Anthropic key.

### Bugs fixed while building
- `core/db.py`: the run-history query read a non-existent `commit` column → corrected to
  `commit_hash` (would have crashed every dashboard load).
- `agents/alerter.py`: removed `labels=[...]` to avoid a 422 on repos without those labels predefined.
- `agents/divergence.py`: added JSON-mode + a tolerant parser so a small model's prose replies don't
  silently register as "clean."

### Build environment notes
The package folder *is* the project root (flattened layout), so `import docsentry` needs the parent
on `sys.path` while relative paths (`../docsentry-testbed`, `./chroma_db`, `docsentry.db`) assume the
CWD is the `docsentry/` folder. The canonical launch sets `PYTHONPATH=..` from inside `docsentry/`.

---

## 6. Flow, tokenization & credit optimization

This is where DocSentry is deliberately frugal. **Credit/token usage was optimized at every stage
of the pipeline**, not just by picking a cheap model.

### 6.1 The biggest lever: local models = $0
- **LLM inference** runs on **Ollama locally** — no per-token API billing at all.
- **Embeddings** run on **`all-MiniLM-L6-v2` locally** via sentence-transformers — no embedding API.
- Net external LLM/embedding spend: **zero**. The only "budget" is your own CPU/RAM.

### 6.2 Never send code to the model — send *deltas*
The LLM never sees a source file. `diff_analyzer` distills a change into a single human-readable
line like:
```
`divide` signature changed: (a, b, safe=True) → (a, b, safe=False)
```
That one string (a few dozen tokens) replaces what would otherwise be hundreds of tokens of raw
diff. Structural understanding happens in tree-sitter (free), so the model only reasons about the
*meaning*, not the text.

### 6.3 Bound the context with retrieval, don't dump the docs
Instead of sending the entire documentation to the model, `doc_linker` retrieves only the **top-3**
most relevant sections, and the model judges **one section at a time**. Context per call stays tiny
and constant regardless of how large the docs grow.

### 6.4 Hybrid retrieval keeps N small
The exact-name keyword boost means the truly relevant section reliably lands in the top few results,
so `n=3` is enough. Fewer candidate sections → fewer LLM calls per change.

### 6.5 Gate expensive work behind cheap signals
- **AST pre-filter:** whitespace/comment/formatting changes produce zero `SemanticChange`s, so the
  LLM is never invoked for them. Non-`.py` files are skipped outright.
- **Per-commit scoping:** only files touched by the commit are analyzed — never a full-repo scan.
- **Confidence routing:** the extra self-verify LLM call only fires for high-confidence auto-fix
  candidates. The common case (an alert or a clean verdict) costs exactly **one** LLM call.

### 6.6 Tight, structured output
- `max_tokens=800` caps every response.
- `response_format=json_object` eliminates wasted "Here is the JSON you asked for…" preamble tokens
  and prevents costly retries from unparseable prose.

### 6.7 Loop-safety = no wasted runs
The webhook skips pushes on the agent's own `docsentry/fix-*` branches, so an auto-fix PR never
retriggers the whole pipeline on itself — preventing an infinite (and expensive) feedback loop.

### Summary table
| Technique | Where | Saves |
|---|---|---|
| Local Ollama LLM | `divergence.py` | 100% of LLM API cost |
| Local embeddings | `vector_store.py` | 100% of embedding API cost |
| AST delta, not raw code | `diff_analyzer.py` | ~majority of prompt tokens |
| Top-N section retrieval | `doc_linker.py` | Unbounded → constant context |
| AST pre-filter / `.py` skip | `diff_analyzer.py` | Whole LLM calls on noise |
| Per-commit scoping | `git_ops.py` | Full-repo re-analysis |
| Verify only on high-conf | `pipeline.py` | Redundant second call |
| `max_tokens` + JSON mode | `divergence.py` | Output tokens + retries |
| Self-branch skip guard | `main.py` | Infinite self-triggering |

---

## 7. Data contracts

The modules are decoupled by plain dicts, which keeps each stage independently testable.

**SemanticChange** (from `diff_analyzer`):
```python
{ "file": "calculator.py", "kind": "params_changed",
  "name": "divide", "detail": "`divide` signature changed: (...) → (...)" }
```

**Doc hit** (from `doc_linker` / `vector_store.search`):
```python
{ "id": "README.md::7", "content": "...", "distance": 0.31,
  "meta": {"file": "README.md", "heading": "divide(a, b, safe=True)",
           "start_line": 7, "end_line": 11},
  "exact_match": True }
```

**Verdict** (from `divergence`):
```python
{ "diverged": True, "confidence": 0.5,
  "mismatch": "doc claims safe defaults to True, but it now defaults to False",
  "suggested_fix": "...", "doc_id": "...", "doc_file": "...", "doc_heading": "..." }
```

**Run result** (from `pipeline`, stored in SQLite, served to the dashboard):
```python
{ "status": "alerted", "issue": "https://github.com/.../issues/1",
  "change": "`divide` signature changed: (...) → (...)" }
```

---

## 8. Running it

### Prerequisites
- Python 3.11+ with the project `.venv` and deps installed
- **Ollama** running locally with a model pulled: `ollama pull orca-mini`
- Node.js 20+ (only for the dashboard)
- A `.env` with `GITHUB_TOKEN`, `TARGET_REPO`, `LOCAL_REPO_PATH`, `WEBHOOK_SECRET`, thresholds

### One-shot run (CLI)
```powershell
cd docsentry
$env:PYTHONPATH = ".."
.venv\Scripts\python -m docsentry.cli init            # index the docs
.venv\Scripts\python -m docsentry.pipeline            # run the agent on the latest commit
```

### Live server
```powershell
cd docsentry
$env:PYTHONPATH = ".."
.venv\Scripts\python -m uvicorn docsentry.main:app --port 8000
```
Then expose it (`ngrok http 8000`) and register a GitHub webhook → `<tunnel>/webhook/github`
(content type `application/json`, secret = `WEBHOOK_SECRET`, "just the push event").

### Dashboard
```powershell
cd docsentry\dashboard
npm install
npm run dev            # http://localhost:5173
```

### Docker
```powershell
docker build -t docsentry .
docker run --env-file .env -p 8000:8000 -v ${PWD}\..\docsentry-testbed:/repo docsentry
```

---

## 9. Security model

- **Webhook authenticity:** every payload is HMAC-SHA256 verified against `WEBHOOK_SECRET` using
  `hmac.compare_digest` (constant-time). Unsigned or mismatched requests get `401` before any work.
- **Least-privilege token:** the GitHub PAT is fine-grained, scoped to the single target repo, with
  only Contents/Issues/PRs/Webhooks write.
- **Secrets never committed:** `.env`, `chroma_db/`, and `docsentry.db` are gitignored.
- **No data leaves the machine:** because the LLM and embeddings are local, source and docs are never
  sent to a third-party API — a real privacy/compliance advantage over cloud-LLM approaches.

---

## 10. Limitations & known trade-offs

- **Small-model ceiling:** `orca-mini` caps confidence ~0.5, so auto-fix PRs don't trigger under the
  default 0.85 threshold — everything becomes an alert. A stronger local model (or lower threshold)
  changes this.
- **Multi-alert noise:** the pipeline judges the top-3 linked sections independently, so one code
  change can raise more than one issue. Acting only on the single best match would reduce noise.
- **Python-only:** `diff_analyzer` currently parses Python. Other languages need their own
  tree-sitter grammar + an `extract_functions` mirror.
- **Markdown-only docs:** `parser.py` handles `.md`; other doc formats aren't indexed.
- **Function-level granularity:** it reasons about signatures/docstrings, not deep behavioral changes
  inside a function body.
- **Launch sensitivity:** relative paths assume a specific working directory (see §5).

---

## 11. Future improvements

- **Multi-language:** add `tree-sitter-javascript`/`-typescript` and mirror `extract_functions`.
- **Single-best-match mode** to cut alert noise.
- **Absolute path anchoring** in `config.py` so it runs from any directory.
- **Docs Health Score badge** (shields.io endpoint returning % clean).
- **PR-comment mode:** comment on the offending PR instead of opening a new issue.
- **Slack/Discord alerts** via a webhook.
- **Dogfooding:** point DocSentry at its own repo.
- **Model routing:** small local model for triage, escalate only uncertain cases to a stronger model.

---

## 12. FAQ

**Q: Why tree-sitter instead of a plain `git diff`?**
A text diff tells you *lines changed*; tree-sitter tells you a *function's signature changed*. The
agent needs meaning, not lines — and it lets us skip the LLM entirely for cosmetic edits.

**Q: Why a vector database for docs?**
So the model only ever sees the handful of doc sections relevant to a change, not the whole manual.
It bounds context (and cost) and scales to large docs.

**Q: Does it cost money to run?**
No API cost. LLM and embeddings are local via Ollama + sentence-transformers. You only spend CPU/RAM.

**Q: How does it avoid infinite loops?**
Its own fix PRs push to `docsentry/fix-*` branches, and the webhook explicitly ignores those refs.

**Q: What if the model outputs garbage instead of JSON?**
`response_format=json_object` forces JSON, and `_parse_verdict` tolerates fences/prose and coerces
types; a truly unparseable reply is treated as a safe `diverged=false`.

**Q: Can it break my docs with a bad auto-fix?**
Auto-fix only runs at ≥0.85 confidence *and* passes a self-verification re-check first; otherwise it
downgrades to an issue for a human. And every fix is a PR, never a direct push to the main branch.

---

## 13. Glossary

- **Agentic loop** — perceive → reason → act → verify, each stage a separate module in `agents/`.
- **Semantic change** — a structural code change (signature/params/docstring), not a text diff.
- **Divergence** — a documentation claim that a code change has made false.
- **Hybrid retrieval** — dense embedding similarity combined with exact keyword matching.
- **Thresholded autonomy** — scaling the agent's authority to act to its confidence in the verdict.
- **Self-verification** — the agent re-judging its own proposed fix before shipping it.
- **Testbed** — `docsentry-testbed`, the dummy repo DocSentry watches for demos.

---

*DocSentry — because a lying README is worse than no README.*
