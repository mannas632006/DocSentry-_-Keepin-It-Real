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
│ doc_linker  │   BM25 scores the change against every doc section,
│ (retrieval) │   then an exact-name match outranks any score
└──────┬──────┘
       ▼
┌─────────────┐   REASON (judge)
│ divergence  │   the LLM (Groq by default) returns strict JSON:
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
| Retrieval | **BM25** (pure Python) | Exact-token match on identifiers; no model, no torch, deploys anywhere. `chroma` optional |
| LLM brain | **Groq** via OpenAI-compatible client | Free tier, calibrated confidence. `gemini` and local `ollama` also supported |
| Actions | **PyGithub** | Opens issues/PRs on the target repo |
| Server | **FastAPI** + **uvicorn** | Async webhook receiver + dashboard API |
| Persistence | **SQLite** (stdlib) | Zero-config run history |
| Dashboard | **React** + **Vite** | Live-polling view of every run |
| Config | **pydantic-settings** | Typed `.env` loading, never raises at import |

---

## 3. The agentic loop, module by module

### `core/git_ops.py` — PERCEIVE (raw)
`ensure_repo()` returns a local checkout of the watched repo, cloning it into `data_dir` when
`local_repo_path` is unset — which is what a deployed instance does, since it has no sibling
checkout to point at.

`get_commit_changes(repo, hash)` diffs a commit against its parent and returns a list of
`FileChange(path, change_type, before, after)` — the full text of each touched file *before* and
*after*. This is the only place raw file content is read. Root commits (no parent) are diffed
against the empty tree, listing every file as `added`.

Clone URLs embed the PAT, so `redact()` scrubs credentials from anything headed for a log or an
API response.

### `agents/diff_analyzer.py` — PERCEIVE (semantic)
The heart of the "understanding." Instead of diffing text lines, it:
1. Parses both versions with tree-sitter into ASTs.
2. Extracts a `FunctionSig(name, params, returns, docstring)` snapshot for every function, keyed by
   its **qualified** name (`Calculator.divide`), so same-named methods in different classes stay
   distinct.
3. Compares snapshots and emits `SemanticChange` objects: `function_added`, `function_removed`,
   `params_changed`, `default_changed`, `return_type_changed`, `docstring_changed`.

`default_changed` is called out separately from `params_changed` because it is the highest-signal
case for drift: the parameter list is unchanged, nothing looks different, and the docs quietly
state the old value in prose.

**Why this matters:** a whitespace or comment change produces *zero* semantic changes, so the
expensive downstream LLM is never called for noise. Only meaningful structural changes flow on.

### `core/parser.py` + `core/retrieval.py` — REASON (retrieve)
- `parser.py` splits every markdown file into heading-anchored `DocSection`s with line ranges.
  Fenced code blocks are tracked, so a `# comment` inside a ```python block is not mistaken for a
  heading — which matters, because the docs this agent reads are mostly code samples.
- `retrieval.py` indexes each section with **BM25** in memory. `reindex()` rebuilds it (a repo's
  markdown is a few kilobytes, so there is nothing to persist); `search(query, n)` returns the
  top-N by lexical score. Tokenization splits compound identifiers, so `safe_divide` also matches a
  doc that says `divide`.

**Why BM25 and not embeddings:** the signal that a section documents `divide` is the literal token
`divide`. Lexical search matches that exactly; dense vectors blur it into general similarity and
return three vaguely-related sections whether or not any of them are relevant. BM25 also returns
*nothing* when nothing matches, which a vector store cannot do. A `chroma` backend remains
available behind an extra.

### `agents/doc_linker.py` — REASON (retrieve, hybrid)
`link_change_to_docs(change)` builds a query from the changed function's name + the human-readable
detail, retrieves a wider pool than it needs, then applies an **exact-name boost**: any section
that names the identifier outranks any lexical score. The match is word-boundary anchored, so
`divide` does not link to `divided` or `safe_divide`.

### `agents/divergence.py` — REASON (judge) — the brain
Sends the change + one doc section to the model via `docsentry/llm` and demands strict JSON:
```json
{ "diverged": true, "confidence": 0.0-1.0, "mismatch": "...", "suggested_fix": "..." }
```
Robustness built in:
- `response_format={"type": "json_object"}` forces JSON (small models otherwise reply in prose).
  Groq additionally requires the literal word "json" in the prompt, which the system prompt
  satisfies.
- `parse_verdict()` strips code fences, extracts the outermost `{...}` if the model wraps it in
  prose, coerces types, and rescales a `confidence` of `90` to `0.9` — taken literally, that
  clears every threshold at once.
- An unreachable model yields a non-diverged verdict carrying an `error`, so one bad call cannot
  abort a run — but the error stays distinguishable from a genuine "not diverged" (see the
  verifier).
- `suggested_fix` must be the **complete** corrected section. It replaces the section's whole line
  range, so a partial fix would delete the rest of it.

### `agents/auto_fixer.py` — ACT (autonomous)
For high-confidence verdicts: creates a `docsentry/fix-<key>` branch — named from a hash of the
drift, not a timestamp, so re-running the same finding reuses the branch instead of spawning
another PR — replaces the offending doc section with `suggested_fix`, commits, pushes, and opens a
PR via PyGithub.

The splice range is validated against the file before any branch is created, and a `try/finally`
always restores the checkout to the base branch, so a failed push or API call cannot strand the
working tree on a fix branch.

### `agents/alerter.py` — ACT (human-in-the-loop)
For medium confidence: opens a "📄🔥 Docs Lie" issue with the code change, the suspected lie, the
confidence score, and a suggested fix. Findings are de-duplicated on
`(doc file, heading, change)`, so re-pushing the same drift reuses the existing issue. The
`docs-lie` label is created first if absent, rather than dropped — posting a non-existent label
422s.

### `agents/verifier.py` — VERIFY (self-check)
Before a fix ships, re-runs `check_divergence` on the *patched* content. If the doc still lies, the
auto-fix is downgraded to an issue. This is the guardrail against LLM overconfidence — the agent
grades its own homework before submitting it.

It **fails closed**: an unreachable model means "unverified", not "clean". Returns
`(passed, reason)`, and the reason is carried into the resulting issue.

### `pipeline.py` — the orchestrator
Wires all of the above into `run_pipeline(commit_hash, options)` and returns a list of findings
(`auto_fixed` / `alerted` / `clean` / `low_confidence_skip` / `fix_failed_verification` /
`no_semantic_changes` / `no_linked_docs` / `no_docs_indexed` / `error`).

`RunOptions` carries per-run overrides — `dry_run`, both thresholds, `max_docs_per_change` — so the
dashboard can trigger a one-off run at a different threshold without mutating server config. Unset
fields fall back to the global settings.

A failure judging one change is captured as an `error` finding rather than aborting the run.
Runnable standalone: `docsentry run`.

### `main.py` — the server
FastAPI app exposing:
- `POST /webhook/github` — HMAC-verified push receiver; skips the agent's own fix branches to
  prevent infinite self-triggering; answers GitHub's `ping`; runs the pipeline as a background
  task.
- `GET /health` — liveness, plus whether the agent is *ready* and, if not, exactly why.
- `GET /api/config` — effective config with secrets reduced to booleans.
- `GET /api/runs` — run history, filtered and paginated in SQL (`?status=`, `?q=`, `?limit=`,
  `?offset=`); `GET /api/runs/{id}` for one run.
- `GET /api/stats` — aggregate counts for the dashboard tiles.
- `POST /api/analyze`, `DELETE /api/runs` — guarded by `X-Admin-Token`, and **disabled entirely**
  while `admin_token` is unset. The service is internet-facing; an anonymous trigger would file
  real issues on the watched repo.

When `dashboard/dist` exists (the Docker image builds it), the app also serves the dashboard from
the same origin.

---

## 4. Confidence-based routing

The single most important design idea: **thresholded autonomy**. The agent doesn't act with the
same authority on every verdict — it scales its autonomy to its certainty.

| Confidence | Action | Rationale |
|---|---|---|
| **≥ 0.85** (`AUTOFIX_THRESHOLD`) | Auto-fix → open PR (after self-verify) | Certain enough to propose a concrete change |
| **0.50 – 0.84** (`ALERT_THRESHOLD`) | Alert → open issue | Probably wrong, but a human should decide |
| **< 0.50** | Log & skip | Too uncertain to be worth anyone's attention |

Both thresholds are tunable in `.env`, and overridable per-run via the CLI or `POST /api/analyze`.

**Model choice decides which tier you actually reach.** On the canonical flipped-default case:
`orca-mini` (2B) detects the drift but caps around ~0.5 confidence, so it never reaches auto-fix;
`llama3.2:1b` misses it entirely and reports *clean*; Groq's `llama-3.3-70b-versatile` detects it
with calibrated confidence. A small local model doesn't just lower the scores — it fails to
distinguish "the doc contradicts this" from "the doc mentions this", which is the entire judgement.
That is why the default provider is Groq rather than a local model.

Orthogonal to the thresholds, `dry_run` is a global kill switch: the agent does every step and
reports what it *would* do, opening nothing.

---

## 5. How it was made

### v1 — the original build

Built in six phases, each ending in a runnable checkpoint (test-driven, "always working"):

| Phase | Deliverable | Proof of life |
|---|---|---|
| **0** | Env, venv, deps, testbed repo, `.env` | setup check all-green |
| **1** | Diff analyzer (tree-sitter) | Detects `divide` default flip |
| **2** | Code↔doc linker (ChromaDB) | Finds the README `divide` section, exact match |
| **3** | Divergence detector (LLM) | Returns `diverged=true` verdict |
| **4** | Agentic actions (fix / alert / verify) | Opens a real GitHub issue/PR |
| **5** | Webhook server + React dashboard | Push → auto-caught, shown live |
| **6** | Dockerfile, CLI, `requirements.txt` | Containerized, one-command onboarding |

**The v1 pivot: Anthropic → local Ollama.** Phase 3 was originally written against the Anthropic
API. Mid-build it returned `400: "credit balance is too low"`. Rather than pay, the LLM layer was
rewired to a local Ollama model through the OpenAI-compatible client, keeping the same JSON
contract at zero per-token cost.

Bugs fixed during that build: `core/db.py` read a non-existent `commit` column (corrected to
`commit_hash`); `alerter.py` dropped `labels=` to avoid a 422; `divergence.py` gained JSON-mode and
a tolerant parser so a small model's prose replies didn't silently register as "clean".

### v2 — runnable, deployable, tested

v1 worked on the machine it was built on and nowhere else. v2 is the same agent with the
foundations fixed.

**It could not start.** `config.py` declared `github_token`, `target_repo` and `local_repo_path`
with no defaults, so `Settings()` raised at *import* and took every module down with it. Nothing
imported `docsentry` either — no package of that name existed. Every setting now has a default;
`validate_for_run()` reports problems, surfaced by `/health` and `docsentry doctor`.

**It could not deploy.** The LLM endpoint was hardcoded to `localhost:11434`, and the dependency
tree pulled PyTorch (~800MB installed) for embeddings. No free tier accepts either. The provider is
now config (`groq` | `gemini` | `ollama`), and retrieval is pure-Python BM25.

**It could not be tested.** The suite needed a live Ollama, network access, and a sibling checkout
that no longer existed. `test_divergence` asserted `confidence >= 0.7` against a model this very
document recorded as capping at 0.5 — it could not pass. The 152 tests now build a real git repo
per test and script the model.

**Bugs found and fixed in v2** — several latent, waiting for a better model to trigger them:

- **The doc-eating splice.** The prompt asked for "the corrected version of ONLY the false lines"
  while `auto_fixer` spliced that text over the section's *entire* line range. A one-line fix would
  have deleted the rest of the section. It never fired only because orca-mini's confidence caps at
  0.5 and auto-fix needs 0.85 — the first capable model would have hit it.
- **The fail-open verifier.** `verify_fix` returned `not recheck["diverged"]`. An LLM error yields
  `diverged=False`, so an outage read as a PASS — shipping an unverified fix at exactly the moment
  the verifier was broken.
- **Code fences parsed as headings.** Any `# comment` inside a ```python block split a section,
  in docs that are mostly code samples.
- **`default_changed` never emitted.** Declared as a change kind, never produced — despite being
  the flagship demo case. Reported as a generic `params_changed`.
- **Method name collisions.** Functions were keyed by bare name, so `Foo.divide` overwrote
  `Bar.divide` and changes to one were invisible.
- **Root commits inverted.** `commit.diff(None)` compares against the working tree, not the empty
  tree.
- **Duplicate issues.** One flipped default filed three near-identical issues (top-3 docs judged,
  each acted on), and re-pushing filed them again. Now 1 doc per change by default, plus dedup on
  the drift itself.
- **Stranded checkouts.** No `try/finally` around the fix branch: a failed push left the working
  tree on `docsentry/fix-*` and broke every later run.
- **CWD-dependent database.** A bare relative `docsentry.db` meant a different database per launch
  directory.
- **`UnicodeEncodeError` on Windows.** Printing a finding containing `→` crashed the CLI on a
  cp1252 console.

### Layout note

The package now lives in `docsentry/`, which is the layout every import in the codebase already
assumed. Paths derive from the package location rather than the CWD, so `pip install -e .` followed
by `docsentry <command>` works from anywhere — no `PYTHONPATH` gymnastics.

---

## 6. Flow, tokenization & credit optimization

This is where DocSentry is deliberately frugal. **Credit/token usage was optimized at every stage
of the pipeline**, not just by picking a cheap model.

### 6.1 The biggest lever: a free tier, and no embedding model at all
- **LLM inference** runs on **Groq's free tier** — no card, no per-token billing. `llm_provider`
  switches to a local **Ollama** model for fully offline development, or **Gemini**'s free tier.
- **Retrieval needs no model.** BM25 is arithmetic over token counts: no embedding API, and no
  local embedding model either. v1 ran `all-MiniLM-L6-v2` locally, which was free per-call but cost
  ~800MB of PyTorch to install — enough to make the service undeployable on any free host.
- Net external spend: **zero**, on hardware that costs nothing.

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
Instead of sending the entire documentation to the model, `doc_linker` retrieves only the most
relevant sections, and the model judges **one section at a time**. Context per call stays tiny and
constant regardless of how large the docs grow.

### 6.4 Retrieval that returns nothing when nothing matches
The exact-name boost means the truly relevant section reliably ranks first, so
`max_docs_per_change=1` is enough — one LLM call per changed function.

BM25 has a property a vector store lacks: it can score everything at zero and return **nothing**.
A dense index always hands back its `n` nearest neighbours, however unrelated, and v1 then judged
and acted on all three — turning one flipped default into three near-duplicate issues. Sections
that don't mention the identifier now never reach the model at all.

### 6.5 Gate expensive work behind cheap signals
- **AST pre-filter:** whitespace/comment/formatting changes produce zero `SemanticChange`s, so the
  LLM is never invoked for them. Non-`.py` files are skipped outright.
- **Per-commit scoping:** only files touched by the commit are analyzed — never a full-repo scan.
- **Confidence routing:** the extra self-verify LLM call only fires for high-confidence auto-fix
  candidates. The common case (an alert or a clean verdict) costs exactly **one** LLM call.

### 6.6 Tight, structured output
- `max_tokens=900` caps every response; `temperature=0` makes verdicts reproducible.
- `response_format=json_object` eliminates wasted "Here is the JSON you asked for…" preamble tokens
  and prevents costly retries from unparseable prose.

### 6.7 Loop-safety = no wasted runs
The webhook skips pushes on the agent's own `docsentry/fix-*` branches, so an auto-fix PR never
retriggers the whole pipeline on itself — preventing an infinite (and expensive) feedback loop.

### 6.8 Don't pay twice for the same drift
Alerts are de-duplicated on `(doc file, heading, change)` and fix branches are named from that same
key, so re-pushing or re-running the same finding reuses the existing issue or PR rather than
paying for another one.

### Summary table
| Technique | Where | Saves |
|---|---|---|
| Groq free tier | `llm/client.py` | 100% of LLM API cost |
| BM25, no embedding model | `core/retrieval.py` | Embedding API cost *and* ~800MB of PyTorch |
| AST delta, not raw code | `diff_analyzer.py` | ~majority of prompt tokens |
| Top-N section retrieval | `doc_linker.py` | Unbounded → constant context |
| Zero-score sections dropped | `core/retrieval.py` | LLM calls on unrelated docs |
| 1 doc per change (was 3) | `pipeline.py` | 2 of every 3 LLM calls, and duplicate issues |
| AST pre-filter / `.py` skip | `diff_analyzer.py` | Whole LLM calls on noise |
| Per-commit scoping | `git_ops.py` | Full-repo re-analysis |
| Verify only on high-conf | `pipeline.py` | Redundant second call |
| `max_tokens` + JSON mode | `llm/client.py` | Output tokens + retries |
| Self-branch skip guard | `main.py` | Infinite self-triggering |
| Alert + branch dedup | `alerter.py`, `auto_fixer.py` | Repeat work on known drift |

---

## 7. Data contracts

The modules are decoupled by plain dicts, which keeps each stage independently testable.

**SemanticChange** (from `diff_analyzer`):
```python
{ "file": "calculator.py", "kind": "default_changed",
  "name": "divide", "detail": "`divide` default for `safe` changed: `True` → `False`" }
```

**Doc hit** (from `doc_linker` / `retrieval.search`):
```python
{ "id": "README.md::7", "content": "...", "score": 4.21,   # higher is better
  "meta": {"file": "README.md", "heading": "divide",
           "start_line": 7, "end_line": 11},
  "exact_match": True }
```

**Verdict** (from `divergence`):
```python
{ "diverged": True, "confidence": 0.95,
  "mismatch": "doc claims safe defaults to True, but it now defaults to False",
  "suggested_fix": "## divide\n\n...",   # the COMPLETE corrected section
  "error": None,                          # set when the model was unreachable
  "doc_id": "README.md::7", "doc_file": "README.md", "doc_heading": "divide",
  "doc_start_line": 7, "doc_end_line": 11 }
```

**Finding** (from `pipeline`, stored in SQLite, served to the dashboard):
```python
{ "status": "alerted",
  "change": { "file": "calculator.py", "kind": "default_changed",
              "name": "divide", "detail": "..." },
  "doc": { "file": "README.md", "heading": "divide",
           "start_line": 7, "end_line": 11 },
  "confidence": 0.95,
  "mismatch": "...",
  "suggested_fix": "...",
  "url": "https://github.com/.../issues/1" }   # "dry-run://..." in a dry run
```

Two contract notes worth knowing:

- **`score`, not `distance`.** Every retrieval backend reports higher-is-better, so swapping BM25
  for Chroma doesn't silently invert the ranking.
- **`error` is not `diverged: False`.** An unreachable model returns a non-diverged verdict *with*
  `error` set. The verifier reads that field specifically, because treating it as a clean verdict is
  what made v1's verifier fail open.

---

## 8. Running it

### Prerequisites
- Python 3.11+
- A `.env` with `llm_api_key`, `github_token` and `target_repo` (see `.env.example`)
- Node.js 20+ — only for the dashboard
- Nothing else. No sibling checkout (the agent clones `target_repo` itself), no local model, no
  `PYTHONPATH`.

### Install
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows; source .venv/bin/activate elsewhere
pip install -e ".[dev]"
```

### One-shot run (CLI)
```bash
docsentry doctor              # is everything wired up?
docsentry run --dry-run       # analyse the latest commit, open nothing
docsentry run                 # for real
docsentry run <sha> --json    # a specific commit, machine-readable
```

### Live server
```bash
docsentry serve --reload      # http://localhost:8000, API docs at /docs
```
Then expose it (`ngrok http 8000`) and register a GitHub webhook → `<tunnel>/webhook/github`
(content type `application/json`, secret = your `webhook_secret`, "just the push event").

### Dashboard
```bash
cd dashboard
npm install
npm run dev                   # http://localhost:5173
```

### Docker
The image builds the dashboard and serves it from the API, so one container is the whole app:
```bash
docker build -t docsentry .
docker run --env-file .env -p 8000:8000 docsentry
```

### Deploying
See [DEPLOY.md](DEPLOY.md) — Render + Vercel + Groq, all free tier.

---

## 9. Security model

- **Webhook authenticity:** every payload is HMAC-SHA256 verified against `webhook_secret` using
  `hmac.compare_digest` (constant-time). Unsigned or mismatched requests get `401` before any work.
- **Write endpoints are closed by default:** `POST /api/analyze` and `DELETE /api/runs` require
  `X-Admin-Token`, compared in constant time. While `admin_token` is unset they are **disabled**
  rather than open — the service is internet-facing, and an anonymous trigger could file real issues
  on the watched repo.
- **Least-privilege token:** the GitHub PAT is fine-grained, scoped to the single target repo, with
  only Contents/Issues/PRs write.
- **Secrets never committed:** `.env` and `.docsentry/` (database + cloned repos) are gitignored.
- **Secrets never logged or served:** clone URLs embed the PAT, so `redact()` scrubs credentials
  from log lines and error responses, and `/api/config` reduces every secret to a boolean.
- **What does leave the machine:** with a hosted provider, the model sees the *change summary* and
  the matched doc section — never a source file (see §6.2). Set `llm_provider=ollama` for a fully
  local setup where nothing leaves at all; read §4 on what that costs in verdict quality first.

---

## 10. Limitations & known trade-offs

- **Small-model ceiling:** local 1–2B models either cap confidence around 0.5 (`orca-mini`, never
  reaching auto-fix) or miss the drift entirely (`llama3.2:1b`, reports *clean*). This is why the
  default provider is Groq. It is a genuine trade-off against the "nothing leaves your machine"
  property, not a bug.
- **Python-only:** `diff_analyzer` currently parses Python. Other languages need their own
  tree-sitter grammar + an `extract_functions` mirror.
- **Markdown-only docs:** `parser.py` handles `.md`/`.markdown`/`.mdx`; other doc formats aren't
  indexed.
- **Function-level granularity:** it reasons about signatures, defaults, return types and
  docstrings — not deep behavioural changes inside a function body. A rewritten function that keeps
  its signature is invisible to it.
- **Lexical retrieval has a blind spot:** BM25 needs the doc to *name* the identifier. Prose that
  describes a function purely in English ("the division helper") won't be linked. This is the price
  of its precision; `retrieval_backend=chroma` trades back the other way.
- **Free-tier ephemerality:** on a host without a persistent disk, run history and the dedup log
  reset on restart. Issues and PRs already opened are unaffected. See DEPLOY.md.
- **One commit at a time:** a push containing many commits is analysed at its head commit only;
  drift introduced and reverted mid-push is not examined.

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

**Q: Why retrieval for docs, rather than sending the whole manual?**
So the model only ever sees the doc sections relevant to a change. It bounds context (and cost) and
scales to large docs.

**Q: Why BM25 rather than a vector database?**
Because the query is an identifier. The signal that a section documents `divide` is the literal
token `divide` — lexical search matches it exactly, while dense vectors blur it into general
similarity. BM25 can also return *nothing* when nothing matches; a vector store always hands back
its `n` nearest neighbours, which is how v1 turned one flipped default into three issues. It needs
no model, which is what makes the service fit on a free tier. `retrieval_backend=chroma` is still
there if you want dense matching.

**Q: Does it cost money to run?**
No. Groq's free tier needs no card, retrieval needs no model at all, and both hosting tiers in
DEPLOY.md are free. Set `llm_provider=ollama` if you'd rather spend CPU than use a hosted API.

**Q: How does it avoid infinite loops?**
Its own fix PRs push to `docsentry/fix-*` branches, and the webhook explicitly ignores those refs.

**Q: What if the model outputs garbage instead of JSON?**
`response_format=json_object` forces JSON, and `parse_verdict` tolerates fences/prose, coerces
types and rescales a `90` to `0.9`; a truly unparseable reply is treated as a safe `diverged=false`.

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
