# 🛡️ DocSentry

**An autonomous agent that keeps documentation honest.** When code changes in a way that makes
the docs *lie* — a flipped default, a renamed function, a changed signature — DocSentry detects it,
opens a GitHub issue (or a fix PR), and verifies its own fix before shipping it.

> *"The docs defended themselves."*

---

## Why

Documentation drifts. Code changes, prose doesn't, and the README silently becomes false. CI can't
catch it — the code compiles and the tests pass, but the *words* now lie. DocSentry watches a repo
and, on every push, asks: *"Does any documentation still make a claim this change just made false?"*

## How it works

A classic **PERCEIVE → REASON → ACT → VERIFY** agent loop:

```
push → diff_analyzer (tree-sitter AST) → doc_linker (BM25 retrieval)
     → divergence (LLM) → confidence router → fix PR / alert issue
     → verifier (self-check) → SQLite → FastAPI → React dashboard
```

- **Perceive:** tree-sitter parses the before/after code into ASTs and compares *function
  signatures* — not text lines — so reformatting and comment edits are ignored, while a flipped
  default deep inside a signature is caught precisely.
- **Reason:** the doc sections that actually name the changed function are retrieved, then an LLM
  judges whether the doc now lies, returning strict JSON.
- **Act:** confidence ≥0.85 → auto-fix PR; 0.50–0.84 → "Docs Lie" issue; below → skip.
- **Verify:** the agent re-checks its own fix before opening the PR, and **fails closed** — if the
  model can't be reached, the fix is treated as unverified rather than clean.

See **[DOCUMENTATION.md](DOCUMENTATION.md)** for the technical deep-dive.

## Tech stack

tree-sitter · GitPython · BM25 (pure Python) · **Groq** (or Gemini, or local Ollama) · PyGithub ·
FastAPI · SQLite · React + Vite

## Quick start

```bash
# 1. Install (Python 3.11+)
python -m venv .venv
.venv/Scripts/activate           # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env             # then fill in llm_api_key, github_token, target_repo

# 3. Check everything is wired up
docsentry doctor

# 4. Run the agent on the watched repo's latest commit
docsentry run --dry-run          # analyse, but open nothing
docsentry run                    # for real
```

`docsentry doctor` tells you exactly what's missing rather than making you guess:

```
Configuration
  [ok] all required settings present
       provider=groq model=llama-3.3-70b-versatile
LLM
  [ok] groq reachable at https://api.groq.com/openai/v1
Watched repository
  [ok] /home/you/.docsentry/repos/acme__testbed
Documentation index
  [ok] indexed 4 sections

READY
```

### Live server + dashboard

```bash
# Terminal 1 — API + webhook receiver
docsentry serve --reload         # http://localhost:8000  (API docs at /docs)

# Terminal 2 — dashboard
cd dashboard && npm install && npm run dev   # http://localhost:5173
```

Expose the server with a tunnel (`ngrok http 8000`) and add a GitHub webhook pointing at
`<tunnel>/webhook/github` (content type `application/json`, secret = your `webhook_secret`,
just the push event).

## CLI

| Command | What it does |
|---|---|
| `docsentry doctor` | Check config, LLM reachability, repo access and the doc index |
| `docsentry run [SHA]` | Run the agent on a commit (default: repo HEAD) |
| `docsentry index` | Rebuild the documentation index and report the section count |
| `docsentry config` | Print the effective configuration (secrets redacted) |
| `docsentry serve` | Start the API and webhook receiver |

`run` takes `--dry-run` / `--no-dry-run`, `--json`, `--autofix-threshold`, `--alert-threshold`
and `--max-docs`. Both dry-run flags are explicit because `dry_run` can be set in the environment
(as the Render blueprint does) — `--no-dry-run` is how you act anyway for one run.

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness, plus whether the agent is actually *ready* and why not |
| `GET /api/config` | Effective config, secrets reduced to booleans |
| `GET /api/stats` | Counts by status |
| `GET /api/runs` | Run history — `?status=`, `?q=`, `?limit=`, `?offset=` |
| `GET /api/runs/{id}` | One run with its findings |
| `POST /api/analyze` | Trigger a run, with optional per-run overrides 🔒 |
| `DELETE /api/runs` | Clear history 🔒 |
| `POST /webhook/github` | Signed GitHub push receiver |

🔒 requires the `X-Admin-Token` header. **While `admin_token` is unset these endpoints are
disabled**, not open — the service is internet-facing, and an anonymous trigger could file real
issues on your repo.

## Configuration

Everything has a default, so the app always starts; missing values are reported by `/health` and
`docsentry doctor` rather than crashing on import. See [.env.example](.env.example) for the full
list. The ones that matter:

| Setting | Default | Notes |
|---|---|---|
| `llm_provider` | `groq` | `groq` · `gemini` · `ollama` |
| `llm_api_key` | — | Required for groq/gemini. [Free Groq key](https://console.groq.com/keys) |
| `github_token` | — | Fine-grained PAT: Contents, Issues, Pull requests (read+write) |
| `target_repo` | — | `owner/name` of the repo to watch |
| `local_repo_path` | *(blank)* | Blank = clone `target_repo` at runtime. Leave blank in production |
| `admin_token` | *(blank)* | Blank = write endpoints disabled |
| `dry_run` | `false` | `true` = analyse and report, open nothing |
| `autofix_threshold` | `0.85` | Confidence ≥ this → verified fix PR |
| `alert_threshold` | `0.50` | Confidence ≥ this → issue |
| `max_docs_per_change` | `1` | Doc sections judged per code change |
| `retrieval_backend` | `bm25` | `chroma` needs `pip install -e ".[chroma]"` |

## Choosing a model

The verdict quality *is* the product, and it varies sharply by model. Measured on the canonical
case — `divide(a, b, safe=True)` becomes `safe=False` while the README still says "safe is True":

| Model | Result |
|---|---|
| `orca-mini` (2B, local) | Detects it, but confidence caps around 0.5 — never reaches auto-fix |
| `llama3.2:1b` (local) | **Misses it entirely** — reports "clean" |
| `llama-3.3-70b-versatile` (Groq) | Detects at 90%, drafts a correct fix, passes verification → **auto-fix PR** |

Local models are genuinely free and private, and they're a fine way to develop against. But a 1–2B
model cannot reliably tell "the doc contradicts this change" from "the doc is merely related to
it", and that judgement is the whole agent. Groq's free tier costs nothing and needs no card, which
is why it's the default — and it's the only configuration measured to carry a change all the way to
an opened pull request (3/3 runs, dry-run against the testbed).

## Using it on your own repos (free, no server)

The simplest way to run DocSentry is as a **GitHub Action** — it runs inside GitHub's runners on
every push, needs no hosting and no credit card, and the token to open issues/PRs is provided
automatically. The only secret you add is a free [Groq key](https://console.groq.com/keys). Drop
[`deploy/github-action/docsentry.yml`](deploy/github-action/docsentry.yml) into any repo you want
watched — see [deploy/github-action/](deploy/github-action/README.md).

Or run it by hand against any local checkout:

```bash
docsentry run --dry-run     # analyse the latest commit, open nothing
docsentry run               # open a "Docs Lie" issue or a verified fix PR
```

### A dashboard, without a server

There are two dashboards for the two ways of running DocSentry:

- **Static** — for the serverless (GitHub Action / local) mode. `docsentry dashboard`
  emits one self-contained `dashboard.html` that reads a `history.json` written by
  `docsentry run --history`. Publish both to **GitHub Pages** for a live monitor at
  `https://<you>.github.io/<repo>/` (the [dashboard workflow](deploy/github-action/docsentry-dashboard.yml)
  does this automatically), or just open the HTML off disk. No server, no build, no card.
- **Live** — the React app in [dashboard/](dashboard/), for the hosted webhook server; it
  reads the FastAPI + SQLite backend and adds write controls (trigger a run, clear history).

### Hosting the live server + dashboard

If you want the always-on webhook service with the dashboard, the same app runs as one container:

```bash
docker build -t docsentry .
docker run -p 8000:8000 --env-file .env docsentry
```

See **[DEPLOY.md](DEPLOY.md)** for hosted options and their trade-offs. Note that most "free" cloud
tiers now want a card hold (Render) or have moved container hosting behind a paid plan (Hugging
Face) — the GitHub Action above sidesteps all of that.

## Project layout

```
.
├── docsentry/
│   ├── agents/      diff_analyzer, doc_linker, divergence, auto_fixer, alerter, verifier
│   ├── core/        git_ops, parser, retrieval, db, github_ops
│   ├── llm/         provider-agnostic client (groq | gemini | ollama)
│   ├── main.py      FastAPI webhook + dashboard API
│   ├── pipeline.py  the perceive→reason→act→verify loop
│   └── cli.py       docsentry doctor | run | index | config | serve
├── dashboard/       React + Vite dashboard
├── tests/           pytest suite (hermetic: no network, no LLM, no clone)
├── render.yaml      Render blueprint
├── Dockerfile       multi-stage: dashboard + API in one image
└── DOCUMENTATION.md full technical docs
```

## Tests

```bash
pytest                    # 173 tests, ~20s, no network and no API key needed
```

The suite builds a real git repo in a temp dir per test and scripts the model, so it exercises the
whole loop — including the routing thresholds and the verifier's fail-closed path — without
touching GitHub or an LLM.

## Notes

- **Python + Markdown** for now; other languages and doc formats are a documented extension point.
- BM25 rather than embeddings is a deliberate choice, not a downgrade: the signal that a section
  documents `divide` is the literal token `divide`, which lexical search matches exactly and dense
  vectors blur. It also keeps the install inside a free tier's limits, which a PyTorch dependency
  does not.
- The dashboard is plain React — no component library, no CSS framework.

## License

MIT — do whatever you like; attribution appreciated.

---

## Made By: Muhammad Anas (MM)

For any assistance or complaints, contact me at f240576@cfd.nu.edu.pk
