"""LLM-backed ATS evaluation using a locally served Ollama model."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from typing import Any, Optional

log = logging.getLogger(__name__)

_SCORE_KEYS = ("score", "ats_score", "final_score", "overall_score", "match_score", "fit_score")
_OUT_OF_100 = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:/|out of)\s*100", re.I)
_LABELLED = re.compile(r"(?:score|ats|overall|match|fit)\D{0,15}?(\d{1,3}(?:\.\d+)?)", re.I)


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
    """Request and parse one independent Ollama assessment, returning None if transport or parsing fails."""
    jd, resume = _as_dict(jd_payload), _as_dict(resume_payload)
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
    body = {
        "model": model or os.environ.get("OLLAMA_MODEL", "llama3.2:latest"),
        "prompt": _build_llm_prompt(jd, resume),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout_value = timeout if timeout is not None else float(os.environ.get("OLLAMA_TIMEOUT", "120"))
    try:
        try:
            with urllib.request.urlopen(request, timeout=timeout_value) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except TypeError:
            with urllib.request.urlopen(request) as response:
                payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        log.warning("Ollama request failed: %s", exc)
        return None

    raw = payload.get("response") if isinstance(payload, dict) else payload
    score = extract_numeric_score(raw)
    if score is None:
        log.warning("Could not read a score from Ollama response: %r", raw)
        return None
    reason = ""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict):
            reason = str(parsed.get("reason") or "")
    except (json.JSONDecodeError, TypeError):
        pass
    return {"score": round(score, 2), "reason": reason}


def get_ollama_score(
    jd_payload: Any, resume_payload: Any, model: Optional[str] = None
) -> Optional[float]:
    """Return only the Ollama score for callers that do not need its explanatory reason."""
    result = get_ollama_evaluation(jd_payload, resume_payload, model)
    return result["score"] if result else None
