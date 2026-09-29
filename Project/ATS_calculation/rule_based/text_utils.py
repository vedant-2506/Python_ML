"""Text and payload normalization helpers shared by rule-based ATS factors."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Optional

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in is it of on or that the to with we you your
    our will can should must may using use used knowledge understanding ability strong good excellent
    experience experienced working work years year required requirements preferred plus etc including
    such other any all s""".split()
)

_PRE = (
    ("c++", " cpp "), ("c#", " csharp "), (".net", " dotnet "), ("node.js", " nodejs "),
    ("react.js", " react "), ("vue.js", " vue "), ("next.js", " nextjs "), ("express.js", " express "),
)

ALIASES = {
    "js": "javascript", "ts": "typescript", "py": "python", "reactjs": "react", "react js": "react",
    "node js": "nodejs", "node": "nodejs", "ml": "machine learning", "ai": "artificial intelligence",
    "nlp": "natural language processing", "k8s": "kubernetes", "postgres": "postgresql",
    "mongo": "mongodb", "sklearn": "scikit learn", "golang": "go", "restful": "rest",
    "ci cd": "cicd", "oops": "object oriented programming", "oop": "object oriented programming",
}
_ALIAS_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(key) for key in ALIASES), key=len, reverse=True)) + r")\b"
)

# Keyword (canonical form) -> resume terms that demonstrate it even if the exact word is absent.
# Implied matches are worth 0.7 of a direct match.
IMPLIED_BY = {
    "version control": ["git", "github", "gitlab", "bitbucket", "svn"],
    "back end": ["spring boot", "spring", "servlet", "jdbc", "django", "flask", "express", "nodejs", "backend", "rest api"],
    "html5": ["html"],
    "css3": ["css"],
    "object oriented programming": ["oop", "object oriented", "inheritance", "polymorphism", "encapsulation"],
    "unit testing": ["junit", "pytest", "unittest", "testng", "mockito", "jest", "mocha"],
    "debugging": ["debug", "debugging", "bug", "troubleshoot"],
    "bug fixing": ["bug", "debugging", "troubleshoot"],
    "data structures": ["data structure", "stl", "linked list", "hashmap", "hash map"],
    "algorithms": ["algorithm", "root finding", "sorting", "searching", "numerical"],
    "mobile application development": ["android", "ios", "flutter", "react native", "kotlin", "swift"],
    "collaboration": ["collaboration", "collaborating", "collaborated", "teamwork", "team"],
    "agile": ["agile", "jira", "kanban", "sprint"],
    "scrum": ["scrum", "sprint"],
    "code review": ["pull request", "code review", "reviewed code"],
    "problem solving": ["problem solving", "algorithm", "debug", "troubleshoot", "resolving"],
    "communication": ["communication", "presented", "documented", "documentation"],
}


def _normalize_text(value: Any) -> str:
    """Standardize text so punctuation, casing, and technology spellings compare consistently."""
    if value is None:
        return ""
    text = str(value).strip()
    for old, new in _PRE:
        text = text.replace(old, new)
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _canon(value: Any) -> str:
    """Apply skill aliases after normalization so equivalent terms use one canonical form."""
    return _ALIAS_RE.sub(lambda match: ALIASES[match.group(1)], _normalize_text(value))


def _stem(token: str) -> str:
    """Trim common suffixes so inflected words count as the same matching token."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _tokens(value: Any, stem: bool = False) -> list[str]:
    """Split normalized text into useful terms for keyword and similarity scoring."""
    return _tokens_from_canonical(_canon(value), stem=stem)


def _tokens_from_canonical(value: Any, stem: bool = False) -> list[str]:
    """Tokenize text that has already been normalized and alias-canonicalized."""
    if value is None:
        return []
    tokens = [token for token in str(value).split() if token not in _STOPWORDS]
    return [_stem(token) for token in tokens] if stem else tokens


def _flatten(value: Any) -> list[str]:
    """Collect nested record values as strings so structured resume fields can be searched."""
    if value is None:
        return []
    if isinstance(value, dict):
        flattened: list[str] = []
        for item in value.values():
            flattened.extend(_flatten(item))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened = []
        for item in value:
            flattened.extend(_flatten(item))
        return flattened
    return [str(value)]


def _items(value: Any, split: bool = True) -> list[str]:
    """Normalize strings and structured values into items for consistent factor matching."""
    if value is None:
        return []
    if isinstance(value, str):
        if not split:
            return [value.strip()] if value.strip() else []
        return [part.strip() for part in re.split(r"[,;|\n\u2022]+", value) if part.strip()]
    if isinstance(value, dict):
        name = value.get("name") or value.get("skill") or value.get("title")
        return [str(name)] if name else [" ".join(_flatten(value))]
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_items(item, split))
        return items
    return [str(value)]


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Extract a numeric value from mixed input so score calculations tolerate text fields."""
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
        return float(match.group()) if match else default


def _clamp(value: float) -> float:
    """Keep scores inside the ATS 0-100 range before blending or returning them."""
    return max(0.0, min(100.0, value))


def _as_dict(value: Any) -> dict[str, Any]:
    """Convert dict or JSON input to a safe mapping so scorers handle database payloads."""
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _resume_text(resume: dict[str, Any]) -> str:
    """Flatten and canonicalize a resume so keyword checks can search all its evidence."""
    return f" {_canon(' '.join(_flatten(resume)))} "


def _project_text(resume: dict[str, Any]) -> str:
    """Select project titles and descriptions so similarity measures project relevance."""
    projects = resume.get("projects") or resume.get("project") or []
    parts: list[str] = []
    records = projects if isinstance(projects, list) else [projects]
    for project in records:
        if isinstance(project, dict):
            parts.extend((
                str(project.get("project_title") or project.get("title") or ""),
                str(project.get("description") or ""),
            ))
    return " ".join(part for part in parts if part.strip())


_RANGE_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)")
_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)")
_MONTHS = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:months?|mos?)\b")
_DATE_RANGE = re.compile(
    r"(?:[a-z]{3,9}\.?\s+)?((?:19|20)\d{2})\s*(?:-|\u2013|\u2014|to)\s*"
    r"(?:[a-z]{3,9}\.?\s+)?((?:19|20)\d{2}|present|current|now|till date)"
)


def _parse_years(value: Any) -> Optional[float]:
    """Parse numeric, duration, or date-range input into years for experience comparison."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("years", "experience_years", "duration_years", "total_years", "duration"):
            if key in value:
                parsed = _parse_years(value[key])
                if parsed is not None:
                    return parsed
        if "months" in value:
            months = _coerce_float(value["months"], 0.0)
            return months / 12 if months else None
        return None
    if isinstance(value, (list, tuple, set)):
        parts = [part for part in (_parse_years(item) for item in value) if part is not None]
        return sum(parts) if parts else None

    text = str(value).lower()
    match = _RANGE_YEARS.search(text)
    if match:
        return float(match.group(1))
    years = sum(float(match) for match in _YEARS.findall(text))
    months = sum(float(match) for match in _MONTHS.findall(text)) / 12
    if years or months:
        return years + months
    total, found = 0.0, False
    for start, end in _DATE_RANGE.findall(text):
        end_year = date.today().year if not end.isdigit() else int(end)
        total += max(0, end_year - int(start))
        found = True
    if found:
        return total
    if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*\+?\s*", text):
        return float(text.replace("+", ""))
    return None