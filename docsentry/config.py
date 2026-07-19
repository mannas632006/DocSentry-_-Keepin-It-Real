"""Runtime configuration.

Importing this module must never raise. Every setting has a usable default so
that `import docsentry.main` works on a bare checkout with no .env — the API
can then boot and report *why* it is not ready via /health, instead of dying
at import time with a pydantic traceback.

Requirements that are only needed for a real run are checked by
`validate_for_run()`, which returns human-readable problems rather than
throwing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

Provider = Literal["groq", "ollama", "gemini"]

# Per-provider endpoint + model defaults. All three speak the OpenAI wire
# format, so one client library covers them; only base_url and model change.
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "orca-mini:latest",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.0-flash",
    },
}

# Providers that need a real credential (Ollama runs unauthenticated locally).
PROVIDERS_REQUIRING_KEY = {"groq", "gemini"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---
    llm_provider: Provider = "groq"
    llm_api_key: str = ""
    llm_model: str = ""       # blank -> PROVIDER_DEFAULTS[provider]["model"]
    llm_base_url: str = ""    # blank -> PROVIDER_DEFAULTS[provider]["base_url"]
    llm_timeout: float = 60.0
    llm_max_retries: int = 2

    # --- GitHub ---
    github_token: str = ""
    target_repo: str = ""     # "owner/name"

    # --- Storage ---
    # Absolute and derived from the package location, never the CWD: the old
    # relative "docsentry.db" silently created a fresh database per directory
    # you happened to launch from.
    data_dir: Path = PROJECT_ROOT / ".docsentry"

    # Where the watched repo lives on disk. Blank means "clone target_repo into
    # data_dir at runtime", which is the only thing that works on a host where
    # no sibling checkout exists.
    local_repo_path: str = ""

    # --- Webhook ---
    webhook_secret: str = "dev-secret"

    # Guards the endpoints with side effects (trigger a run, clear history).
    # The service runs on a public URL, so while this is unset those endpoints
    # are disabled rather than open: an unauthenticated trigger could spam
    # real issues onto the watched repo.
    admin_token: str = ""

    # --- Behaviour ---
    autofix_threshold: float = 0.85
    alert_threshold: float = 0.50

    # How many linked doc sections to judge per code change. The v1 pipeline
    # judged the top 3 and filed an issue for each, so one flipped default
    # produced three near-duplicate issues. 1 is the sane default.
    max_docs_per_change: int = 1

    # Retrieval backend. bm25 is pure-Python and deploys anywhere; chroma
    # needs the [chroma] extra and is intended for local use.
    retrieval_backend: Literal["bm25", "chroma"] = "bm25"

    # Review-first, the safer default: never open a fix PR unprompted. Drift is
    # reported as an issue describing the problem and the fix DocSentry *can*
    # apply; a human then approves it (comment `/docsentry apply`) to open the
    # PR. Set false for the fully autonomous mode where high-confidence fixes
    # open a PR directly.
    require_approval: bool = True

    # Global kill switch for side effects. When true the agent does all the
    # analysis and reports what it *would* do, but opens no issues or PRs.
    dry_run: bool = False

    # CORS origins for the dashboard, comma-separated. "*" is fine locally;
    # set explicitly in production.
    cors_origins: str = "*"

    @field_validator("target_repo")
    @classmethod
    def _strip_repo(cls, v: str) -> str:
        """Accept a full URL as well as owner/name."""
        v = v.strip().removesuffix(".git")
        if "github.com" in v:
            v = v.split("github.com", 1)[1].lstrip("/:")
        return v.strip("/")

    @field_validator("autofix_threshold", "alert_threshold")
    @classmethod
    def _sane_threshold(cls, v: float) -> float:
        return min(max(v, 0.0), 1.0)

    # --- Derived values ---

    @property
    def model(self) -> str:
        return self.llm_model or PROVIDER_DEFAULTS[self.llm_provider]["model"]

    @property
    def base_url(self) -> str:
        return self.llm_base_url or PROVIDER_DEFAULTS[self.llm_provider]["base_url"]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "docsentry.db"

    @property
    def repo_cache_path(self) -> Path:
        """Where a runtime-cloned copy of the watched repo is kept."""
        slug = self.target_repo.replace("/", "__") or "repo"
        return self.data_dir / "repos" / slug

    @property
    def clone_url(self) -> str:
        """Authenticated HTTPS clone URL for the watched repo."""
        if self.github_token:
            return (
                f"https://x-access-token:{self.github_token}"
                f"@github.com/{self.target_repo}.git"
            )
        return f"https://github.com/{self.target_repo}.git"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_run(self) -> list[str]:
        """Return problems blocking a real pipeline run. Empty list = ready."""
        problems: list[str] = []
        if not self.target_repo:
            problems.append("target_repo is not set (expected 'owner/name')")
        elif "/" not in self.target_repo:
            problems.append(
                f"target_repo must be 'owner/name', got {self.target_repo!r}"
            )
        if not self.github_token:
            problems.append("github_token is not set")
        if self.llm_provider in PROVIDERS_REQUIRING_KEY and not self.llm_api_key:
            problems.append(
                f"llm_api_key is not set (required by provider {self.llm_provider!r})"
            )
        if self.alert_threshold > self.autofix_threshold:
            problems.append(
                f"alert_threshold ({self.alert_threshold}) is above "
                f"autofix_threshold ({self.autofix_threshold}); nothing would "
                "ever be auto-fixed"
            )
        return problems

    def public_dict(self) -> dict:
        """Config safe to expose over HTTP: no secrets, only whether they exist."""
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.model,
            "llm_base_url": self.base_url,
            "llm_api_key_set": bool(self.llm_api_key),
            "github_token_set": bool(self.github_token),
            "target_repo": self.target_repo,
            "autofix_threshold": self.autofix_threshold,
            "alert_threshold": self.alert_threshold,
            "max_docs_per_change": self.max_docs_per_change,
            "retrieval_backend": self.retrieval_backend,
            "require_approval": self.require_approval,
            "dry_run": self.dry_run,
            "admin_enabled": bool(self.admin_token),
        }


settings = Settings()
