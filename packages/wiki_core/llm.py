"""OpenRouter LLM integration."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from wiki_core.config import ENV_FILE, load_dotenv

load_dotenv()


def get_openrouter_models() -> list[str]:
    primary = os.environ.get("OPENROUTER_MODEL", "openrouter/free").strip()
    fallbacks_str = os.environ.get("OPENROUTER_FALLBACK_MODELS", "").strip()
    models: list[str] = []
    if primary:
        models.append(primary)
    if fallbacks_str:
        for m in fallbacks_str.split(","):
            m_clean = m.strip()
            if m_clean and m_clean not in models:
                models.append(m_clean)
    for m in (
        "nvidia/nemotron-3-super-120b-a12b:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter/free",
    ):
        if m not in models:
            models.append(m)
    return models


def call_openrouter(
    prompt: str,
    system_prompt: str = "You are a helpful AI Knowledge Base Assistant.",
    verbose: bool = True,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key or api_key == "your_openrouter_api_key_here":
        raise ValueError(
            f"OpenRouter API key not configured. Add OPENROUTER_API_KEY to {ENV_FILE}"
        )

    models = get_openrouter_models()
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/llm-wiki/wiki",
        "X-Title": "LLM Wiki",
        "Content-Type": "application/json",
    }
    last_error: str | None = None

    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        if verbose:
            print(f"Querying OpenRouter ({model})...")
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                text = res_json["choices"][0]["message"]["content"].strip()
                if text:
                    return text
        except urllib.error.HTTPError as http_err:
            last_error = f"HTTP {http_err.code}: {http_err.reason}"
            if verbose:
                print(f"[fallback] {model}: {last_error}")
        except Exception as e:
            last_error = str(e)
            if verbose:
                print(f"[fallback] {model}: {e}")

    raise RuntimeError(f"All OpenRouter models failed. Last error: {last_error}")
