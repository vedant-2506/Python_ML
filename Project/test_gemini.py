"""Explicit Gemini smoke test; safe to import during normal pytest runs."""

from __future__ import annotations

import os
import sys

import pytest


def _run_gemini_request() -> str:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    with genai.Client(api_key=api_key) as client:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "models/gemini-3.1-flash-lite"),
            contents="Reply with: Gemini API is working!",
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=1)
                ),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
    return response.text or ""


@pytest.mark.integration
def test_gemini_api_integration() -> None:
    """Run only when explicitly requested with a configured API credential."""
    if os.getenv("RUN_GEMINI_INTEGRATION") != "1":
        pytest.skip("Set RUN_GEMINI_INTEGRATION=1 to run the live Gemini test")
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is not configured")
    try:
        response = _run_gemini_request()
    except Exception as exc:
        status = getattr(exc, "status", None) or getattr(exc, "code", None)
        if status in {408, 429, 500, 502, 503, 504}:
            pytest.skip(f"Gemini service unavailable ({status})")
        raise
    assert response.strip() == "Gemini API is working!"


def main() -> int:
    try:
        print(_run_gemini_request())
    except Exception as exc:
        print(f"Gemini integration test failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
