from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, Optional

from .text_utils import (
    ALIASES,
    IMPLIED_BY,
    _as_dict,
    _canon,
    _clamp,
    _coerce_float,
    _flatten,
    _items,
    _parse_years,
    _project_text,
    _resume_text,
    _tokens,
    _tokens_from_canonical,
)

log = logging.getLogger(__name__)

WEIGHTS = {
    "keyword": 0.35,
    "similarity": 0.20,
    "title": 0.10,
    "experience": 0.15,
    "education": 0.15,
    "achievement": 0.05,
}
# JD-term coverage is naturally < 100% even for a great resume, so lift it a bit.
SIMILARITY_BOOST = 1.6

_LEVEL_PATTERNS = [
    (5, r"\b(phd|doctorate|doctoral)\b"),
    (4, r"\b(master|masters|mtech|m tech|msc|m sc|mca|mba|ms|m s|postgraduate|post graduate)\b"),
    (3, r"\b(bachelor|bachelors|btech|b tech|be|b e|bsc|b sc|bca|bcom|b com|ba|b a|bs|b s|bba|graduate|undergraduate)\b"),
    (2, r"\b(diploma|polytechnic)\b"),
    (1, r"\b(12th|hsc|intermediate|higher secondary|senior secondary)\b"),
]


_as_list = _items  # backwards compatibility

# --------------------------------------------------------------------------
# Factor scorers (return None when the JD doesn't ask for that factor)
# --------------------------------------------------------------------------
def _keyword_strength(keyword: str, skills: list[str], skill_set: set[str],
                      resume_text: str, text_tokens: set[str]) -> float:
    """Estimate evidence strength for one requirement using direct, implied, or fuzzy matches."""
    if keyword in skill_set:
        return 1.0
    kpad = f" {keyword} "
    for s in skills:
        if kpad in f" {s} ":  # "python" inside "python programming"
            return 0.95
    for s in skills:
        if len(s.split()) >= 2 and f" {s} " in kpad:
            return 0.8
    if kpad in resume_text:  # mentioned in projects / experience text
        return 0.9
    for term in IMPLIED_BY.get(keyword, ()):
        term_toks = set(_tokens(term, stem=True))
        if term_toks and term_toks <= text_tokens:
            return 0.7
    ktoks = set(_tokens_from_canonical(keyword, stem=True))
    if len(ktoks) >= 2:
        cov = len(ktoks & text_tokens) / len(ktoks)
        if cov >= 0.5:
            return round(0.75 * cov, 3)
    if len(keyword) >= 4:
        for s in skills:
            if SequenceMatcher(None, keyword, s).ratio() >= 0.88:  # typos / spelling variants
                return 0.9
    return 0.0


def _keyword_analysis(required: Any, resume_skills: Any, resume_text: str):
    """Score required skills and collect matched/missing terms for factor evidence."""
    keywords: list[str] = []
    for item in _items(required):
        k = _canon(item)
        if k and k not in keywords:
            keywords.append(k)
    if not keywords:
        return None, [], []
    skills: list[str] = []
    for item in _items(resume_skills):
        s = _canon(item)
        if s and s not in skills:
            skills.append(s)
    skill_set = set(skills)
    text_tokens = set(_tokens_from_canonical(resume_text, stem=True))

    total, matched, missing = 0.0, [], []
    for k in keywords:
        strength = _keyword_strength(k, skills, skill_set, resume_text, text_tokens)
        total += strength
        (matched if strength >= 0.5 else missing).append(k)
    return round(total / len(keywords) * 100, 2), matched, missing


def calculate_keyword_score(required_keywords: Any, resume_keywords: Any, resume_text: Any = None) -> float:
    """Return a standalone keyword score for callers that do not need full factor details."""
    padded = f" {_canon(resume_text)} " if resume_text else " "
    score, _, _ = _keyword_analysis(required_keywords, resume_keywords, padded)
    return score or 0.0


def _cosine_similarity(first: list[float], second: list[float]) -> Optional[float]:
    """Compare two embedding vectors, returning no score when either vector is unusable."""
    if not first or len(first) != len(second):
        return None
    dot = sum(left * right for left, right in zip(first, second))
    first_norm = sum(value * value for value in first) ** 0.5
    second_norm = sum(value * value for value in second) ** 0.5
    if not first_norm or not second_norm:
        return None
    return max(0.0, min(1.0, dot / (first_norm * second_norm)))


def _semantic_similarities(reference_text: str, candidate_texts: list[str]) -> Optional[list[float]]:
    """Score texts with a local embedding model, allowing callers to fall back when unavailable."""
    if not candidate_texts:
        return []
    try:
        model = _get_embedding_model()
        embeddings = model.encode(
            [reference_text, *candidate_texts],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        reference = embeddings[0].tolist()
        candidates = [embedding.tolist() for embedding in embeddings[1:]]
        similarities = [_cosine_similarity(reference, candidate) for candidate in candidates]
    except Exception as exc:
        log.debug("Local semantic model unavailable; using lexical matching: %s", exc)
        return None
    if any(similarity is None for similarity in similarities):
        return None
    return [similarity for similarity in similarities if similarity is not None]


@lru_cache(maxsize=1)
def _get_embedding_model():
    """Load and cache the configured embedding model so repeated comparisons avoid reloads."""
    from sentence_transformers import SentenceTransformer

    model_name = os.environ.get(
        "ATS_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
    )
    return SentenceTransformer(model_name)


def _semantic_similarity(first_text: str, second_text: str) -> Optional[float]:
    """Compare one text pair semantically while preserving the model-unavailable fallback."""
    similarities = _semantic_similarities(first_text, [second_text])
    return similarities[0] if similarities else None


def _lexical_similarity_score(jd_text: str, resume_text: str) -> Optional[float]:
    """Estimate project relevance from normalized term coverage when embeddings are unavailable."""
    jd_raw = {t for t in _tokens(jd_text, stem=True) if len(t) > 2}
    if not jd_raw:
        return None
    res_raw = set(_tokens(resume_text, stem=True))
    if not res_raw:
        return 0.0

    def expand_terms(text: str) -> set[str]:
        """Expand text with aliases and implied evidence so lexical comparison is less brittle."""
        expanded = set()
        for term in _tokens(text, stem=True):
            if len(term) <= 2:
                continue
            expanded.add(term)
            if term in ALIASES:
                expanded.add(_canon(ALIASES[term]))
        text_norm = _canon(text)
        for base, implied in IMPLIED_BY.items():
            if base in text_norm:
                expanded.update(_tokens(base, stem=True))
                for item in implied:
                    expanded.update(_tokens(item, stem=True))
        return expanded

    jd_terms = expand_terms(jd_text)
    res_terms = expand_terms(resume_text)
    if not jd_terms or not res_terms:
        return 0.0

    direct_overlap = len(jd_terms & res_terms)
    coverage = direct_overlap / len(jd_terms)
    union = len(jd_terms | res_terms)
    jaccard = direct_overlap / union if union else 0.0
    score = (0.7 * coverage + 0.3 * jaccard) * 100
    return round(min(100.0, score * SIMILARITY_BOOST), 2)


def _similarity_score(jd_text: str, resume_text: str) -> Optional[float]:
    """Choose semantic or lexical similarity and mark empty JD text as inapplicable."""
    if not _tokens(jd_text, stem=True):
        return None
    if not _tokens(resume_text, stem=True):
        return 0.0
    semantic = _semantic_similarity(jd_text, resume_text)
    if semantic is not None:
        return round(semantic * 100, 2)
    return _lexical_similarity_score(jd_text, resume_text)


def _lexical_title_similarity(jd_title: str, titles: list[str]) -> float:
    """Score role-title overlap lexically when no semantic model can be used."""
    jd_toks = set(_tokens_from_canonical(jd_title))
    best = 0.0
    for title in titles:
        if title == jd_title:
            return 100.0
        if f" {jd_title} " in f" {title} " or f" {title} " in f" {jd_title} ":
            best = max(best, 90.0)
        title_toks = set(_tokens_from_canonical(title))
        if not title_toks or not jd_toks:
            continue
        overlap = len(jd_toks & title_toks)
        coverage = overlap / len(jd_toks)
        jaccard = overlap / len(jd_toks | title_toks)
        best = max(best, 100 * (0.7 * coverage + 0.3 * jaccard))
    return round(min(100.0, best), 2)


def _estimate_title_similarity(jd_title: Any, resume_titles: Any) -> Optional[float]:
    """Compare the JD title with candidate roles and omit this factor when titles are absent."""
    jd = _canon(jd_title)
    if not jd:
        return None
    titles = [t for t in (_canon(x) for x in _items(resume_titles, split=False)) if t]
    if not titles:
        return None  # fresher / no previous roles: factor not applicable (weights renormalized)
    if jd in titles:
        return 100.0
    similarities = _semantic_similarities(jd, titles)
    if similarities is None:
        return _lexical_title_similarity(jd, titles)
    best = max(similarities, default=0.0) * 100
    return round(min(100.0, best), 2)


def _calculate_experience_score(required_years: Any, candidate_years: Any) -> Optional[float]:
    """Convert required and candidate tenure into a partial-credit factor score."""
    required = _coerce_float(required_years, 0.0)
    candidate = _coerce_float(candidate_years, 0.0)
    if required <= 0:
        return None
    if candidate >= required:
        return 100.0
    return round(_clamp(100 * (candidate / required) ** 0.7), 2)  # gentle partial credit


def _degree_level(text: str) -> int:
    """Map qualification text to an ordered education level for degree comparisons."""
    canon = _canon(text)
    return max((lvl for lvl, pat in _LEVEL_PATTERNS if re.search(pat, canon)), default=0)


def _normalize_pct(value: Any) -> float:
    """Convert common GPA, CGPA, and percentage scales to a comparable 0-100 value."""
    x = _coerce_float(value, 0.0)
    if x <= 0:
        return 0.0
    if x <= 4.0:
        return x * 25  # 4-point GPA
    if x <= 10.0:
        return x * 10  # 10-point CGPA
    return min(x, 100.0)


_PCT_KEYS = ("percentage", "percentage/mark", "mark", "marks", "grade", "gpa", "cgpa", "score", "minimum_percentage",
             "minimum_percent")


def _first_pct(record: Any) -> float:
    """Find the first recognized grade field so education records use a consistent scale."""
    if isinstance(record, dict):
        for key in _PCT_KEYS:
            if record.get(key):
                return _normalize_pct(record[key])
    return 0.0


def _calculate_education_score(required_education: Any, candidate_education: Any) -> Optional[float]:
    """Compare qualification level and grades while excluding education not requested by the JD."""
    req = required_education
    if isinstance(req, list):
        req = req[0] if req else None
    if not req:
        return None
    if isinstance(req, dict):
        req_text = " ".join(_flatten([req.get(k) for k in ("degree", "qualification", "degree_name", "field")]))
    else:
        req_text = " ".join(_flatten(req))
    req_pct = _first_pct(req)
    if not req_text.strip() and req_pct <= 0:
        return None
    req_level = _degree_level(req_text)

    records = candidate_education if isinstance(candidate_education, list) else [candidate_education]
    records = [r for r in records if r]
    if not records:
        return 0.0

    req_toks = set(_tokens(req_text, stem=True))
    best = 0.0
    for rec in records:
        cand_text = " ".join(_flatten(rec))
        cand_level = _degree_level(cand_text)
        if not req_text.strip():
            level_score = 100.0
        elif req_level and cand_level:
            level_score = 100.0 if cand_level >= req_level else 100 * (cand_level / req_level) ** 2
        else:
            cand_toks = set(_tokens(cand_text, stem=True))
            level_score = 100 * len(req_toks & cand_toks) / len(req_toks) if req_toks else 100.0
        cand_pct = _first_pct(rec)
        if req_pct > 0 and cand_pct > 0:
            score = 0.75 * level_score + 0.25 * min(100.0, cand_pct / req_pct * 100)
        else:
            score = level_score  # don't punish a missing percentage
        best = max(best, score)
    return round(_clamp(best), 2)


def _achievement_score(required_achievements: Any, candidate_achievements: Any) -> Optional[float]:
    """Measure required certificate or achievement coverage without penalizing absent requirements."""
    required = []
    for item in _items(required_achievements, split=False):
        canonical = _canon(item)
        if canonical:
            required.append(canonical)
    if not required:
        return None
    candidates = []
    for item in _items(candidate_achievements, split=False):
        canonical = _canon(item)
        if canonical:
            candidates.append(canonical)
    if not candidates:
        return 0.0
    scores = []
    for r in required:
        r_toks = set(_tokens_from_canonical(r, stem=True))
        best = 0.0
        for c in candidates:
            if f" {r} " in f" {c} " or f" {c} " in f" {r} ":
                best = 1.0
                break
            if r_toks:
                best = max(best, len(r_toks & set(_tokens_from_canonical(c, stem=True))) / len(r_toks))
        scores.append(best)
    return round(sum(scores) / len(scores) * 100, 2)


# --------------------------------------------------------------------------
# Result object + main evaluation
# --------------------------------------------------------------------------
@dataclass
class ATSFactorResult:
    """Store component scores and evidence so callers can explain the deterministic ATS result."""
    keyword_score: float
    similarity_score: float
    title_score: float
    experience_score: float
    education_score: float
    achievement_score: float
    rule_based_score: float
    weighted_details: dict[str, float]
    evidence: dict[str, str]
    applicable_factors: dict[str, bool] = field(default_factory=dict)
    effective_weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize rounded scores and factor metadata for APIs, logs, or database storage."""
        return {
            "keyword_score": round(self.keyword_score, 2),
            "similarity_score": round(self.similarity_score, 2),
            "title_score": round(self.title_score, 2),
            "experience_score": round(self.experience_score, 2),
            "education_score": round(self.education_score, 2),
            "achievement_score": round(self.achievement_score, 2),
            "rule_based_score": round(self.rule_based_score, 2),
            "weighted_details": {k: round(v, 4) for k, v in self.weighted_details.items()},
            "effective_weights": {k: round(v, 4) for k, v in self.effective_weights.items()},
            "applicable_factors": self.applicable_factors,
            "evidence": self.evidence,
        }


def _jd_text(jd: dict[str, Any]) -> str:
    """Flatten relevant job-description fields for shared text matching operations."""
    keys = ("job_title", "responsibilities", "required_skills", "expected_skills",
            "achievement_requirements", "description", "qualifications")
    return " ".join(part for key in keys for part in _flatten(jd.get(key)))


def _jd_skill_text(jd: dict[str, Any]) -> str:
    """Select requested skills so project similarity is anchored to the job requirements."""
    skills = jd.get("required_skills") or jd.get("expected_skills") or []
    return " ".join(_items(skills))


def _resume_titles(resume: dict[str, Any]) -> list[Any]:
    """Gather role titles from supported resume shapes for title-fit scoring."""
    titles = list(_items(resume.get("job_titles") or resume.get("previous_job_roles") or [], split=False))
    exp = resume.get("experience")
    if isinstance(exp, list):
        for entry in exp:
            if isinstance(entry, dict):
                t = entry.get("title") or entry.get("role") or entry.get("position")
                if t:
                    titles.append(t)
    return titles


def _required_years(jd: dict[str, Any]) -> Optional[float]:
    """Resolve job experience requirements to years so factor scoring handles varied schemas."""
    raw = jd.get("required_experience_years") or jd.get("expected_experience")
    if isinstance(raw, list):
        vals = [v for v in (_parse_years(x) for x in raw) if v is not None]
        return max(vals) if vals else None
    return _parse_years(raw)


def _candidate_years(resume: dict[str, Any]) -> float:
    """Read candidate tenure from known resume fields, defaulting to zero when missing."""
    for key in ("experience_years", "total_experience", "years_of_experience", "experience"):
        parsed = _parse_years(resume.get(key))
        if parsed is not None:
            return parsed
    return 0.0


def evaluate_candidate_against_jd(jd: dict[str, Any], resume: dict[str, Any]) -> ATSFactorResult:
    """Evaluate all applicable deterministic factors and retain evidence for the final score."""
    jd = _as_dict(jd)
    resume = _as_dict(resume)
    resume_text = _resume_text(resume)
    project_text = _project_text(resume)

    required_skills = jd.get("required_skills") or jd.get("expected_skills") or []
    resume_skills = resume.get("skills") or resume.get("skill") or []
    keyword, matched, missing = _keyword_analysis(required_skills, resume_skills, resume_text)

    similarity = _similarity_score(_jd_skill_text(jd), project_text)
    title = _estimate_title_similarity(jd.get("job_title"), _resume_titles(resume))

    required_years = _required_years(jd)
    candidate_years = _candidate_years(resume)
    experience = _calculate_experience_score(required_years, candidate_years)

    required_education = jd.get("required_education") or jd.get("expected_education")
    education = _calculate_education_score(required_education, resume.get("education") or [])

    achievement_requirements = jd.get("achievement_requirements") or jd.get("expected_certificate") or []
    candidate_achievements = (
        resume.get("achievements") or resume.get("certificate") or resume.get("certificates") or []
    )
    achievement = _achievement_score(achievement_requirements, candidate_achievements)

    scores = {
        "keyword": keyword, "similarity": similarity, "title": title,
        "experience": experience, "education": education, "achievement": achievement,
    }
    applicable = {
        key: value is not None and value > 0
        for key, value in scores.items()
    }

    # If a factor is not available or the candidate has no evidence, do not let it drag the score downward.
    # This keeps strong matches above 50 instead of being crushed by sparse optional factors.
    effective: dict[str, float] = {}
    weighted: dict[str, float] = {}
    total_weight = sum(WEIGHTS[k] for k, ok in applicable.items() if ok)
    if total_weight <= 0:
        rule_based_score = round(_clamp((keyword or 0.0) + (similarity or 0.0) * 0.5), 2)
    else:
        effective = {k: (WEIGHTS[k] / total_weight if ok and total_weight else 0.0) for k, ok in applicable.items()}
        weighted = {k: (scores[k] or 0.0) * effective[k] for k in scores}
        base_score = sum(weighted.values())
        # Preserve a realistic floor for clearly strong matches.
        if base_score < 50 and keyword and similarity:
            base_score = min(100.0, base_score + (50 - base_score) * 0.35)
        rule_based_score = round(_clamp(base_score), 2)

    na = "not requested by JD (excluded from score)"
    evidence = {
        "keyword": na if keyword is None else
        f"Matched {len(matched)} of {len(matched) + len(missing)} required keywords."
        + (f" Missing: {', '.join(missing[:10])}." if missing else ""),
        "similarity": na if similarity is None else f"JD term coverage in resume scored {similarity}.",
        "title": "not applicable (no job title in JD or resume; excluded from score)" if title is None else f"Title match scored {title} against '{jd.get('job_title')}'.",
        "experience": na if experience is None else
        f"Candidate ~{round(candidate_years, 1)} yrs vs required {required_years} yrs.",
        "education": na if education is None else f"Education match scored {education} vs {required_education}.",
        "achievement": na if achievement is None else f"Achievement/certificate match scored {achievement}.",
    }

    return ATSFactorResult(
        keyword_score=keyword or 0.0,
        similarity_score=similarity or 0.0,
        title_score=title or 0.0,
        experience_score=experience or 0.0,
        education_score=education or 0.0,
        achievement_score=achievement or 0.0,
        rule_based_score=rule_based_score,
        weighted_details=weighted,
        evidence=evidence,
        applicable_factors=applicable,
        effective_weights=effective,
    )


def compute_rule_based_score(jd: dict[str, Any], resume: dict[str, Any]) -> float:
    """Return only the combined rule-based score for integrations that need a scalar."""
    return evaluate_candidate_against_jd(jd, resume).rule_based_score


