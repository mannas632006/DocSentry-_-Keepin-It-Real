"""FastAPI app: GitHub webhook receiver + dashboard API."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from docsentry import __version__
from docsentry.config import PROJECT_ROOT, settings
from docsentry.core import db
from docsentry.core.git_ops import GitOpsError, commit_message, ensure_repo, redact
from docsentry.llm import probe
from docsentry.pipeline import RunOptions, run_pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    problems = settings.validate_for_run()
    if problems:
        # Boot anyway: a running API that explains what is missing is more
        # useful than a crash loop, and /health reports the same list.
        log.warning("not ready to run: %s", "; ".join(problems))
    yield


app = FastAPI(
    title="DocSentry",
    version=__version__,
    description="An autonomous agent that keeps documentation honest.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- auth -----------------------------------------------------------------


def require_admin(x_admin_token: str | None = Header(None)) -> None:
    """Guard for endpoints with real side effects."""
    if not settings.admin_token:
        raise HTTPException(
            403,
            "admin_token is not configured, so write endpoints are disabled. "
            "Set admin_token in the environment to enable them.",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(401, "Bad or missing X-Admin-Token")


def _verify_signature(body: bytes, signature: str | None) -> None:
    if signature is None:
        raise HTTPException(401, "Missing signature")
    expected = "sha256=" + hmac.new(
        settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Bad signature")


# --- the work ------------------------------------------------------------


def _process(commit_hash: str, trigger: str, options: RunOptions) -> int:
    """Run the pipeline for one commit and persist the result."""
    started = time.perf_counter()
    opts = options.resolved()
    error = ""
    results: list[dict[str, Any]] = []
    msg = ""
    try:
        repo_path = ensure_repo(fetch=True)
        msg = commit_message(repo_path, commit_hash)
        results = run_pipeline(commit_hash, options)
    except GitOpsError as e:
        error = redact(str(e))
        log.error("run failed: %s", error)
    except Exception as e:  # noqa: BLE001 - a failed run must still be recorded
        error = redact(f"{type(e).__name__}: {e}")
        log.exception("run failed")

    return db.save_run(
        commit_hash,
        results,
        commit_msg=msg,
        duration_ms=int((time.perf_counter() - started) * 1000),
        trigger=trigger,
        dry_run=opts["dry_run"],
        error=error,
    )


# --- webhook -------------------------------------------------------------


@app.post("/webhook/github", tags=["webhook"])
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
) -> dict[str, Any]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    if x_github_event == "ping":
        return {"ok": True, "pong": True}
    if x_github_event != "push":
        return {"ignored": x_github_event}

    payload = await request.json()
    ref = payload.get("ref", "")
    # Skip the agent's own fix branches, or it would analyse its own PRs.
    if ref.startswith("refs/heads/docsentry/"):
        return {"ignored": "own branch"}
    if payload.get("deleted"):
        return {"ignored": "branch deleted"}

    commit = payload.get("after")
    if not commit or set(commit) == {"0"}:
        return {"ignored": "no commit"}

    background.add_task(_process, commit, "webhook", RunOptions())
    return {"queued": commit}


# --- read API ------------------------------------------------------------


@app.get("/health", tags=["meta"])
def health() -> dict[str, Any]:
    """Liveness plus a straight answer about whether the agent can actually run."""
    problems = settings.validate_for_run()
    llm = probe()
    return {
        "status": "ok" if not problems and llm.get("reachable") else "degraded",
        "version": __version__,
        "ready": not problems,
        "problems": problems,
        "llm": llm,
        "target_repo": settings.target_repo,
        "dry_run": settings.dry_run,
    }


@app.get("/api/config", tags=["meta"])
def api_config() -> dict[str, Any]:
    """Effective configuration, with secrets reduced to booleans."""
    return settings.public_dict()


@app.get("/api/stats", tags=["runs"])
def api_stats() -> dict[str, Any]:
    return db.stats()


@app.get("/api/runs", tags=["runs"])
def api_runs(
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="keep runs with a finding of this status"),
    q: str | None = Query(None, description="free-text search"),
) -> dict[str, Any]:
    return {
        "total": db.count_runs(status=status, q=q),
        "limit": limit,
        "offset": offset,
        "runs": db.recent_runs(limit=limit, offset=offset, status=status, q=q),
    }


@app.get("/api/runs/{run_id}", tags=["runs"])
def api_run(run_id: int) -> dict[str, Any]:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, f"no run with id {run_id}")
    return run


# --- write API -----------------------------------------------------------


class AnalyzeRequest(BaseModel):
    commit: str | None = Field(
        None, description="commit SHA; defaults to the watched repo's HEAD"
    )
    dry_run: bool | None = Field(None, description="analyse but open nothing")
    autofix_threshold: float | None = Field(None, ge=0, le=1)
    alert_threshold: float | None = Field(None, ge=0, le=1)
    max_docs_per_change: int | None = Field(None, ge=1, le=10)


@app.post("/api/analyze", tags=["runs"], dependencies=[Depends(require_admin)])
def api_analyze(req: AnalyzeRequest, background: BackgroundTasks) -> dict[str, Any]:
    """Trigger a run by hand, optionally with one-off overrides."""
    problems = settings.validate_for_run()
    if problems:
        raise HTTPException(409, {"error": "not ready to run", "problems": problems})

    commit = req.commit
    if not commit:
        try:
            from docsentry.core.git_ops import latest_commit_hash
            commit = latest_commit_hash(ensure_repo(fetch=True))
        except GitOpsError as e:
            raise HTTPException(400, redact(str(e))) from e

    options = RunOptions(
        dry_run=req.dry_run,
        autofix_threshold=req.autofix_threshold,
        alert_threshold=req.alert_threshold,
        max_docs_per_change=req.max_docs_per_change,
    )
    background.add_task(_process, commit, "manual", options)
    return {"queued": commit, "options": options.resolved()}


@app.delete("/api/runs", tags=["runs"], dependencies=[Depends(require_admin)])
def api_clear_runs() -> dict[str, Any]:
    """Wipe run history and the alert dedup log."""
    return {"deleted": db.clear_runs()}


# --- optional bundled dashboard ------------------------------------------

# When the dashboard has been built, serve it from the same origin. Lets a
# single Render service host both without needing the Vercel front end.
_DIST = PROJECT_ROOT / "dashboard" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="dashboard")
else:
    @app.get("/", tags=["meta"])
    def root() -> dict[str, Any]:
        return {
            "name": "DocSentry",
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }
