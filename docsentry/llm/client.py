"""One LLM client for every supported provider.

Groq, Gemini and Ollama all expose an OpenAI-compatible chat endpoint, so the
only things that vary are the base URL, the model name and whether a real API
key is required. That makes the provider a config value rather than a code
change — which is what lets the same agent run against a local Ollama during
development and a hosted model in production.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from openai import OpenAI, OpenAIError

from docsentry.config import PROVIDERS_REQUIRING_KEY, settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """The model could not be reached or refused the request."""


# Single-slot cache: one client, rebuilt when the config behind it changes.
# Keyed on a hash of the credential rather than the credential itself, and
# bounded to one entry — an lru_cache over the raw settings would keep every
# API key ever used reachable in memory for the process lifetime.
_cached: dict[str, Any] = {"sig": None, "client": None}


def _signature() -> tuple:
    key = settings.llm_api_key
    return (
        settings.llm_provider,
        settings.base_url,
        hashlib.sha256(key.encode()).hexdigest() if key else "",
        settings.llm_timeout,
        settings.llm_max_retries,
    )


def get_client() -> OpenAI:
    if settings.llm_provider in PROVIDERS_REQUIRING_KEY and not settings.llm_api_key:
        raise LLMError(
            f"provider {settings.llm_provider!r} requires llm_api_key, which is unset"
        )
    sig = _signature()
    if _cached["sig"] != sig:
        _cached["client"] = OpenAI(
            base_url=settings.base_url,
            # Ollama ignores the key but the SDK requires a non-empty string.
            api_key=settings.llm_api_key or "not-needed",
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )
        _cached["sig"] = sig
    return _cached["client"]


def parse_verdict(raw: str) -> dict[str, Any]:
    """Extract a verdict dict from a model reply, tolerating fences and prose.

    Small local models routinely wrap JSON in markdown fences or bolt an
    explanation onto the end, so a bare json.loads is not enough.
    """
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

    candidates = [raw]
    # Greedy match: the outermost {...} in the reply.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        candidates.append(m.group(0))

    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            confidence = float(data.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "diverged": bool(data.get("diverged", False)),
            # A model returning 0-100 instead of 0-1 is a common failure;
            # rescale rather than let it trip every threshold.
            "confidence": min(max(confidence / 100 if confidence > 1 else confidence, 0.0), 1.0),
            "mismatch": str(data.get("mismatch", "") or ""),
            "suggested_fix": str(data.get("suggested_fix", "") or ""),
        }

    log.warning("unparseable model reply: %s", raw[:200])
    return {
        "diverged": False,
        "confidence": 0.0,
        "mismatch": f"UNPARSEABLE MODEL REPLY: {raw[:200]}",
        "suggested_fix": "",
    }


def complete_json(system: str, user: str, *, max_tokens: int = 900) -> dict[str, Any]:
    """Ask the configured model for a JSON object and parse it.

    Note: Groq's json_object mode requires the literal word "json" to appear in
    the prompt; the system prompt satisfies this.
    """
    client = get_client()
    try:
        resp = client.chat.completions.create(
            model=settings.model,
            max_tokens=max_tokens,
            temperature=0,          # deterministic verdicts
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except OpenAIError as e:
        raise LLMError(f"{settings.llm_provider} request failed: {e}") from e

    return parse_verdict(resp.choices[0].message.content or "")


def probe() -> dict[str, Any]:
    """Cheap liveness check for /health. Never raises."""
    info: dict[str, Any] = {
        "provider": settings.llm_provider,
        "model": settings.model,
        "base_url": settings.base_url,
    }
    try:
        client = get_client()
        client.models.list()
        info["reachable"] = True
    except Exception as e:  # noqa: BLE001 - a health check must never throw
        info["reachable"] = False
        info["error"] = str(e)[:200]
    return info
