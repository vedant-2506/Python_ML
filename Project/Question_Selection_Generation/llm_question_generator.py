"""Groq-backed Stage 2 generation and untrusted response validation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .adaptive_policy import determine_stage2_difficulty
from .config import GROQ_MODEL, LLM_PROVIDER
from .groq_client import GroqError, generate_json, verify_model
from .prompts.adaptive_question_prompt import build_adaptive_prompt
from .question_selector import normalize_question

SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
ALLOWED_DIFFICULTIES = {"Easy", "Medium", "Hard"}


@dataclass(frozen=True)
class GeneratedQuestion:
    skill: str
    difficulty: str
    question: str
    reference_answer: str
    expected_concepts: list[str]


def sentence_count(text: str) -> int:
    return len([part for part in SENTENCE_PATTERN.split(text.strip()) if part.strip()])


def _similar(left: str, right: str) -> bool:
    return SequenceMatcher(None, normalize_question(left), normalize_question(right)).ratio() >= 0.88


def _decode_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        result = json.loads(str(payload))
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response is not valid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("LLM JSON root must be an object")
    return result


def validate_generated_questions(
    payload: Any,
    changeable_skills: list[str],
    difficulty_distribution: dict[str, int],
    existing_questions: list[str],
) -> list[GeneratedQuestion]:
    rows = _decode_payload(payload).get("questions")
    if not isinstance(rows, list) or len(rows) != 4:
        raise ValueError("LLM response must contain exactly four questions")
    allowed = {skill.casefold(): skill for skill in changeable_skills}
    result: list[GeneratedQuestion] = []
    all_prior = [question for question in existing_questions if str(question).strip()]
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each generated question must be an object")
        skill = str(row.get("skill", "")).strip()
        difficulty = str(row.get("difficulty", "")).strip().title()
        question = str(row.get("question", "")).strip()
        answer = str(row.get("answer", row.get("reference_answer", ""))).strip()
        concepts = row.get("expected_concepts")
        if skill.casefold() not in allowed:
            raise ValueError(f"generated skill {skill!r} is not a permitted Changeable Skill")
        if difficulty not in ALLOWED_DIFFICULTIES or not question or not answer:
            raise ValueError("generated question has missing text or invalid difficulty")
        if not isinstance(concepts, list) or not 1 <= len(concepts) <= 8:
            raise ValueError("expected_concepts must be a non-empty list with at most eight items")
        if not all(str(item).strip() for item in concepts):
            raise ValueError("expected_concepts cannot contain empty values")
        count = sentence_count(answer)
        if count not in {5, 6}:
            raise ValueError(f"reference answer must contain 5-6 sentences, found {count}")
        if any(_similar(question, previous) for previous in [*all_prior, *(item.question for item in result)]):
            raise ValueError("generated question duplicates or paraphrases an existing question")
        result.append(GeneratedQuestion(allowed[skill.casefold()], difficulty, question, answer, [str(item).strip() for item in concepts]))

    actual = {difficulty: sum(item.difficulty == difficulty for item in result) for difficulty in ALLOWED_DIFFICULTIES}
    expected = {difficulty: difficulty_distribution.get(difficulty, 0) for difficulty in ALLOWED_DIFFICULTIES}
    if actual != expected:
        raise ValueError(f"invalid difficulty distribution: {actual}; expected {expected}")
    return result


def generate_stage2_questions(
    jd: dict[str, Any],
    changeable_skills: list[str],
    percentage: float | None,
    existing_questions: list[str],
    retries: int = 2,
    difficulty_distribution: dict[str, int] | None = None,
) -> list[GeneratedQuestion]:
    if LLM_PROVIDER != "groq":
        raise GroqError(f"unsupported LLM_PROVIDER={LLM_PROVIDER!r}; Stage 2 requires groq")
    if not changeable_skills:
        raise ValueError("JD has no usable Changeable Skills; adaptive Stage 2 cannot generate unrelated questions")
    if difficulty_distribution is not None:
        distribution = difficulty_distribution
    elif percentage is not None:
        distribution = determine_stage2_difficulty(percentage)
    else:
        distribution = {"Easy": 2, "Medium": 2, "Hard": 0}
    verify_model(GROQ_MODEL)
    prompt = build_adaptive_prompt(jd, changeable_skills, percentage, distribution, existing_questions)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return validate_generated_questions(
                generate_json(prompt, GROQ_MODEL), changeable_skills, distribution, existing_questions
            )
        except GroqError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            last_error = exc
            if attempt < retries:
                prompt += "\nCorrection required: return a complete response satisfying every validation rule."
    raise ValueError(f"Groq did not produce a valid batch after {retries + 1} attempts: {last_error}")
