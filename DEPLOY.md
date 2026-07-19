# Deploying DocSentry

## Just want to use it? Use the GitHub Action (recommended, no server)

If the goal is "watch my repos and catch drift," you do **not** need to host anything. DocSentry
runs as a GitHub Action inside GitHub's own runners — no server, no webhook, no credit card, and
the token to open issues/PRs is provided automatically. The only secret you add is a free Groq key.
Two-minute setup in **[deploy/github-action/](deploy/github-action/README.md)**.

Everything below is for running the **always-on webhook service + dashboard** instead, if you
specifically want that.

> **A note on "free" hosting.** The container-hosting landscape has tightened: Render's free tier
> needs a card-verification hold, and Hugging Face moved Docker Spaces behind a paid plan. The
> GitHub Action above avoids all of it. If you want a hosted server anyway, Koyeb is the remaining
> GitHub-native free-ish option to try, or run locally and expose it with a Cloudflare Tunnel
> (`cloudflared tunnel --url http://localhost:8000`) — free, no card, live while your machine is.

---

## Hosting the webhook service (Render example)

API on **Render** (free web service), dashboard on **Vercel** (free static hosting), LLM on
**Groq** (free tier, no card). Note the card caveat above for Render.

Read [Free-tier caveats](#free-tier-caveats) first — two of them shape how you'll use this.

---

## What you need

| Thing | Where | Cost |
|---|---|---|
| Groq API key | <https://console.groq.com/keys> | free, no card |
| GitHub fine-grained PAT | <https://github.com/settings/tokens?type=beta> | free |
| A repo to watch | any repo you own | free |
| Render account | <https://render.com> | free |
| Vercel account | <https://vercel.com> | free |

The PAT needs, **on the watched repo only**:

- **Contents** — read & write (to push the fix branch)
- **Issues** — read & write (to open "Docs Lie" issues)
- **Pull requests** — read & write (to open fix PRs)

Scope it to the single repo. This token can write to your code; don't give it more reach than the
job needs.

---

## 1. The API on Render

1. Push this repo to GitHub.
2. Render → **New** → **Blueprint** → select the repo. It reads [render.yaml](render.yaml) and
   provisions `docsentry-api`.
3. Render prompts for the three secrets marked `sync: false`:

   | Variable | Value |
   |---|---|
   | `LLM_API_KEY` | your Groq key (`gsk_...`) |
   | `GITHUB_TOKEN` | your fine-grained PAT |
   | `TARGET_REPO` | `your-username/the-repo-to-watch` |

4. Deploy. When it's live, open `https://<your-service>.onrender.com/health`:

   ```json
   { "status": "ok", "ready": true, "problems": [],
     "llm": { "provider": "groq", "reachable": true } }
   ```

   `ready: false` lists exactly what's missing in `problems` — fix those and redeploy.

5. Copy the two values Render generated for you, under **Environment**:
   - `WEBHOOK_SECRET` → needed in step 3
   - `ADMIN_TOKEN` → needed in step 4

`render.yaml` ships with `DRY_RUN=true` on purpose. The agent will do everything except open
issues and PRs, so you can watch it work first. Flip it to `false` when you trust the verdicts.

## 2. The dashboard on Vercel

1. Vercel → **Add New** → **Project** → import the same repo.
2. Set **Root Directory** to `dashboard`. Vercel picks up the framework from
   [dashboard/vercel.json](dashboard/vercel.json).
3. Add an environment variable:

   | Variable | Value |
   |---|---|
   | `VITE_API_URL` | `https://<your-service>.onrender.com` (no trailing slash) |

4. Deploy.

You can skip step 3 entirely — the dashboard has a **Settings** panel where you paste the API URL
once, stored per browser. Useful when you want to repoint it without a rebuild.

## 3. The GitHub webhook

On the **watched** repo → Settings → Webhooks → Add webhook:

| Field | Value |
|---|---|
| Payload URL | `https://<your-service>.onrender.com/webhook/github` |
| Content type | `application/json` |
| Secret | the `WEBHOOK_SECRET` Render generated |
| Events | **Just the push event** |

GitHub sends a ping immediately; a green tick means the signature check passed. A red one usually
means the secret doesn't match, or the service is still waking (see caveats).

## 4. Enable the dashboard's controls

Open the dashboard → **Settings** → paste the `ADMIN_TOKEN` Render generated → Save.

That unlocks **Run agent** and **Clear run history**. Without it those endpoints return 403 by
design: the API is on a public URL, and an anonymous trigger could file real issues on your repo.
The token is kept in your browser only and is sent as `X-Admin-Token`.

## 5. Try it

Push a change to the watched repo that makes its docs lie — the canonical one:

```python
# before
def divide(a, b, safe=True): ...
# after
def divide(a, b, safe=False): ...
```

…while the README still says *"By default `safe` is **True**"*.

Within a few seconds of the push, the dashboard shows a run. With `DRY_RUN=true` you'll see the
verdict, the confidence and the proposed fix, with nothing opened. Set `DRY_RUN=false` and the same
push files a real issue — or, above 0.85 confidence, a verified fix PR.

You can also hit **Run agent** in the dashboard to analyse the current HEAD without pushing.

---

## Free-tier caveats

These are real. Better to know now than to debug them later.

### Cold starts vs. GitHub's webhook timeout

Render's free tier spins the service down after ~15 minutes idle; waking it takes ~50 seconds.
**GitHub webhooks time out after 10 seconds.** So the first push after an idle period shows as a
*failed delivery* in GitHub — even though Render does wake up and the run does happen.

Options:

- **Redeliver** from the repo's webhook page (Recent Deliveries → Redeliver). One click.
- **Keep it warm** — point a free cron ping (e.g. <https://cron-job.org>) at `/health` every 10
  minutes. A free instance gets 750 hours/month, which is enough to stay up continuously for one
  service.
- **Ignore it** — pushes while the service is already awake deliver fine.

### History is ephemeral

Render's free tier has no persistent disk, so the SQLite database resets on every deploy and
restart. You lose the *run history*, not the work: issues and PRs already opened live on GitHub.
The dedup log resets too, so a drift already reported could be reported once more after a restart.

For durable history, attach a Render disk (paid), or point `data_dir` at one.

### Groq rate limits

The free tier is generous but rate-limited per minute. One push costs roughly one LLM call per
changed function (plus one more to verify a fix). A push touching dozens of signatures can hit the
limit; those changes surface as `error` findings rather than crashing the run, and you can re-run
them.

---

## Alternatives

**One service instead of two.** The [Dockerfile](Dockerfile) builds the dashboard and serves it
from the API, so Render alone hosts everything and `VITE_API_URL` becomes unnecessary — the
dashboard defaults to its own origin. Set the Render service's runtime to Docker.

**Hugging Face Spaces.** A free Docker Space has more RAM and no spin-down, which sidesteps the
cold-start caveat. Use the same Dockerfile; set the secrets in the Space settings.

**Local, no deploy.** `docsentry serve` plus `ngrok http 8000` gives a public webhook URL from your
machine, and `llm_provider=ollama` keeps it fully offline. Read the model comparison in the README
first — small local models miss the drift this agent exists to catch.
