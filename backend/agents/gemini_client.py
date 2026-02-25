"""
LLM API client — uses google-genai SDK with Anthropic fallback.

Model priority cascade:
  1. Gemini models (first choice, high free-tier)
     - gemini-2.0-flash-lite
     - gemini-2.5-flash-lite
     - gemini-2.0-flash
  2. Anthropic models (fallback)
     - claude-3-5-haiku-20241022
     - claude-3-haiku-20240307
"""
from __future__ import annotations
import os
import json
import time
from dotenv import load_dotenv

load_dotenv()

_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

# ── Gemini Setup ──────────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types
    _gemini_client = genai.Client(api_key=_GEMINI_KEY) if _GEMINI_KEY else None
except ImportError:
    _gemini_client = None

# ── Anthropic Setup ───────────────────────────────────────────────────────────
try:
    import anthropic
    _anthropic_client = anthropic.Anthropic(api_key=_ANTHROPIC_KEY) if _ANTHROPIC_KEY else None
except ImportError:
    _anthropic_client = None

# ── OpenAI Setup ──────────────────────────────────────────────────────────────
try:
    import openai
    _openai_client = openai.OpenAI(api_key=_OPENAI_KEY) if _OPENAI_KEY else None
except ImportError:
    _openai_client = None

GEMINI_MODELS = [
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
]

ANTHROPIC_MODELS = [
    "claude-3-5-haiku-20241022",
    "claude-3-haiku-20240307",
]

OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-3.5-turbo",
]

_DIS_SYSTEM = (
    "You are an expert AI agent in a Document Intelligence System (DIS) "
    "for regulatory PDF processing. The system extracts structure deterministically "
    "and you reason about what was found. Be concise, technical, and grounded in the data."
)


def query(
    prompt: str,
    system_extra: str = "",
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    """
    Query LLM with automatic model fallback (Gemini → Anthropic → OpenAI) and retry on 429.
    Never raises — returns a descriptive fallback string on persistent failure.
    """
    if not _gemini_client and not _anthropic_client and not _openai_client:
        return "[LLM error: No active LLM API keys (Gemini, Anthropic, or OpenAI)]"

    system = _DIS_SYSTEM + (" " + system_extra if system_extra else "")

    # 1. Try Gemini
    if _gemini_client:
        for model in GEMINI_MODELS:
            for attempt in range(2):
                try:
                    response = _gemini_client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            temperature=temperature,
                            max_output_tokens=max_tokens,
                        ),
                    )
                    text = (response.text or "").strip()
                    if text:
                        return text
                except Exception as exc:
                    err = str(exc)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        if attempt < 1:
                            time.sleep(8)
                        else:
                            break  # Try next Gemini model
                    elif "404" in err or "NOT_FOUND" in err:
                        break  # Try next Gemini model (not available on this key)
                    else:
                        break  # Unknown error, try next model

    # 2. Try Anthropic (Fallback)
    if _anthropic_client:
        for model in ANTHROPIC_MODELS:
            for attempt in range(2):
                try:
                    response = _anthropic_client.messages.create(
                        model=model,
                        system=system,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    text = response.content[0].text.strip()
                    if text:
                        return text
                except Exception as exc:
                    err = str(exc).lower()
                    if "rate_limit" in err or "429" in err:
                        if attempt < 1:
                            time.sleep(8)
                        else:
                            break  # Try next Anthropic model
                    else:
                        break  # Unknown error, try next model

    # 3. Try OpenAI (Fallback 2)
    if _openai_client:
        for model in OPENAI_MODELS:
            for attempt in range(2):
                try:
                    response = _openai_client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    text = response.choices[0].message.content.strip()
                    if text:
                        return text
                except Exception as exc:
                    err = str(exc).lower()
                    if "429" in err or "rate limit" in err:
                        if attempt < 1:
                            time.sleep(8)
                        else:
                            break  # Try next OpenAI model
                    else:
                        break  # Unknown error, try next model

    return "[LLM reasoning: All Gemini, Anthropic, and OpenAI models exhausted or rate-limited]"


def query_json(
    prompt: str,
    system_extra: str = "",
    fallback: dict | None = None,
) -> dict:
    """Query LLM expecting a JSON response. Returns fallback dict on error."""
    raw = query(
        prompt + "\n\nRespond with valid JSON only. No markdown fences, no explanation.",
        system_extra=system_extra,
        temperature=0.1,
        max_tokens=512,
    )
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            parts = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned)
    except Exception:
        return fallback or {}
