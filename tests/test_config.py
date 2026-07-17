"""Settings: defaults, derived values, and readiness reporting."""
from __future__ import annotations

from docsentry.config import PROVIDER_DEFAULTS, Settings, settings


def test_import_never_raises_without_env():
    """The whole v1 app died at import when .env was absent, because
    github_token had no default. A bare Settings() must construct."""
    s = Settings(_env_file=None)
    assert s.github_token == ""
    assert s.target_repo == ""
    assert s.validate_for_run()          # reports problems rather than raising


def test_provider_defaults_fill_in_model_and_url():
    s = Settings(_env_file=None, llm_provider="groq")
    assert s.model == PROVIDER_DEFAULTS["groq"]["model"]
    assert s.base_url == PROVIDER_DEFAULTS["groq"]["base_url"]

    ollama = Settings(_env_file=None, llm_provider="ollama")
    assert "11434" in ollama.base_url


def test_explicit_model_overrides_the_default():
    s = Settings(_env_file=None, llm_provider="groq", llm_model="my-model")
    assert s.model == "my-model"


def test_target_repo_accepts_a_full_url():
    for raw in ("https://github.com/acme/repo",
                "https://github.com/acme/repo.git",
                "git@github.com:acme/repo.git",
                "acme/repo"):
        assert Settings(_env_file=None, target_repo=raw).target_repo == "acme/repo"


def test_thresholds_are_clamped():
    s = Settings(_env_file=None, autofix_threshold=5, alert_threshold=-2)
    assert s.autofix_threshold == 1.0
    assert s.alert_threshold == 0.0


def test_inverted_thresholds_are_reported():
    s = Settings(_env_file=None, target_repo="a/b", github_token="t",
                 llm_provider="ollama", autofix_threshold=0.2,
                 alert_threshold=0.9)
    assert any("would ever be auto-fixed" in p for p in s.validate_for_run())


def test_ollama_needs_no_api_key():
    s = Settings(_env_file=None, llm_provider="ollama",
                 target_repo="a/b", github_token="t")
    assert s.validate_for_run() == []


def test_groq_requires_an_api_key():
    s = Settings(_env_file=None, llm_provider="groq",
                 target_repo="a/b", github_token="t")
    assert any("llm_api_key" in p for p in s.validate_for_run())


def test_clone_url_embeds_the_token():
    s = Settings(_env_file=None, target_repo="acme/repo", github_token="ghp_x")
    assert s.clone_url == "https://x-access-token:ghp_x@github.com/acme/repo.git"


def test_clone_url_without_a_token_is_anonymous():
    s = Settings(_env_file=None, target_repo="acme/repo")
    assert s.clone_url == "https://github.com/acme/repo.git"


def test_repo_cache_path_is_slugged(tmp_path):
    s = Settings(_env_file=None, target_repo="acme/repo", data_dir=tmp_path)
    assert s.repo_cache_path == tmp_path / "repos" / "acme__repo"


def test_public_dict_hides_secrets():
    s = Settings(_env_file=None, github_token="ghp_secret", llm_api_key="gsk_secret")
    pub = s.public_dict()
    assert pub["github_token_set"] is True
    assert pub["llm_api_key_set"] is True
    assert "ghp_secret" not in str(pub)
    assert "gsk_secret" not in str(pub)


def test_cors_origins_split():
    s = Settings(_env_file=None, cors_origins="https://a.dev, https://b.dev")
    assert s.cors_origin_list == ["https://a.dev", "https://b.dev"]


def test_db_path_is_absolute_and_under_data_dir(tmp_path):
    """v1 used a bare relative path, so the database silently depended on the
    directory you launched from."""
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.db_path.is_absolute()
    assert s.db_path.parent == tmp_path


def test_max_docs_default_is_one():
    """v1 judged the top 3 sections and filed an issue for each."""
    assert Settings(_env_file=None).max_docs_per_change == 1


def test_defaults_are_deploy_safe():
    s = Settings(_env_file=None)
    assert s.retrieval_backend == "bm25"      # no torch
    assert s.llm_provider == "groq"           # no localhost
    assert s.admin_token == ""                # write endpoints closed
