"""OpenRouter LLM integration."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_BASE = "https://openrouter.ai/api/v1"
MODELS_CACHE_TTL = 3600

# Preference ladder, ordered by what these models actually do when called — not by size on
# paper. Measured 2026-08:
#   nemotron-3.5-lightning:free      0.8s, 1M context  -> best fit for hour-long transcripts
#   nemotron-3-ultra-550b-a55b:free  listed but the provider 404s; kept for when it recovers
#   nemotron-3-super-120b-a12b:free  works, but 22.6s for eight tokens
#   nemotron-3-nano-30b-a3b:free     0.7s, smaller context
# Anything unlisted falls through to the generic free pool below.
PREFERRED_MODELS = (
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
)
# Second-tier ordering for whatever else the catalogue offers.
PREFERRED_FREE_HINTS = ("nemotron", "deepseek", "llama", "qwen", "mistral", "gemma", "phi")

# Never worth trying: responds 200 with empty content, which reads as a silent failure.
BLOCKED_MODELS = {"openrouter/free", "openrouter/auto"}

# Context windows in tokens, for picking a model that can hold a long source.
MODEL_CONTEXT: dict[str, int] = {}

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
        MODEL_CONTEXT.update(
            {m["id"]: m.get("context_length") or 0 for m in data.get("data", []) if m.get("id")}
        )
    except Exception as exc:
        error = str(exc)
        logger.warning("Could not fetch the OpenRouter model list: %s", exc)

    with _cache_lock:
        _models_cache.update({"at": time.time(), "ids": ids, "error": error})
    return ids, error


def get_models(min_context: int = 0) -> list[str]:
    """Ordered candidates to try.

    Anything set in OPENROUTER_MODEL wins, then the measured Nemotron ladder, then whatever
    else the catalogue offers free. `min_context` drops models too small to hold the input,
    so a long transcript is not silently truncated into a worse note.
    """
    configured = _configured_models()
    available, _error = fetch_available_models()

    if not available:
        # Catalogue unreachable: trust the configuration and let the call itself report.
        return configured or list(PREFERRED_MODELS)

    available_set = set(available)
    ordered = [m for m in configured if m in available_set]

    unknown = [m for m in configured if m not in available_set]
    if unknown:
        logger.warning(
            "Configured model(s) not offered by OpenRouter and skipped: %s", ", ".join(unknown)
        )

    for m in PREFERRED_MODELS:
        if m in available_set and m not in ordered:
            ordered.append(m)

    free = [
        m
        for m in available
        if m.endswith(":free") and m not in ordered and m not in BLOCKED_MODELS
    ]
    free.sort(key=lambda m: next((i for i, h in enumerate(PREFERRED_FREE_HINTS) if h in m), 99))
    ordered.extend(free)

    ordered = [m for m in ordered if m not in BLOCKED_MODELS]
    if min_context:
        big_enough = [m for m in ordered if MODEL_CONTEXT.get(m, 0) >= min_context]
        # Only apply the filter if something survives it; a short list beats no list.
        ordered = big_enough or ordered

    # Models that just rate-limited us go to the back. Without this every request paid the
    # same failed round trips before reaching one that answers.
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


# Roughly four characters per token; enough to avoid picking a model that cannot hold the
# input, without pulling in a tokeniser.
def estimate_tokens(text: str) -> int:
    return len(text) // 4


def _prepare(prompt: str, system: str) -> tuple[str, dict, list[str]]:
    key = get_api_key()
    if not key:
        raise LLMNotConfigured(
            "OPENROUTER_API_KEY is not set. Add it to the environment to enable AI features."
        )
    # Leave headroom for the reply on top of the prompt.
    models = get_models(min_context=estimate_tokens(prompt + system) + 4096)
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


def _body(
    model: str, prompt: str, system: str, stream: bool, max_tokens: int = 2048
) -> bytes:
    return json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "stream": stream,
            # Several Nemotron variants otherwise prepend their chain of thought to the
            # answer ("Here's a thinking process..."), which would end up inside a note.
            "reasoning": {"exclude": True},
        }
    ).encode()


# Reasoning that leaks despite the request above: an explicit block, or a preamble the model
# writes before the real answer.
_THINK_BLOCK = re.compile(
    r"<(think|thinking|reasoning)>.*?</\1>|^\s*<(think|thinking|reasoning)>.*",
    re.DOTALL | re.IGNORECASE,
)
_PREAMBLE = re.compile(
    r"^\s*(?:okay|alright|first|let me|let's|we need to|i need to|the user (?:wants|is asking)"
    r"|here'?s (?:a |my )?(?:thinking|plan|approach))\b[^\n]*(?:\n(?![#\-*\d]).*)*?\n\s*\n",
    re.IGNORECASE,
)


def clean_output(text: str) -> str:
    """Strip leaked chain-of-thought so it never reaches a note."""
    out = _THINK_BLOCK.sub("", text or "").strip()
    # Only trim a preamble when real content follows it — never return nothing.
    trimmed = _PREAMBLE.sub("", out, count=1).strip()
    return trimmed or out


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


def call_llm_json(prompt: str, system: str, max_tokens: int = 6000) -> dict:
    """Call for a JSON object, trying models until one actually returns parseable JSON.

    Needed because the Nemotron family is reasoning-first: it writes its whole chain of
    thought as ordinary content and ignores `reasoning: {exclude: true}`. At the default
    token ceiling the reasoning consumed the entire budget and the JSON never arrived — so
    extraction silently produced nothing at all. Three defences: a much larger budget, a
    request for JSON output where the provider supports it, and treating an unparseable
    reply as a failure so the next model gets a turn.
    """
    _key, headers, models = _prepare(prompt, system)
    attempts: list[str] = []

    for model in models:
        try:
            body = json.loads(_body(model, prompt, system, stream=False, max_tokens=max_tokens))
            body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(
                f"{API_BASE}/chat/completions",
                data=json.dumps(body).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode())
            text = clean_output(data["choices"][0]["message"]["content"] or "")
            parsed = extract_json(text)
            if parsed is not None:
                logger.info("Structured reply via %s", model)
                return parsed
            attempts.append(f"{model}: no JSON in {len(text)} chars")
        except urllib.error.HTTPError as exc:
            _note_failure(model, exc, attempts)
        except Exception as exc:
            attempts.append(f"{model}: {exc}")

    raise _exhausted(attempts)


def extract_json(text: str) -> dict | None:
    """Find a JSON object in a reply that may be wrapped in prose or a code fence."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


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
            text = clean_output(data["choices"][0]["message"]["content"] or "")
            if text:
                logger.info("LLM answered via %s", model)
                return text
            # openrouter/free returns 200 with no content — a silent failure unless caught.
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
                # A leaked <think> block arrives in pieces, so hold the opening text back
                # until we know whether it closes. Capped so a model that never closes one
                # still shows something.
                head, holding = "", True
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
                    if not piece:
                        continue
                    if holding:
                        head += piece
                        low = head.lstrip().lower()
                        if not low.startswith("<think"):
                            holding = False
                            piece, head = head, ""
                        elif "</think" in low or len(head) > 4000:
                            piece = clean_output(head)
                            holding, head = False, ""
                            if not piece:
                                continue
                        else:
                            continue
                    produced = True
                    yield piece
            if holding and head:
                # The block never closed; emit whatever survives cleaning.
                remainder = clean_output(head)
                if remainder:
                    produced = True
                    yield remainder
            if produced:
                logger.info("LLM streamed via %s", model)
                return
            attempts.append(f"{model}: empty stream")
        except urllib.error.HTTPError as exc:
            _note_failure(model, exc, attempts)
        except Exception as exc:
            attempts.append(f"{model}: {exc}")

    raise _exhausted(attempts)
