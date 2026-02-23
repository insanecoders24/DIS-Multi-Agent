"""
Gemini API client — uses google-genai SDK with retry and model fallback.

Model priority (all on the same API key):
  1. gemini-2.0-flash-lite   — lowest quota cost, highest RPM
  2. gemini-2.0-flash        — fallback
  3. gemini-2.5-flash-lite   — second fallback

Retry: up to 3 attempts with 10s waits on 429.
"""
from __future__ import annotations
import os
import json
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

_KEY = os.getenv("GEMINI_API_KEY", "")
_client = genai.Client(api_key=_KEY) if _KEY else None

# Model cascade — tiyer on quota cost
MODELS = [
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
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
    Query Gemini with automatic model fallback and retry on 429.
    Never raises — returns a descriptive fallback string on persistent failure.
    """
    if not _client:
        return "[Gemini API key not configured]"

    system = _DIS_SYSTEM + (" " + system_extra if system_extra else "")

    for model in MODELS:
        for attempt in range(3):
            try:
                response = _client.models.generate_content(
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
                    # Rate limited — wait and retry or try next model
                    if attempt < 2:
                        time.sleep(12)
                    else:
                        break  # try next model
                elif "404" in err or "NOT_FOUND" in err:
                    break  # model not available — try next
                else:
                    return f"[Gemini error: {err[:120]}]"

    return "[Gemini reasoning: all models rate-limited — reasoning will resume shortly]"


def query_json(
    prompt: str,
    system_extra: str = "",
    fallback: dict | None = None,
) -> dict:
    """Query Gemini expecting a JSON response. Returns fallback dict on error."""
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
