"""Core-skill classification and constrained Question Bank selection."""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from typing import Any, Iterable

CORE_SUBJECT_ALIASES = {
    "object-oriented programming (oop)": "Object-Oriented Programming (OOP)",
    "object-oriented programming": "Object-Oriented Programming (OOP)",
    "oop": "Object-Oriented Programming (OOP)",
    "data structures": "Data Structures",
    "dsa": "Data Structures",
    "algorithms": "Algorithms",
    "dbms": "Database Management Systems (DBMS)",
    "database management systems": "Database Management Systems (DBMS)",
    "sql": "SQL",
    "computer networks": "Computer Networks",
    "networking": "Computer Networks",
    "operating systems": "Operating Systems",
    "os": "Operating Systems",
    "software engineering": "Software Engineering",
    "sdlc": "Software Development Life Cycle (SDLC)",
    "software development life cycle": "Software Development Life Cycle (SDLC)",
    "system design": "System Design Fundamentals",
    "system design fundamentals": "System Design Fundamentals",
    "computer architecture": "Computer Architecture",
    "programming fundamentals": "Programming Fundamentals",
    "version control": "Git / Version Control",
    "git": "Git / Version Control",
    "unit testing": "Software Testing Fundamentals",
    "software testing": "Software Testing Fundamentals",
    "testing": "Software Testing Fundamentals",
}

CHANGING_TECH_TERMS = {
    "spring boot", "spring security", "react", "react.js", "angular", "node.js", "node",
    "kafka", "aws", "azure", "docker", "kubernetes", "machine learning", "deep learning",
    "artificial intelligence", "ai", "tensorflow", "pytorch", "nlp", "rest api", "restful api",
    "html5", "css3", "mobile application development", "back-end", "ci/cd",
}

@dataclass(frozen=True)
class SelectedQuestion:
    question_id: int
    subject: str
    topic: str
    question: str
    answer: str
    expected_concepts: str
    difficulty: str


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./ -]", " ", str(value).lower())).strip()


def load_project_vocabulary(connection) -> dict[str, str]:
    """Read project-controlled canonical names and aliases without replacing them."""
    vocabulary: dict[str, str] = {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT canonical_name, aliases FROM technology_dictionary")
        for canonical, aliases in cursor.fetchall():
            vocabulary[_norm(canonical)] = canonical
            for alias in aliases or []:
                vocabulary[_norm(alias)] = canonical
        cursor.execute("SELECT alias_name, tech_id FROM technology_alias")
        cursor.execute("""SELECT a.alias_name, d.canonical_name
                        FROM technology_alias a JOIN technology_dictionary d ON d.tech_id = a.tech_id""")
        for alias, canonical in cursor.fetchall():
            vocabulary[_norm(alias)] = canonical
    return vocabulary


def classify_skills(expected_skills: Iterable[str], project_vocabulary: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    """Classify JD skills by stable core subject, leaving changing technologies for the LLM."""
    vocabulary = project_vocabulary or {}
    core: list[str] = []
    changing: list[str] = []
    for raw_skill in expected_skills:
        normalized = _norm(raw_skill)
        canonical = vocabulary.get(normalized, raw_skill)
        lookup = _norm(canonical)
        core_subject = CORE_SUBJECT_ALIASES.get(lookup)
        if core_subject and core_subject not in core:
            core.append(core_subject)
        elif lookup in CHANGING_TECH_TERMS or any(term in lookup for term in CHANGING_TECH_TERMS):
            if canonical not in changing:
                changing.append(canonical)
    return core, changing


def _query_for_subjects(connection, subjects: list[str], difficulty: str, limit: int) -> list[tuple]:
    if not subjects:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT question_id, subject, topic, question, answer, expected_concepts, difficulty
               FROM bankresume WHERE subject = ANY(%s) AND difficulty = %s
               ORDER BY random() LIMIT %s""",
            (subjects, difficulty, limit),
        )
        return cursor.fetchall()


def select_stage1_questions(connection, core_subjects: list[str], rng: random.Random | None = None) -> list[SelectedQuestion]:
    """Return exactly 3 Easy, 2 Medium, and 1 Hard reusable bank questions."""
    rng = rng or random.SystemRandom()
    chosen: list[tuple] = []
    for difficulty, count in (("Easy", 3), ("Medium", 2), ("Hard", 1)):
        rows = _query_for_subjects(connection, core_subjects, difficulty, max(count * 4, count))
        if len(rows) < count:
            raise ValueError(f"Question Bank has only {len(rows)} {difficulty} questions for core subjects {core_subjects}")
        chosen.extend(rng.sample(rows, count))
    rng.shuffle(chosen)
    return [SelectedQuestion(*row) for row in chosen]


def validate_stage1_questions(questions: list[SelectedQuestion]) -> list[str]:
    errors: list[str] = []
    if len(questions) != 6:
        errors.append(f"expected 6 questions, received {len(questions)}")
    ids = [item.question_id for item in questions]
    if len(ids) != len(set(ids)):
        errors.append("duplicate Question Bank IDs")
    counts = {difficulty: sum(item.difficulty == difficulty for item in questions) for difficulty in ("Easy", "Medium", "Hard")}
    if counts != {"Easy": 3, "Medium": 2, "Hard": 1}:
        errors.append(f"invalid difficulty distribution: {counts}")
    for item in questions:
        if not all(str(value).strip() for value in (item.question_id, item.question, item.answer, item.expected_concepts)):
            errors.append(f"empty field for question {item.question_id}")
    return errors


def normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./ -]", " ", text.lower())).strip()


def question_hash(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode()).hexdigest()


def average_score(scores: Iterable[float]) -> float:
    values = [float(score) for score in scores]
    if not values or any(score < 0 or score > 100 for score in values):
        raise ValueError("scores must contain at least one value between 0 and 100")
    return sum(values) / len(values)


def determine_stage2_difficulty(score: float) -> dict[str, int]:
    score = float(score)
    if not 0 <= score <= 100:
        raise ValueError("average score must be between 0 and 100")
    if score >= 81:
        return {"Hard": 4}
    if score >= 60:
        return {"Hard": 2, "Easy": 2}
    return {"Easy": 4}


def serialize_jd_context(jd: dict[str, Any]) -> str:
    return json.dumps(jd, ensure_ascii=False, sort_keys=True)
