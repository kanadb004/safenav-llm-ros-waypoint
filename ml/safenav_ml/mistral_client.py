"""Minimal REST client for the Mistral chat completions API (docs/phase-4-brief.md section 4).

No SDK: plain ``requests``. Honors ``x-ratelimit-remaining-req-minute`` and backs off on 429.
Never prints ``MISTRAL_API_KEY``.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

API_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise MistralError("MISTRAL_API_KEY is not set in the environment")
    return key


def chat(
    messages: List[Dict[str, str]],
    model: str = "ministral-14b-latest",
    temperature: float = 1.0,
    json_object: bool = True,
    max_retries: int = 5,
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    """One chat completion call. Returns the parsed JSON body dict if ``json_object`` is set,
    else the raw text. Retries with exponential backoff on 429 and 5xx; respects the
    ``x-ratelimit-remaining-req-minute`` header by sleeping to the next minute window when it
    hits zero."""
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}

    delay = 2.0
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=timeout_s)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(delay)
            delay *= 2
            continue

        remaining = resp.headers.get("x-ratelimit-remaining-req-minute")
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", delay))
            time.sleep(retry_after)
            delay *= 2
            continue
        if resp.status_code >= 500:
            last_error = MistralError(f"server error {resp.status_code}: {resp.text[:200]}")
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code != 200:
            raise MistralError(f"mistral API {resp.status_code}: {resp.text[:500]}")

        if remaining is not None and remaining.isdigit() and int(remaining) == 0:
            time.sleep(2.0)

        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        if not json_object:
            return {"text": content, "usage": body.get("usage", {})}
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise MistralError(f"non-JSON content despite json_object mode: {exc}") from exc
        return {"data": data, "usage": body.get("usage", {})}

    raise MistralError(f"exhausted retries: {last_error}")


def unwrap_one_level(data: Dict[str, Any], expected_keys: List[str]) -> Dict[str, Any]:
    """The model sometimes nests the requested object one level deep, e.g.
    ``{"response": {...}}``. If none of ``expected_keys`` are present at the top level but
    there is exactly one nested dict value, unwrap it."""
    if any(k in data for k in expected_keys):
        return data
    nested = [v for v in data.values() if isinstance(v, dict)]
    if len(nested) == 1:
        return nested[0]
    return data
