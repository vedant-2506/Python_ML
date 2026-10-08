"""LLM-backed ATS evaluation using the Gemini API."""

from __future__ import annotations

import atexit
import email.utils
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import errors
from google.genai import types

load_dotenv()

log = logging.getLogger(__name__)

_SCORE_KEYS = ("score", "ats_score", "final_score", "overall_score", "match_score", "fit_score")
_OUT_OF_100 = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:/|out of)\s*100", re.I)
_LABELLED = re.compile(r"(?:score|ats|overall|match|fit)\D{0,15}?(\d{1,3}(?:\.\d+)?)", re.I)
_MAX_RETRIES = 2
_MAX_RETRY_WAIT_SECONDS = 20.0
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_gemini_blocked_reason: Optional[str] = None


@lru_cache(maxsize=1)
def _get_gemini_client(api_key: str) -> genai.Client:
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    atexit.register(client.close)
    return client


def reset_gemini_failure_state() -> None:
    """Allow a new pipeline run to try again after a previous run was blocked."""
    global _gemini_blocked_reason
    _gemini_blocked_reason = None


def _error_details(exc: errors.APIError) -> tuple[dict[str, Any], list[str], Optional[float]]:
    payload = exc.details if isinstance(exc.details, dict) else {}
    error_payload = payload.get("error", payload)
    details = error_payload.get("details", []) if isinstance(error_payload, dict) else []
    quota_ids: list[str] = []
    retry_delay: Optional[float] = None

    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            detail_type = str(detail.get("@type", ""))
            if detail_type.endswith("QuotaFailure"):
                violations = detail.get("violations", [])
                if isinstance(violations, list):
                    quota_ids.extend(
                        str(violation.get("quotaId") or violation.get("quotaMetric") or "")
                        for violation in violations
                        if isinstance(violation, dict)
                    )
            elif detail_type.endswith("RetryInfo"):
                retry_delay = _parse_retry_delay(detail.get("retryDelay"))

    response_headers = getattr(exc.response, "headers", None)
    if response_headers:
        header_value = response_headers.get("Retry-After")
        header_delay = _parse_retry_after_header(header_value)
        if header_delay is not None:
            retry_delay = max(retry_delay or 0.0, header_delay)
    return error_payload if isinstance(error_payload, dict) else {}, quota_ids, retry_delay


def _parse_retry_delay(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", value)
        if match:
            return float(match.group(1))
    return None


def _parse_retry_after_header(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = email.utils.parsedate_to_datetime(str(value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _failure_category(
    code: int, error_payload: dict[str, Any], quota_ids: list[str]
) -> tuple[str, bool]:
    status = str(error_payload.get("status") or "").upper()
    message = str(error_payload.get("message") or "").lower()
    quota_text = " ".join(quota_ids).lower()

    if code == 429 and any(token in quota_text for token in ("perday", "per_day", "daily")):
        return "daily quota exhausted", True
    if any(token in f"{status} {message}" for token in ("billing", "payment", "billingdisabled")):
        return "billing/project restriction", True
    if code in {400, 401, 403}:
        if code == 401 or "api key" in message or "apikey" in message:
            return "invalid or unauthorized API key", True
        return "permanent API/project request error", True
    if code == 404:
        return "invalid or unavailable model", True
    if code == 429:
        return "rate limit", False
    if code == 503:
        return "temporary service unavailable", False
    return f"HTTP {code} API error", code not in _RETRYABLE_STATUS_CODES


def _retry_wait_seconds(attempt: int, server_delay: Optional[float]) -> float:
    exponential = min(0.5 * (2 ** (attempt - 1)), 8.0)
    if server_delay is not None:
        return max(exponential, server_delay) + random.uniform(0.0, 0.25)
    return random.uniform(exponential * 0.75, exponential * 1.25)


def _block_gemini(reason: str, code: int, quota_ids: list[str]) -> None:
    global _gemini_blocked_reason
    _gemini_blocked_reason = reason
    quota_text = f" quota_ids={','.join(quota_ids)}" if quota_ids else ""
    log.error(
        "Gemini scoring circuit opened: status=%s reason=%s%s; further requests "
        "are suppressed for this pipeline run",
        code,
        reason,
        quota_text,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    """Decode JSON payloads into mappings so the LLM scorer accepts database-shaped inputs."""
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def extract_numeric_score(value: Any) -> Optional[float]:
    """Find a valid 0-100 score in model output so failed responses remain distinguishable from zero."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if 0 <= value <= 100 else None
    if isinstance(value, dict):
        for key in _SCORE_KEYS:
            if key in value:
                found = extract_numeric_score(value[key])
                if found is not None:
                    return found
        return None
    if not isinstance(value, str):
        return None

    text = re.sub(r"^```(?:json)?|```$", "", value.strip(), flags=re.M).strip()
    if not text:
        return None
    object_match = re.search(r"\{.*\}", text, re.S)
    candidates = [text, object_match.group(0) if object_match else None]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            found = extract_numeric_score(json.loads(candidate))
        except (json.JSONDecodeError, TypeError):
            continue
        if found is not None:
            return found
    for pattern in (_OUT_OF_100, _LABELLED):
        match = pattern.search(text)
        if match and 0 <= float(match.group(1)) <= 100:
            return float(match.group(1))
    if re.fullmatch(r"\d{1,3}(?:\.\d+)?%?", text):
        number = float(text.rstrip("%"))
        return number if number <= 100 else None
    return None


def _build_llm_prompt(jd: dict[str, Any], resume: dict[str, Any]) -> str:
    """Build an evidence-only scoring prompt so the model returns a consistent JSON assessment."""
    return (
        "You are an ATS (applicant tracking system) evaluator. Compare the resume JSON with the job "
        "description JSON and rate the overall fit from 0 to 100.\n"
        "Rules:\n"
        "- Use ONLY information present in the JSON. Never invent skills, experience, education or achievements.\n"
        "- Judge like a recruiter: credit skills clearly demonstrated in projects or experience even when the exact "
        "keyword differs (for example Git/GitHub for version control), but give no credit for anything unsupported.\n"
        "- Weigh: skill/keyword coverage 35%, relevance of projects/experience 20%, job-title/role fit 10%, "
        "experience 15%, education 15%, achievements/certificates 5%.\n"
        "- If the JD does not ask for a factor (for example no experience or certificates), ignore it and spread its "
        "weight over the others. Do not penalise the candidate for it.\n"
        "- Do not penalise freshers or students for having no work experience or job titles unless the JD requires them.\n"
        "- Scale: 90-100 excellent, 75-89 strong, 60-74 good, 40-59 partial, 20-39 weak, 0-19 unrelated.\n"
        'Return ONLY JSON in this form: {"score": <number 0-100>, "reason": "<1-2 sentences citing evidence from the JSON>"}\n\n'
        f"JD JSON: {json.dumps(jd, ensure_ascii=False)}\n"
        f"Resume JSON: {json.dumps(resume, ensure_ascii=False)}"
    )


def get_ollama_evaluation(
    jd_payload: Any,
    resume_payload: Any,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Request and parse one independent Gemini assessment."""
    global _gemini_blocked_reason
    jd, resume = _as_dict(jd_payload), _as_dict(resume_payload)
    if _gemini_blocked_reason is not None:
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY is not configured")
        return None

    try:
        timeout_value = (
            timeout
            if timeout is not None
            else float(os.environ.get("GEMINI_TIMEOUT", "120"))
        )
        client = _get_gemini_client(api_key)
        total_wait = 0.0
        raw = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=model
                    or os.environ.get("GEMINI_MODEL", "models/gemini-3.1-flash-lite"),
                    contents=_build_llm_prompt(jd, resume),
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        http_options=types.HttpOptions(
                            timeout=int(timeout_value * 1000),
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    ),
                )
                raw = response.text
                break
            except errors.APIError as exc:
                error_payload, quota_ids, server_delay = _error_details(exc)
                category, permanent = _failure_category(exc.code, error_payload, quota_ids)
                if permanent:
                    _block_gemini(category, exc.code, quota_ids)
                    return None
                if exc.code not in _RETRYABLE_STATUS_CODES:
                    log.warning(
                        "Gemini request failed: status=%s reason=%s",
                        exc.code,
                        category,
                    )
                    return None
                if attempt >= _MAX_RETRIES:
                    _block_gemini(category, exc.code, quota_ids)
                    return None

                delay = _retry_wait_seconds(attempt + 1, server_delay)
                if (
                    delay > _MAX_RETRY_WAIT_SECONDS
                    or total_wait + delay > _MAX_RETRY_WAIT_SECONDS
                ):
                    _block_gemini(
                        f"{category}; retry delay exceeds the configured wait limit",
                        exc.code,
                        quota_ids,
                    )
                    return None
                total_wait += delay
                log.warning(
                    "Gemini transient failure: status=%s reason=%s; "
                    "retry %s/%s in %.2f seconds%s",
                    exc.code,
                    category,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    f" quota_ids={','.join(quota_ids)}" if quota_ids else "",
                )
                time.sleep(delay)
            except Exception as exc:
                _gemini_blocked_reason = f"unexpected {type(exc).__name__}"
                log.error(
                    "Gemini request failed: reason=%s; further requests are "
                    "suppressed for this pipeline run",
                    _gemini_blocked_reason,
                )
                return None
    except (TypeError, ValueError) as exc:
        _gemini_blocked_reason = f"invalid Gemini configuration ({type(exc).__name__})"
        log.error(
            "Gemini request failed: reason=%s; further requests are suppressed "
            "for this pipeline run",
            _gemini_blocked_reason,
        )
        return None

    if not isinstance(raw, str) or not raw.strip():
        log.warning("Gemini returned an empty or non-text response")
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("Gemini returned malformed JSON")
        return None

    if not isinstance(parsed, dict):
        log.warning("Gemini returned JSON that was not an object")
        return None

    score = extract_numeric_score(parsed)
    if score is None:
        log.warning("Could not read a valid score from Gemini response")
        return None
    reason = ""
    if isinstance(parsed, dict):
        reason = str(parsed.get("reason") or "")
    return {"score": round(score, 2), "reason": reason}


def get_ollama_score(
    jd_payload: Any, resume_payload: Any, model: Optional[str] = None
) -> Optional[float]:
    """Return only the Gemini score for callers that do not need its reason."""
    result = get_ollama_evaluation(jd_payload, resume_payload, model)
    return result["score"] if result else None
