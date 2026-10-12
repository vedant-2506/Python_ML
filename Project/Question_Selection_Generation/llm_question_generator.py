"""Ollama-backed adaptive Changing-Tech question generation and safe storage."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

try:
    from .config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL
    from .prompts.adaptive_question_prompt import build_adaptive_prompt
    from .question_selector import determine_stage2_difficulty, normalize_question, question_hash
except ImportError:
    from config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL
    from prompts.adaptive_question_prompt import build_adaptive_prompt
    from question_selector import determine_stage2_difficulty, normalize_question, question_hash

SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
ALLOWED_DIFFICULTIES = {"Easy", "Medium", "Hard"}

@dataclass(frozen=True)
class GeneratedQuestion:
    skill: str
    difficulty: str
    question: str
    reference_answer: str
    expected_concepts: list[str]


class OllamaUnavailableError(RuntimeError):
    """Raised when the configured Ollama server or model cannot be reached."""


def sentence_count(text: str) -> int:
    return len([part for part in SENTENCE_PATTERN.split(text.strip()) if part.strip()])


def check_ollama(model: str = OLLAMA_MODEL, timeout: float = 10) -> bool:
    request = urllib.request.Request(
        OLLAMA_URL.replace("/api/generate", "/api/tags"), method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return any(item.get("name") == model for item in payload.get("models", []))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _decode_json(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip().replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Ollama returned non-JSON output")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Ollama JSON root must be an object")
    return parsed


def call_ollama(prompt: str, model: str = OLLAMA_MODEL, timeout: float = OLLAMA_TIMEOUT) -> dict:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 900, "num_ctx": 3072},
    }
    request = urllib.request.Request(OLLAMA_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Ollama HTTP error for model {model}: {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaUnavailableError(
            f"Ollama is unavailable at {OLLAMA_URL}. Start it with `ollama serve`, "
            f"then retry. Details: {exc}"
        ) from exc
    if payload.get("model") and payload["model"] != model:
        raise RuntimeError(f"Ollama returned model {payload['model']!r}, expected {model!r}")
    return _decode_json(payload.get("response", payload))


def validate_generated_questions(
    payload: dict,
    changing_skills: list[str],
    difficulty_distribution: dict[str, int],
    used_questions: list[str],
) -> list[GeneratedQuestion]:
    rows = payload.get("questions")
    if not isinstance(rows, list) or len(rows) != sum(difficulty_distribution.values()):
        raise ValueError("LLM response must contain exactly the requested number of questions")
    allowed_skills = {skill.lower() for skill in changing_skills}
    used = {normalize_question(question) for question in used_questions}
    result: list[GeneratedQuestion] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each generated question must be an object")
        required = ("skill", "difficulty", "question", "reference_answer", "expected_concepts")
        if any(key not in row for key in required):
            raise ValueError(f"Generated question is missing one of {required}")
        skill = str(row["skill"]).strip()
        difficulty = str(row["difficulty"]).strip().title()
        question = str(row["question"]).strip()
        answer = str(row["reference_answer"]).strip()
        concepts = row["expected_concepts"]
        if skill.lower() not in allowed_skills:
            raise ValueError(f"Generated skill {skill!r} is not a Changing-Tech JD skill")
        if difficulty not in ALLOWED_DIFFICULTIES or not question or not answer:
            raise ValueError("Generated question has invalid difficulty or empty content")
        if not isinstance(concepts, list) or not 3 <= len(concepts) <= 6 or not all(str(item).strip() for item in concepts):
            raise ValueError("expected_concepts must contain 3-6 non-empty items")
        if not 5 <= sentence_count(answer) <= 6:
            raise ValueError(f"reference_answer must contain 5-6 sentences, got {sentence_count(answer)}")
        normalized = normalize_question(question)
        if normalized in used or any(question_hash(item.question) == question_hash(question) for item in result):
            raise ValueError("generated question duplicates an existing or same-batch question")
        used.add(normalized)
        result.append(GeneratedQuestion(skill, difficulty, question, answer, [str(item).strip() for item in concepts]))
    counts = {difficulty: sum(item.difficulty == difficulty for item in result) for difficulty in ALLOWED_DIFFICULTIES}
    expected = {difficulty: difficulty_distribution.get(difficulty, 0) for difficulty in ALLOWED_DIFFICULTIES}
    if counts != expected:
        raise ValueError(f"invalid generated difficulty distribution: {counts}, expected {expected}")
    return result


def generate_stage2_questions(
    jd: dict,
    changing_skills: list[str],
    average: float,
    used_questions: list[str],
    skill_performance: dict[str, float] | None = None,
    model: str = OLLAMA_MODEL,
    retries: int = 2,
) -> list[GeneratedQuestion]:
    if not check_ollama(model):
        raise OllamaUnavailableError(
            f"Cannot reach Ollama at {OLLAMA_URL} or model {model!r} is missing. "
            f"Start Ollama with `ollama serve` and, if needed, install the model "
            f"with `ollama pull {model}`, then rerun this cell."
        )

    distribution = determine_stage2_difficulty(average)
    prompt = build_adaptive_prompt(jd, changing_skills, average, distribution, used_questions, skill_performance)
    last_error: Exception | None = None
    for _ in range(retries + 1):
        try:
            return validate_generated_questions(call_ollama(prompt, model), changing_skills, distribution, used_questions)
        except OllamaUnavailableError:
            raise
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            last_error = exc
    raise RuntimeError(f"Could not generate valid adaptive questions after {retries + 1} attempts: {last_error}")


def ensure_stage2_idempotent(connection, exam_id: uuid.UUID) -> list[dict] | None:
    with connection.cursor() as cursor:
        cursor.execute("""SELECT question_order, skill, difficulty, question, reference_answer, expected_concepts
                         FROM question_exam WHERE exam_id = %s AND stage = 2 ORDER BY question_order""", (str(exam_id),))
        rows = cursor.fetchall()
    if len(rows) != 4:
        return None
    return [{"question_order": row[0], "skill": row[1], "difficulty": row[2], "question": row[3], "reference_answer": row[4], "expected_concepts": row[5]} for row in rows]


def store_stage2(connection, exam_id: uuid.UUID, jd_id: int, questions: list[GeneratedQuestion], model: str = OLLAMA_MODEL) -> list[int]:
    if len(questions) != 4:
        raise ValueError("Stage 2 must store exactly four questions")
    existing = ensure_stage2_idempotent(connection, exam_id)
    if existing is not None:
        return []
    generated_ids: list[int] = []
    with connection.cursor() as cursor:
        for offset, item in enumerate(questions, start=7):
            cursor.execute("""INSERT INTO generated_questions
                (exam_id, jd_id, skill, question, reference_answer, expected_concepts, difficulty, model_name, question_hash)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s) RETURNING generated_question_id""",
                (str(exam_id), jd_id, item.skill, item.question, item.reference_answer, json.dumps(item.expected_concepts), item.difficulty, model, question_hash(item.question)))
            generated_id = cursor.fetchone()[0]
            generated_ids.append(generated_id)
            cursor.execute("""INSERT INTO question_exam
                (exam_id, jd_id, question_order, stage, source, generated_question_id, question, reference_answer, expected_concepts, difficulty, skill)
                VALUES (%s,%s,%s,2,'LLM',%s,%s,%s,%s::jsonb,%s,%s)""",
                (str(exam_id), jd_id, offset, generated_id, item.question, item.reference_answer, json.dumps(item.expected_concepts), item.difficulty, item.skill))
    return generated_ids
