"""Provider client construction and caching."""
from __future__ import annotations

import pytest

from docsentry.config import settings
from docsentry.llm import LLMError
from docsentry.llm.client import _cached, _signature, get_client


@pytest.fixture(autouse=True)
def _clear_cache():
    _cached["sig"] = None
    _cached["client"] = None
    yield


def test_client_is_reused_across_calls():
    assert get_client() is get_client()


def test_client_is_rebuilt_when_the_provider_changes(monkeypatch):
    groq = get_client()
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    ollama = get_client()
    assert ollama is not groq
    assert "11434" in str(ollama.base_url)


def test_client_is_rebuilt_when_the_key_rotates(monkeypatch):
    first = get_client()
    monkeypatch.setattr(settings, "llm_api_key", "gsk_rotated")
    assert get_client() is not first


def test_cache_never_retains_the_api_key(monkeypatch):
    """An lru_cache keyed on the raw settings kept every key ever used
    reachable in memory for the process lifetime."""
    monkeypatch.setattr(settings, "llm_api_key", "gsk_super_secret")
    get_client()
    assert "gsk_super_secret" not in str(_cached["sig"])


def test_cache_holds_only_one_client(monkeypatch):
    for key in ("a", "b", "c"):
        monkeypatch.setattr(settings, "llm_api_key", key)
        get_client()
    # One slot, not an unbounded map of every configuration ever seen.
    assert set(_cached) == {"sig", "client"}


def test_signature_changes_with_each_input(monkeypatch):
    base = _signature()
    monkeypatch.setattr(settings, "llm_timeout", 99.0)
    assert _signature() != base


def test_missing_key_for_groq_raises_before_any_request(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(LLMError, match="requires llm_api_key"):
        get_client()


def test_ollama_needs_no_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "llm_api_key", "")
    # The SDK rejects an empty key, so a placeholder is substituted.
    assert get_client() is not None
