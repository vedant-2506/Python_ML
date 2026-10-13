"""Small, dependency-light Groq API client for structured JSON responses."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODEL, GROQ_TIMEOUT


class GroqError(RuntimeError):
    """Raised for configuration, availability, transport, or response failures."""


def _request(path: str, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    if not GROQ_API_KEY:
        raise GroqError("GROQ_API_KEY is not configured")
    headers = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Accept": "application/json",
    "User-Agent": "RankResume/1.0",
        }
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{GROQ_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=GROQ_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise GroqError(f"Groq HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise GroqError(f"Groq request failed: {exc}") from exc


def verify_model(model: str = GROQ_MODEL) -> None:
    """Confirm the configured model is advertised by Groq before generation."""
    payload = _request("/models")
    model_ids = {item.get("id") for item in payload.get("data", []) if isinstance(item, dict)}
    if model not in model_ids:
        raise GroqError(f"configured Groq model {model!r} is not currently available")


def generate_json(prompt: str, model: str = GROQ_MODEL) -> dict[str, Any]:
    payload = _request(
        "/chat/completions",
        method="POST",
        body={
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return only valid JSON. Do not include Markdown."},
                {"role": "user", "content": prompt},
            ],
        },
    )
    try:
        content = payload["choices"][0]["message"]["content"]
        result = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise GroqError("Groq returned an invalid structured response") from exc
    if not isinstance(result, dict):
        raise GroqError("Groq JSON response must be an object")
    return result
