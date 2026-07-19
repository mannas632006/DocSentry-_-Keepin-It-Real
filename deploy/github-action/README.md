# DocSentry as a GitHub Action

The simplest way to use DocSentry on your own repos. No server, no hosting, no
webhook, no credit card. It runs inside GitHub's runners on every push, and the
token it needs to open issues and PRs is provided automatically — the only
secret you add is a free Groq key.

## Setup (2 minutes)

1. **Get a free Groq key** at <https://console.groq.com/keys> (no card).

2. **Add it to the repo you want watched**: that repo → **Settings** →
   **Secrets and variables** → **Actions** → **New repository secret**:
   - Name: `GROQ_API_KEY`
   - Value: your `gsk_…` key

3. **Add the workflow**: copy [`docsentry.yml`](docsentry.yml) into that repo at
   `.github/workflows/docsentry.yml`, then commit and push.

4. **Allow it to write** (only needed once, for the fix-PR / issue features):
   that repo → **Settings** → **Actions** → **General** → **Workflow
   permissions** → **Read and write permissions** → Save.

That's it. The workflow ships in `DRY_RUN` mode, so the first pushes report
findings in the **Actions** tab log but open nothing. When you trust it, delete
the `DRY_RUN: "true"` line from the workflow and push — now it opens a
"Docs Lie" issue, or (at ≥85% confidence, after self-verifying) a fix PR.

## Seeing it catch something

Adding the workflow itself changes no code signatures, so that first run reports
`no_semantic_changes`. To watch it work, push a change that makes a doc false —
the canonical one:

```python
# before
def divide(a, b, safe=True): ...
# after
def divide(a, b, safe=False): ...
```

…while the README still says the default is `True`. Within a minute the Actions
log shows the verdict, and (with `DRY_RUN` removed) an issue or PR appears.

## Want a graphical dashboard too?

Use [`docsentry-dashboard.yml`](docsentry-dashboard.yml) **instead of**
`docsentry.yml`. It does everything above and also publishes a self-contained
monitoring dashboard to **GitHub Pages** on every push — run history, status
tiles, confidence meters, and deep links to the offending lines. No server, no
database, still no card.

Extra one-time setup:

1. **Settings → Pages → Build and deployment → Source = "GitHub Actions"**.
2. Put `docsentry-dashboard.yml` at `.github/workflows/docsentry.yml` (it
   replaces the basic one — don't run both, they'd double-analyse).

Your dashboard lands at `https://<your-username>.github.io/<repo>/`. It needs a
**public** repo (GitHub Pages on private repos is a paid feature).

Prefer to keep it local? `docsentry run --history history.json` writes the same
history file on your machine, and `docsentry dashboard` emits the `dashboard.html`
to open next to it — no hosting at all.

## Notes

- **Output lives where you work.** The issues and PRs it opens *are* the output,
  on the repo itself, and the full run is in the Actions log — plus the
  dashboard, if you enabled it.
- **Cost.** GitHub Actions is free for public repos and has a generous free
  monthly allowance for private ones. Groq's free tier covers the model.
- **Pin the version.** The workflow installs DocSentry from `@main`. Pin it to a
  tag or commit if you want reproducible runs.
- **It won't loop on itself.** The workflow ignores nothing special, but fix PRs
  are opened with the Actions token, and GitHub deliberately does not let that
  token's pushes trigger further workflow runs.
