"""LLM-powered divergence detection with strict JSON output."""
import json
import re

from openai import OpenAI

from docsentry.config import settings

# Use Ollama's OpenAI-compatible API (no real API key needed)
_client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="dummy",  # Ollama accepts any string as API key
)

SYSTEM = """You are DocSentry, an agent that detects when documentation \
no longer matches code behavior.

You will receive:
1. A semantic code change (what changed in the code)
2. A documentation section that may describe that code

Decide if the documentation now contains false or outdated statements \
because of this change.

Respond with ONLY a JSON object, no markdown fences, no prose:
{
  "diverged": true/false,
  "confidence": 0.0-1.0,
  "mismatch": "one sentence: exactly which doc claim is now false, or empty",
  "suggested_fix": "the corrected version of ONLY the false lines, or empty"
}

Rules:
- diverged=true ONLY if the doc makes a claim the change contradicts.
- A new undocumented function is diverged=false (missing docs imply lying docs).
- confidence reflects how certain you are of the verdict.
- suggested_fix must preserve the doc's tone and format (markdown stays markdown)."""


def _parse_verdict(raw: str) -> dict:
    """Extract a verdict dict from a model reply, tolerating fences/prose."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    # try whole string, then the first {...} block found anywhere in the text
    candidates = [raw]
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        return {
            "diverged": bool(data.get("diverged", False)),
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "mismatch": str(data.get("mismatch", "") or ""),
            "suggested_fix": str(data.get("suggested_fix", "") or ""),
        }
    return {"diverged": False, "confidence": 0.0,
            "mismatch": f"UNPARSEABLE: {raw[:200]}", "suggested_fix": ""}


def check_divergence(change: dict, doc_section: dict) -> dict:
    user_msg = f"""CODE CHANGE:
File: {change['file']}
Kind: {change['kind']}
Detail: {change['detail']}

DOCUMENTATION SECTION ({doc_section['meta']['file']},
lines {doc_section['meta']['start_line']}-{doc_section['meta']['end_line']}):
---
{doc_section['content']}
---"""

    resp = _client.chat.completions.create(
        model=settings.divergence_model,
        max_tokens=800,
        # Force JSON output — small local models (e.g. orca-mini) otherwise
        # reply in prose. Ollama honors this on its OpenAI-compatible endpoint.
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )
    verdict = _parse_verdict(resp.choices[0].message.content or "")
    verdict["doc_id"] = doc_section["id"]
    verdict["doc_file"] = doc_section["meta"]["file"]
    verdict["doc_heading"] = doc_section["meta"]["heading"]
    return verdict