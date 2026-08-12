"""OpenRouter LLM integration."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_BASE = "https://openrouter.ai/api/v1"
MODELS_CACHE_TTL = 3600

# Deliberately empty: model slugs go stale, so the working set is discovered from the live
# catalogue rather than hardcoded. These are only a starting preference order.
PREFERRED_FREE_HINTS = ("deepseek", "llama", "qwen", "mistral", "gemma", "phi")

_models_cache: dict = {"at": 0.0, "ids": [], "error": None}
_cache_lock = threading.Lock()

# model id -> unix time until which we treat it as rate limited.
_rate_limited: dict[str, float] = {}
RATE_LIMIT_COOLDOWN = 600

# A model that has not produced its first byte by now is not worth waiting for when there
# are a dozen alternatives.
FIRST_TOKEN_TIMEOUT = 25
MAX_ATTEMPTS = 4


class LLMNotConfigured(RuntimeError):
    """No usable model or API key. The message is safe to show the user."""


def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key or key == "your_openrouter_api_key_here":
        return ""
    return key


def _configured_models() -> list[str]:
    primary = os.environ.get("OPENROUTER_MODEL", "").strip()
    fallbacks = os.environ.get("OPENROUTER_FALLBACK_MODELS", "")
    models: list[str] = []
    for m in [primary] + [x.strip() for x in fallbacks.split(",")]:
        if m and m not in models:
            models.append(m)
    return models


def fetch_available_models(force: bool = False) -> tuple[list[str], str | None]:
    """Model ids OpenRouter currently serves. Cached for an hour. Returns (ids, error)."""
    with _cache_lock:
        fresh = time.time() - _models_cache["at"] < MODELS_CACHE_TTL
        if fresh and not force and (_models_cache["ids"] or _models_cache["error"]):
            return _models_cache["ids"], _models_cache["error"]

    ids: list[str] = []
    error: str | None = None
    try:
        req = urllib.request.Request(f"{API_BASE}/models", headers={"User-Agent": "LLMWiki/0.3"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        ids = [m["id"] for m in data.get("data", []) if m.get("id")]
    except Exception as exc:
        error = str(exc)
        logger.warning("Could not fetch the OpenRouter model list: %s", exc)

    with _cache_lock:
        _models_cache.update({"at": time.time(), "ids": ids, "error": error})
    return ids, error


def get_models() -> list[str]:
    """Ordered candidates to try.

    Configured ids that OpenRouter actually serves come first, then free models discovered
    from the catalogue. Previously the configured list was used blind — and every id in the
    shipped default was stale, so every request failed with 'All models failed'.
    """
    configured = _configured_models()
    available, _error = fetch_available_models()

    if not available:
        # Catalogue unreachable: trust the configuration and let the call itself report.
        return configured

    available_set = set(available)
    ordered = [m for m in configured if m in available_set]

    unknown = [m for m in configured if m not in available_set]
    if unknown:
        logger.warning(
            "Configured model(s) not offered by OpenRouter and skipped: %s", ", ".join(unknown)
        )

    free = [m for m in available if m.endswith(":free") and m not in ordered]
    free.sort(key=lambda m: next((i for i, h in enumerate(PREFERRED_FREE_HINTS) if h in m), 99))
    ordered.extend(free)

    # Models that just rate-limited us go to the back. Without this every question paid the
    # same two failed round trips before reaching one that answers.
    now = time.time()
    return sorted(ordered, key=lambda m: _rate_limited.get(m, 0) > now)


def model_status() -> dict:
    """Diagnostics for the UI: what is configured, what works, what does not."""
    configured = _configured_models()
    available, error = fetch_available_models()
    available_set = set(available)
    usable = get_models()
    return {
        "configured": configured,
        "valid": [m for m in configured if m in available_set],
        "invalid": [m for m in configured if available and m not in available_set],
        "usable_count": len(usable),
        "will_use": usable[0] if usable else None,
        "free_available": [m for m in available if m.endswith(":free")][:20],
        "api_key_set": bool(get_api_key()),
        "catalogue_error": error,
    }


def _prepare(prompt: str, system: str) -> tuple[str, dict, list[str]]:
    key = get_api_key()
    if not key:
        raise LLMNotConfigured(
            "OPENROUTER_API_KEY is not set. Add it to the environment to enable AI features."
        )
    models = get_models()
    if not models:
        raise LLMNotConfigured(
            "No usable model. Set OPENROUTER_MODEL to an id from https://openrouter.ai/models."
        )
    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://github.com/gopalshivapuja/ai-wiki",
        "X-Title": "LLM Wiki",
        "Content-Type": "application/json",
    }
    return key, headers, models[:MAX_ATTEMPTS]


def _body(model: str, prompt: str, system: str, stream: bool) -> bytes:
    return json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
            "stream": stream,
        }
    ).encode()


def _note_failure(model: str, exc: urllib.error.HTTPError, attempts: list[str]) -> None:
    detail = exc.read().decode("utf-8", errors="ignore")[:200] if exc.fp else ""
    attempts.append(f"{model}: HTTP {exc.code} {detail}")
    if exc.code in (429, 402):
        _rate_limited[model] = time.time() + RATE_LIMIT_COOLDOWN
        logger.info("%s is rate limited; deprioritised for %ds", model, RATE_LIMIT_COOLDOWN)


def _exhausted(attempts: list[str]) -> LLMNotConfigured:
    logger.error("All models failed: %s", "; ".join(attempts))
    return LLMNotConfigured(
        "Every available model failed or is rate limited right now. Free models allow 1,000 "
        "requests/day after a one-time $10 credit purchase. See /api/llm/models."
    )


def call_llm(prompt: str, system: str = "You are a helpful AI assistant.") -> str:
    _key, headers, models = _prepare(prompt, system)
    attempts: list[str] = []

    for model in models:
        try:
            req = urllib.request.Request(
                f"{API_BASE}/chat/completions",
                data=_body(model, prompt, system, stream=False),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
            text = (data["choices"][0]["message"]["content"] or "").strip()
            if text:
                logger.info("LLM answered via %s", model)
                return text
            attempts.append(f"{model}: empty response")
        except urllib.error.HTTPError as exc:
            _note_failure(model, exc, attempts)
        except Exception as exc:
            attempts.append(f"{model}: {exc}")

    raise _exhausted(attempts)


def stream_llm(prompt: str, system: str = "You are a helpful AI assistant."):
    """Yield answer text as the model produces it.

    Generation is the slow part — a free model can take half a minute — so showing the first
    words immediately is the difference between "working" and "frozen".
    """
    _key, headers, models = _prepare(prompt, system)
    attempts: list[str] = []

    for model in models:
        try:
            req = urllib.request.Request(
                f"{API_BASE}/chat/completions",
                data=_body(model, prompt, system, stream=True),
                headers={**headers, "Accept": "text/event-stream"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=FIRST_TOKEN_TIMEOUT) as resp:
                produced = False
                for raw in resp:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        piece = chunk["choices"][0].get("delta", {}).get("content") or ""
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if piece:
                        produced = True
                        yield piece
            if produced:
                logger.info("LLM streamed via %s", model)
                return
            attempts.append(f"{model}: empty stream")
        except urllib.error.HTTPError as exc:
            _note_failure(model, exc, attempts)
        except Exception as exc:
            attempts.append(f"{model}: {exc}")

    raise _exhausted(attempts)
