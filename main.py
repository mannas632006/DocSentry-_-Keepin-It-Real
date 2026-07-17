"""FastAPI app: GitHub webhook receiver + dashboard API."""
import hashlib
import hmac

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from docsentry.config import settings
from docsentry.core.db import init_db, recent_runs, save_run
from docsentry.pipeline import run_pipeline

app = FastAPI(title="DocSentry")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
init_db()


def _verify_signature(body: bytes, signature: str | None):
    if signature is None:
        raise HTTPException(401, "Missing signature")
    expected = "sha256=" + hmac.new(
        settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Bad signature")


def _process(commit_hash: str):
    # pull first so the local clone has the new commit
    from git import Repo
    Repo(settings.local_repo_path).remotes.origin.pull()
    results = run_pipeline(commit_hash)
    save_run(commit_hash, results)


@app.post("/webhook/github")
async def github_webhook(request: Request, background: BackgroundTasks,
                         x_hub_signature_256: str | None = Header(None),
                         x_github_event: str | None = Header(None)):
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)
    if x_github_event != "push":
        return {"ignored": x_github_event}
    payload = await request.json()
    # skip pushes made by the agent itself (its own fix branches)
    if payload.get("ref", "").startswith("refs/heads/docsentry/"):
        return {"ignored": "own branch"}
    commit = payload.get("after")
    background.add_task(_process, commit)
    return {"queued": commit}


@app.get("/api/runs")
def api_runs():
    return recent_runs()


@app.get("/api/stats")
def api_stats():
    runs = recent_runs(500)
    flat = [r for run in runs for r in run["results"]]
    return {
        "total_runs": len(runs),
        "auto_fixed": sum(1 for r in flat if r.get("status") == "auto_fixed"),
        "alerted": sum(1 for r in flat if r.get("status") == "alerted"),
        "clean": sum(1 for r in flat if r.get("status") == "clean"),
    }
