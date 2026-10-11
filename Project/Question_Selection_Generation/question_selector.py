"""Skill classification and deterministic, validated Question Bank selection."""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from typing import Any, Iterable


def normalize_skill_name(value: Any) -> str:
    """Return a comparison key without collapsing distinct language names."""
    text = str(value or "").strip().casefold()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"\s*-\s*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


CORE_SKILL_ALIASES = {
    "oop": "Object-Oriented Programming (OOP)",
    "object oriented programming": "Object-Oriented Programming (OOP)",
    "object oriented programming oop": "Object-Oriented Programming (OOP)",
    "data structures": "Data Structures",
    "dsa": "Data Structures",
    "algorithms": "Algorithms",
    "dbms": "Database Management Systems (DBMS)",
    "database management systems": "Database Management Systems (DBMS)",
    "sql": "SQL",
    "sql queries": "SQL",
    "operating systems": "Operating Systems",
    "os": "Operating Systems",
    "computer networks": "Computer Networks",
    "networking": "Computer Networks",
    "computer architecture": "Computer Architecture",
    "software engineering": "Software Engineering",
    "sdlc": "Software Development Life Cycle (SDLC)",
    "software development life cycle": "Software Development Life Cycle (SDLC)",
    "system design": "System Design Fundamentals",
    "system design fundamentals": "System Design Fundamentals",
    "programming fundamentals": "Programming Fundamentals",
    "c": "C",
    "c plus plus": "C++",
    "c++": "C++",
    "c sharp": "C#",
    "c#": "C#",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "git": "Git / Version Control",
    "git version control": "Git / Version Control",
    "version control": "Git / Version Control",
    "testing fundamentals": "Software Testing Fundamentals",
    "software testing": "Software Testing Fundamentals",
    "unit testing": "Software Testing Fundamentals",
    "testing": "Software Testing Fundamentals",
}

CHANGEABLE_SKILL_ALIASES = {
    "spring boot": "Spring Boot",
    "spring security": "Spring Security",
    "react": "React",
    "react js": "React",
    "angular": "Angular",
    "node js": "Node.js",
    "node": "Node.js",
    "django": "Django",
    "flask": "Flask",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "aws": "AWS",
    "azure": "Azure",
    "terraform": "Terraform",
    "kafka": "Kafka",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "mongodb": "MongoDB",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "machine learning": "Machine Learning",
    "deep learning": "Deep Learning",
    "artificial intelligence": "Artificial Intelligence",
    "ai": "Artificial Intelligence",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "nlp": "NLP",
    "rest api": "REST API",
    "restful api": "REST API",
    "html5": "HTML5",
    "css3": "CSS3",
    "ci cd": "CI/CD",
}

BANK_SUBJECT_ALIASES = {
    "Object-Oriented Programming (OOP)": {"object oriented programming", "oop"},
    "Software Development Life Cycle (SDLC)": {"software engineering", "sdlc"},
    "Software Testing Fundamentals": {"software testing fundamentals", "software testing"},
    "Git / Version Control": {"git version control", "version control", "git"},
    "Database Management Systems (DBMS)": {"database management systems dbms", "dbms"},
    "System Design Fundamentals": {"system design fundamentals", "system design"},
}


@dataclass(frozen=True)
class SkillClassification:
    core_skills: list[str]
    changeable_skills: list[str]
    unclassified_skills: list[str]

    def __iter__(self):
        """Keep the old ``core, changing = classify_skills(...)`` API working."""
        yield self.core_skills
        yield self.changeable_skills


@dataclass(frozen=True)
class SelectedQuestion:
    question_id: int
    subject: str
    topic: str
    question: str
    answer: str
    expected_concepts: str
    difficulty: str


def _flatten_skills(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        for key in ("name", "skill", "value", "title", "canonical_name"):
            if key in value:
                return _flatten_skills(value[key])
        return [item for child in value.values() for item in _flatten_skills(child)]
    if isinstance(value, (list, tuple, set)):
        return [item for child in value for item in _flatten_skills(child)]
    return [str(value)]


def load_project_vocabulary(connection) -> dict[str, str]:
    """Load optional project aliases; explicit policy aliases always remain authoritative."""
    vocabulary: dict[str, str] = {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT canonical_name, aliases FROM technology_dictionary"
        )
        for canonical, aliases in cursor.fetchall():
            vocabulary[normalize_skill_name(canonical)] = canonical
            if isinstance(aliases, dict):
                aliases = aliases.get("aliases", [])
            for alias in aliases or []:
                vocabulary[normalize_skill_name(alias)] = canonical
        cursor.execute(
            """SELECT a.alias_name, d.canonical_name
               FROM technology_alias a
               JOIN technology_dictionary d ON d.tech_id = a.tech_id"""
        )
        for alias, canonical in cursor.fetchall():
            vocabulary[normalize_skill_name(alias)] = canonical
    return vocabulary


def classify_skills(
    expected_skills: Any,
    project_vocabulary: dict[str, str] | None = None,
) -> SkillClassification:
    """Classify every supplied skill, retaining unknown values for review."""
    vocabulary = project_vocabulary or {}
    core: list[str] = []
    changeable: list[str] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    for raw_skill in _flatten_skills(expected_skills):
        display = re.sub(r"\s+", " ", str(raw_skill).strip())
        key = normalize_skill_name(display)
        if not key or key in seen:
            continue
        seen.add(key)
        policy_key = key
        canonical_from_project = vocabulary.get(key)
        if canonical_from_project and key not in CORE_SKILL_ALIASES and key not in CHANGEABLE_SKILL_ALIASES:
            policy_key = normalize_skill_name(canonical_from_project)
        if policy_key in CORE_SKILL_ALIASES:
            value = CORE_SKILL_ALIASES[policy_key]
            if value not in core:
                core.append(value)
        elif policy_key in CHANGEABLE_SKILL_ALIASES:
            value = CHANGEABLE_SKILL_ALIASES[policy_key]
            if value not in changeable:
                changeable.append(value)
        else:
            unresolved.append(display)
    return SkillClassification(core, changeable, unresolved)


def normalize_difficulty(value: Any) -> str:
    key = str(value or "").strip().casefold()
    values = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}
    if key not in values:
        raise ValueError(f"Unsupported difficulty label: {value!r}")
    return values[key]


def _bank_names(core_subjects: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for subject in core_subjects:
        key = normalize_skill_name(subject)
        names.add(key)
        names.update(BANK_SUBJECT_ALIASES.get(subject, set()))
    return names


def _query_for_subjects(connection, subjects: list[str], difficulty: str) -> list[tuple]:
    names = sorted(_bank_names(subjects))
    if not names:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT question_id, subject, topic, question, answer,
                      expected_concepts, difficulty
               FROM bankresume
               WHERE LOWER(TRIM(difficulty)) = %s
                 AND (LOWER(TRIM(subject)) = ANY(%s)
                      OR LOWER(TRIM(topic)) = ANY(%s))
               ORDER BY question_id""",
            (normalize_difficulty(difficulty).casefold(), names, names),
        )
        return cursor.fetchall()


def normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#./ -]", " ", text.casefold())).strip()


def question_hash(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode()).hexdigest()


def select_stage1_questions(
    connection,
    core_subjects: list[str],
    rng: random.Random | None = None,
) -> list[SelectedQuestion]:
    """Select six unique bank rows with the required distribution or fail clearly."""
    rng = rng or random.SystemRandom()
    chosen: list[tuple] = []
    used_ids: set[int] = set()
    used_hashes: set[str] = set()
    shortages: dict[str, int] = {}
    for difficulty, count in (("Easy", 3), ("Medium", 2), ("Hard", 1)):
        candidates = []
        for row in _query_for_subjects(connection, core_subjects, difficulty):
            normalized = normalize_question(row[3])
            if row[0] not in used_ids and normalized and normalized not in used_hashes:
                candidates.append(row)
        if len(candidates) < count:
            shortages[difficulty] = count - len(candidates)
            continue
        selected = rng.sample(candidates, count)
        chosen.extend(selected)
        used_ids.update(row[0] for row in selected)
        used_hashes.update(normalize_question(row[3]) for row in selected)
    if shortages:
        details = ", ".join(f"{key}: {value} missing" for key, value in shortages.items())
        raise ValueError(f"Question Bank cannot satisfy 3 Easy, 2 Medium, 1 Hard ({details})")
    rng.shuffle(chosen)
    questions = [
        SelectedQuestion(row[0], row[1], row[2], row[3], row[4], row[5], normalize_difficulty(row[6]))
        for row in chosen
    ]
    errors = validate_stage1_questions(questions)
    if errors:
        raise ValueError("Stage 1 validation failed: " + "; ".join(errors))
    return questions


def validate_stage1_questions(questions: list[SelectedQuestion]) -> list[str]:
    errors: list[str] = []
    if len(questions) != 6:
        errors.append(f"expected 6 questions, received {len(questions)}")
    if len({item.question_id for item in questions}) != len(questions):
        errors.append("duplicate Question Bank IDs")
    fingerprints = [normalize_question(item.question) for item in questions]
    if len(set(fingerprints)) != len(fingerprints):
        errors.append("duplicate question text")
    counts = {difficulty: sum(item.difficulty == difficulty for item in questions) for difficulty in ("Easy", "Medium", "Hard")}
    if counts != {"Easy": 3, "Medium": 2, "Hard": 1}:
        errors.append(f"invalid difficulty distribution: {counts}")
    for item in questions:
        if (
            not str(item.question_id).strip()
            or not item.question.strip()
            or not item.answer.strip()
            or not item.expected_concepts.strip()
        ):
            errors.append(f"empty field for question {item.question_id}")
    return errors


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
