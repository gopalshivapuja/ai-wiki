"""OpenRouter LLM integration."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()


def get_models() -> list[str]:
    primary = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free").strip()
    fallbacks = os.environ.get(
        "OPENROUTER_FALLBACK_MODELS",
        "nvidia/nemotron-3-super-120b-a12b:free,qwen/qwen3-next-80b-a3b-instruct:free,"
        "meta-llama/llama-3.3-70b-instruct:free,openrouter/free",
    )
    models = []
    for m in [primary] + [x.strip() for x in fallbacks.split(",") if x.strip()]:
        if m not in models:
            models.append(m)
    return models


def call_llm(prompt: str, system: str = "You are a helpful AI assistant.") -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key or key == "your_openrouter_api_key_here":
        raise ValueError("OPENROUTER_API_KEY not configured")

    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://github.com/llm-wiki/wiki",
        "X-Title": "LLM Wiki",
        "Content-Type": "application/json",
    }
    last_err = None
    for model in get_models():
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode())
                text = data["choices"][0]["message"]["content"].strip()
                if text:
                    return text
        except Exception as e:
            last_err = str(e)
    raise RuntimeError(f"All models failed: {last_err}")
