# 🛡️ DocSentry

**An autonomous agent that keeps your documentation honest.** When a code change makes the docs
*lie* — a flipped default, a renamed function, a changed signature — DocSentry catches it, explains
exactly what's now wrong, and offers a fix for you to approve.

> *"The docs defended themselves."*

---

## The problem

Documentation drifts. Code changes, prose doesn't, and the README quietly becomes false. CI can't
catch it — the code compiles and the tests pass, but the *words* now lie. DocSentry watches a repo
and, on every push, asks: *"Does any documentation still make a claim this change just made false?"*

## What it does

By default DocSentry is **review-first** — it never changes your repo on its own. On drift it opens
an issue that tells you:

- **what changed** in the code,
- **why the docs are now wrong**, and the section + lines involved,
- **how confident** it is, and the result of its own self-check,
- **the exact fix it can apply.**

You then decide. Comment **`/docsentry apply`** and it opens a pull request with that exact fix, or
**`/docsentry dismiss`** and it closes the issue. Nothing happens until you say so. (Prefer full
autonomy? One setting flips it to open fix PRs directly — see [Configuration](#configuration).)

---

## Get started

Two ways to use it. Pick one.

### A) Watch a repo automatically — GitHub Action (recommended)

Runs inside GitHub's own runners on every push. **No server, no hosting, no credit card.** The only
secret you add is a free Groq key.

1. **Get a free Groq API key** at <https://console.groq.com/keys> (no card required).

2. **In the repo you want watched**, go to **Settings**:
   - **Secrets and variables → Actions → New repository secret**: name `GROQ_API_KEY`, value your
     `gsk_…` key.
   - **Actions → General → Workflow permissions**: choose **Read and write**, and tick
     **Allow GitHub Actions to create and approve pull requests**.
   - *(optional, for the dashboard)* **Pages → Build and deployment → Source = GitHub Actions**.

3. **Add the workflow files** to that repo (copy them from
   [`deploy/github-action/`](deploy/github-action/)):
   - `deploy/github-action/docsentry-dashboard.yml` → `.github/workflows/docsentry.yml`
     *(or `docsentry.yml` if you don't want the dashboard)*
   - `deploy/github-action/docsentry-apply.yml` → `.github/workflows/docsentry-apply.yml`

4. **Push.** On the next code change that breaks a doc, DocSentry opens a review issue. Comment
   `/docsentry apply` to get a fix PR. If you enabled Pages, your live dashboard is at
   `https://<your-username>.github.io/<repo>/`.

Full walkthrough: **[deploy/github-action/README.md](deploy/github-action/README.md)**.
To watch another repo, just repeat these steps in that repo — each repo watches itself.

### B) Run it yourself — the CLI

Clone it and run the agent by hand against any repo.

```bash
# 1. Install (Python 3.11+)
git clone https://github.com/mannas632006/DocSentry-_-Keepin-It-Real.git docsentry
cd docsentry
python -m venv .venv
.venv/Scripts/activate                 # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e .

# 2. Configure
cp .env.example .env                   # then set llm_api_key, github_token, target_repo

# 3. Check everything is wired up
docsentry doctor

# 4. Run it
docsentry run --dry-run                # analyse the latest commit, open nothing
docsentry run                          # open a review issue for real
```

`docsentry doctor` tells you exactly what's missing instead of making you guess:

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

You need a [Groq key](https://console.groq.com/keys) and a
[fine-grained GitHub token](https://github.com/settings/tokens?type=beta) (Contents + Issues +
Pull requests, read & write) for the repo in `target_repo`.

---

## How it works

A classic **PERCEIVE → REASON → ACT → VERIFY** agent loop:

```
push → diff_analyzer (tree-sitter AST) → doc_linker (BM25 retrieval)
     → divergence (LLM) → verifier (self-check) → review issue
     →  ⏸  you approve  →  fix PR
```

- **Perceive** — tree-sitter parses the before/after code into ASTs and compares *function
  signatures*, not text lines, so reformatting and comment edits are ignored while a flipped default
  deep in a signature is caught precisely.
- **Reason** — the doc sections that actually name the changed function are retrieved (BM25), then an
  LLM judges whether the doc now lies, returning strict JSON.
- **Verify** — the agent re-checks its own fix and **fails closed**: an unreachable model counts as
  "unverified," never "clean."
- **Act** — it opens a review issue and waits for your approval (or, in autonomous mode, opens the
  PR directly for high-confidence fixes).

See **[DOCUMENTATION.md](DOCUMENTATION.md)** for the full technical deep-dive.

## Choosing a model

The verdict quality *is* the product, and it varies sharply by model. Measured on the canonical case
— `divide(a, b, safe=True)` becomes `safe=False` while the README still says "safe is True":

| Model | Result |
|---|---|
| `orca-mini` (2B, local) | Detects it, but confidence caps ~0.5 |
| `llama3.2:1b` (local) | **Misses it entirely** — reports "clean" |
| `llama-3.3-70b-versatile` (Groq) | Detects at 90%, drafts a correct fix, passes verification |

Local models via Ollama are free and private and fine for development, but a 1–2B model can't
reliably tell "the doc contradicts this change" from "the doc merely mentions it" — and that
judgement is the whole agent. Groq's free tier costs nothing and needs no card, so it's the default.

## Configuration

Every setting has a default, so the app always starts; anything missing is reported by
`docsentry doctor` and `/health` rather than crashing. Full list in [.env.example](.env.example).
The ones that matter:

| Setting | Default | Notes |
|---|---|---|
| `llm_provider` | `groq` | `groq` · `gemini` · `ollama` |
| `llm_api_key` | — | Required for groq/gemini. [Free Groq key](https://console.groq.com/keys) |
| `github_token` | — | Fine-grained PAT: Contents, Issues, Pull requests (read + write) |
| `target_repo` | — | `owner/name` of the repo to watch |
| `require_approval` | `true` | Review-first: report + wait for `/docsentry apply`. `false` = autonomous PRs |
| `dry_run` | `false` | `true` = analyse and report, open nothing |
| `autofix_threshold` | `0.85` | (autonomous mode) confidence ≥ this → verified fix PR |
| `alert_threshold` | `0.50` | confidence ≥ this → open an issue |
| `max_docs_per_change` | `1` | doc sections judged per code change |
| `retrieval_backend` | `bm25` | `chroma` needs `pip install -e ".[chroma]"` |
| `admin_token` | *(blank)* | guards the server's write endpoints; blank = disabled |

## CLI

| Command | What it does |
|---|---|
| `docsentry doctor` | Check config, LLM reachability, repo access and the doc index |
| `docsentry run [SHA]` | Run the agent on a commit (default: repo HEAD) |
| `docsentry apply --issue N` | Apply the fix a review issue proposed, and open a PR |
| `docsentry dismiss --issue N` | Close a review issue without changing anything |
| `docsentry dashboard` | Write the standalone `dashboard.html` monitor |
| `docsentry index` | Rebuild the documentation index |
| `docsentry config` | Print the effective configuration (secrets redacted) |
| `docsentry serve` | Start the API + webhook receiver (and serve the dashboard) |

`run` takes `--dry-run` / `--no-dry-run`, `--json`, `--history FILE`, and threshold overrides.

## The dashboard

Two flavours, for the two ways of running DocSentry — both live and both dark/light themed:

- **Static** (serverless / GitHub Action). `docsentry dashboard` emits one self-contained
  `dashboard.html` that reads a `history.json` written by `docsentry run --history`. The
  [dashboard workflow](deploy/github-action/docsentry-dashboard.yml) publishes both to **GitHub
  Pages** automatically — a live monitor with no server, no build, no card.
- **Live** (hosted server). The React app in [dashboard/](dashboard/) reads the FastAPI + SQLite
  backend and adds controls (trigger a run, clear history).

## Self-hosting the server (optional)

If you'd rather run the always-on webhook service with the live dashboard, the whole app runs as one
container:

```bash
docker build -t docsentry .
docker run -p 8000:8000 --env-file .env docsentry     # dashboard + API on http://localhost:8000
```

See **[DEPLOY.md](DEPLOY.md)** for hosted options and their trade-offs. Note that most "free" cloud
tiers now want a card hold — the GitHub Action path above avoids that entirely.

## Project layout

```
.
├── docsentry/               the agent (a Python package)
│   ├── agents/              diff_analyzer · doc_linker · divergence · verifier · auto_fixer
│   │                        · alerter · review
│   ├── core/                git_ops · parser · retrieval (BM25) · db · github_ops
│   ├── llm/                 provider-agnostic client (groq | gemini | ollama)
│   ├── pipeline.py          the perceive → reason → verify → act loop
│   ├── cli.py               docsentry doctor | run | apply | dismiss | dashboard | serve | …
│   ├── main.py              FastAPI webhook + dashboard API
│   ├── history.py           JSON run-history for the serverless mode
│   └── dashboard_static.py  the self-contained monitoring dashboard
├── deploy/github-action/    drop-in workflows: watch a repo, publish a dashboard, apply on approval
├── dashboard/               React + Vite dashboard for the hosted server
├── tests/                   pytest suite — hermetic: no network, no LLM, no clone
├── Dockerfile               multi-stage: builds the dashboard + serves it from the API
└── render.yaml              Render blueprint for the hosted server
```

## Tests

```bash
pip install -e ".[dev]"
pytest                    # 209 tests, ~30s — no network, no API key, no Ollama needed
```

The suite builds a real git repo in a temp dir per test and scripts the model, so it exercises the
whole loop — the routing in both approval and autonomous modes, the verifier's fail-closed path, the
review-issue payload round-trip — without touching GitHub or an LLM.

## Notes

- **Python + Markdown** for now; other languages and doc formats are a documented extension point.
- **BM25, not embeddings**, is deliberate: the signal that a section documents `divide` is the
  literal token `divide`, which lexical search matches exactly and dense vectors blur. It also keeps
  the install light enough to run anywhere — no PyTorch.
- Approved fixes apply the *exact* reviewed change: the fix is embedded in the issue, so approval
  never triggers a second, non-deterministic model call.

## License

MIT — do whatever you like; attribution appreciated.

---

## Made by Muhammad Anas (MM)

For any assistance or complaints, contact me at f240576@cfd.nu.edu.pk
