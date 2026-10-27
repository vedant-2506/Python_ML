"""LLM-backed ATS evaluation using the Gemini API."""

from __future__ import annotations

import atexit
import email.utils
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Optional

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
# Free-tier 429s commonly ask for 30-60s; wait those out instead of giving up.
_MAX_RETRY_WAIT_SECONDS = 90.0
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_DEFAULT_MODEL = "models/gemini-3.1-flash-lite"

# Circuit breaker state. Only PERMANENT errors (or many consecutive transient
# failures) open it; a single failed candidate no longer kills the whole run.
_gemini_blocked_reason: Optional[str] = None
_consecutive_failures = 0

# Throttle state
_throttle_lock = threading.Lock()
_last_call = 0.0


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _throttle() -> None:
    """Space requests out so we stay under GEMINI_RPM requests per minute."""
    global _last_call
    min_interval = 60.0 / _env_int("GEMINI_RPM", 10)
    with _throttle_lock:
        wait = min_interval - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


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
    global _gemini_blocked_reason, _consecutive_failures
    _gemini_blocked_reason = None
    _consecutive_failures = 0


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
    code: int,
    error_payload: dict[str, Any],
    quota_ids: list[str],
) -> tuple[str, bool]:
    """Return (category, permanent). Permanent failures open the circuit breaker."""
    status = str(error_payload.get("status") or "").upper()
    message = str(error_payload.get("message") or "").lower()
    quota_text = " ".join(quota_ids).lower()

    # Handle rate limits BEFORE checking billing errors.
    if code == 429:
        if any(token in quota_text for token in ("perday", "per_day", "daily")):
            return "daily quota exhausted", True
        if any(token in quota_text for token in ("perminute", "per_minute")):
            return "per-minute rate limit", False
        return "rate limit", False

    if any(
        token in f"{status} {message}"
        for token in ("billing", "payment", "billingdisabled")
    ):
        return "billing/project restriction", True

    if code in {400, 401, 403}:
        if code == 401 or "api key" in message:
            return "invalid or unauthorized API key", True
        return "permanent API/project request error", True

    if code == 404:
        return "invalid or unavailable model", True

    if code == 503:
        return "temporary service unavailable", False

    return f"HTTP {code} API error", code not in _RETRYABLE_STATUS_CODES


def _retry_wait_seconds(attempt: int, server_delay: Optional[float]) -> float:
    exponential = min(0.5 * (2 ** (attempt - 1)), 8.0)
    if server_delay is not None:
        return max(exponential, server_delay) + random.uniform(0.0, 0.25)
    return random.uniform(exponential * 0.75, exponential * 1.25)


def _block_gemini(reason: str, code: int, quota_ids: list[str]) -> None:
    """Open the circuit breaker. Use only for permanent / run-wide failures."""
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


def _record_transient_failure(reason: str, code: int, quota_ids: list[str]) -> None:
    """Skip the current call; only open the breaker after repeated failures in a row."""
    global _consecutive_failures
    _consecutive_failures += 1
    limit = _env_int("GEMINI_MAX_CONSECUTIVE_FAILURES", 5)
    log.warning(
        "Gemini transient failure (%s/%s in a row): status=%s reason=%s; "
        "skipping this request",
        _consecutive_failures,
        limit,
        code,
        reason,
    )
    if _consecutive_failures >= limit:
        _block_gemini(f"{reason}; {_consecutive_failures} consecutive failures", code, quota_ids)


def _generate(
    client: genai.Client,
    prompt: str,
    model: str,
    timeout_ms: int,
) -> Optional[str]:
    """Send one prompt with throttling and retries. Returns raw text or None."""
    global _consecutive_failures

    if _gemini_blocked_reason is not None:
        return None

    total_wait = 0.0
    for attempt in range(_MAX_RETRIES + 1):
        _throttle()
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                    http_options=types.HttpOptions(
                        timeout=timeout_ms,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ),
            )
            _consecutive_failures = 0
            return response.text

        except errors.APIError as exc:
            error_payload, quota_ids, server_delay = _error_details(exc)
            category, permanent = _failure_category(exc.code, error_payload, quota_ids)

            if permanent:
                _block_gemini(category, exc.code, quota_ids)
                return None

            if exc.code not in _RETRYABLE_STATUS_CODES:
                log.warning("Gemini request failed: status=%s reason=%s", exc.code, category)
                return None

            if attempt >= _MAX_RETRIES:
                _record_transient_failure(f"{category}; retries exhausted", exc.code, quota_ids)
                return None

            delay = _retry_wait_seconds(attempt + 1, server_delay)
            if (
                delay > _MAX_RETRY_WAIT_SECONDS
                or total_wait + delay > _MAX_RETRY_WAIT_SECONDS
            ):
                _record_transient_failure(
                    f"{category}; retry delay {delay:.0f}s exceeds wait limit",
                    exc.code,
                    quota_ids,
                )
                return None

            total_wait += delay
            log.warning(
                "Gemini transient failure: status=%s reason=%s; retry %s/%s in %.2f seconds%s",
                exc.code,
                category,
                attempt + 1,
                _MAX_RETRIES,
                delay,
                f" quota_ids={','.join(quota_ids)}" if quota_ids else "",
            )
            time.sleep(delay)

        except Exception as exc:  # timeouts, connection resets, etc.
            log.exception("Unexpected Gemini request failure")
            _record_transient_failure(f"unexpected {type(exc).__name__}", 0, [])
            return None

    return None


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
        raw = _generate(
            client,
            _build_llm_prompt(jd, resume),
            model or os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL),
            int(timeout_value * 1000),
        )
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
    return {"score": round(score, 2), "reason": str(parsed.get("reason") or "")}


def get_ollama_score(
    jd_payload: Any, resume_payload: Any, model: Optional[str] = None
) -> Optional[float]:
    """Return only the Gemini score for callers that do not need its reason."""
    result = get_ollama_evaluation(jd_payload, resume_payload, model)
    return result["score"] if result else None


def get_batch_gemini_evaluations(
    jd_payload: Any,
    resumes: list[dict[str, Any]],
    model: Optional[str] = None,
    batch_size: int = 10,
    on_batch: Optional[Callable[[dict[str, Optional[dict[str, Any]]]], None]] = None,
) -> dict[str, Optional[dict[str, Any]]]:
    """Score resumes in batches, preserving valid results and retrying missing ones.

    ``on_batch`` (optional) is called after every batch with that batch's
    ``{candidate_id: {"score", "reason"} | None}`` mapping, so the caller can
    persist scores incrementally instead of only at the end of the run.
    """
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")

    candidate_ids = [str(item["candidate_id"]) for item in resumes]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("Duplicate candidate IDs")

    results: dict[str, Optional[dict[str, Any]]] = {cid: None for cid in candidate_ids}

    if not resumes or _gemini_blocked_reason is not None:
        return results

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.warning("GEMINI_API_KEY is missing")
        return results

    jd = _as_dict(jd_payload)
    client = _get_gemini_client(api_key)
    selected_model = model or os.getenv("GEMINI_MODEL", _DEFAULT_MODEL)
    timeout_ms = int(float(os.getenv("GEMINI_TIMEOUT", "120")) * 1000)

    rubric = _build_llm_prompt(jd, {}).split("Return ONLY JSON in this form:")[0]

    def request_batch(batch: list[dict[str, Any]]) -> Optional[str]:
        """Send one batch using the shared throttle/retry/breaker logic."""
        candidates = [
            {
                "candidate_id": str(item["candidate_id"]),
                "resume": _as_dict(item["structured_data"]),
            }
            for item in batch
        ]
        prompt = (
            rubric
            + "\nEvaluate each candidate independently using the six-factor rubric.\n"
            + "Return ONLY JSON in this format:\n"
            + '{"results":[{"candidate_id":"1","score":80,'
              '"reason":"Evidence-based explanation"}]}\n'
            + "Include exactly one result for each candidate ID provided.\n"
            + "Never invent qualifications or candidate IDs.\n"
            + "JD JSON: "
            + json.dumps(jd, ensure_ascii=False, separators=(",", ":"))
            + "\nCandidates JSON: "
            + json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
        )
        return _generate(client, prompt, selected_model, timeout_ms)

    def parse_batch(
        raw: Optional[str],
        expected: set[str],
    ) -> dict[str, dict[str, Any]]:
        """Keep valid results; reject duplicates and invalid scores."""
        if not isinstance(raw, str) or not raw.strip():
            return {}

        try:
            parsed = json.loads(raw)
            items = parsed["results"]
            if not isinstance(items, list):
                raise ValueError("results must be a list")
        except (ValueError, KeyError, TypeError):
            log.warning("Gemini returned invalid batch JSON")
            return {}

        validated: dict[str, dict[str, Any]] = {}
        duplicate_ids: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            cid = str(item.get("candidate_id", ""))
            if cid not in expected or cid in duplicate_ids:
                continue

            if cid in validated:
                validated.pop(cid, None)
                duplicate_ids.add(cid)
                continue

            score = extract_numeric_score(item.get("score"))
            if score is None:
                continue

            validated[cid] = {
                "score": round(score, 2),
                "reason": str(item.get("reason") or ""),
            }

        return validated

    for start in range(0, len(resumes), batch_size):
        if _gemini_blocked_reason is not None:
            break

        batch = resumes[start:start + batch_size]
        batch_ids = [str(item["candidate_id"]) for item in batch]
        expected = set(batch_ids)

        log.info("Gemini batch %s: scoring %s resumes", start // batch_size + 1, len(batch))

        raw = request_batch(batch)
        validated = parse_batch(raw, expected)
        results.update(validated)

        missing_ids = expected - set(validated)
        if missing_ids:
            log.warning("Gemini batch missing %s of %s scores", len(missing_ids), len(batch))

        # Retry missing candidates once as a smaller batch.
        if missing_ids and _gemini_blocked_reason is None and raw is not None:
            missing_batch = [
                item for item in batch if str(item["candidate_id"]) in missing_ids
            ]
            retry_raw = request_batch(missing_batch)
            results.update(parse_batch(retry_raw, missing_ids))

        successful = sum(results[cid] is not None for cid in batch_ids)
        log.info("Gemini batch completed: %s/%s valid scores", successful, len(batch))

        # Let the caller persist this batch immediately.
        if on_batch is not None:
            try:
                on_batch({cid: results[cid] for cid in batch_ids})
            except Exception:
                log.exception("on_batch callback failed; continuing with next batch")

    return results