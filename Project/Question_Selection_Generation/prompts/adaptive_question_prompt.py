"""Prompt contract for adaptive Changing-Tech question generation."""
from __future__ import annotations

import json


def build_adaptive_prompt(
    jd: dict,
    changing_skills: list[str],
    average_score: float,
    difficulty_distribution: dict[str, int],
    used_questions: list[str],
    skill_performance: dict[str, float] | None = None,
) -> str:
    required = {"questions": [{"skill": "...", "difficulty": "Easy|Medium|Hard", "question": "...", "reference_answer": "5-6 meaningful sentences", "expected_concepts": ["..."]}]}
    compact_jd = {
        "job_title": jd.get("job_title", ""),
        "expected_skills": jd.get("expected_skills", []),
    }
    compact_used = [question[:180] for question in used_questions]
    return f"""You generate question content for an assessment. Python has already decided the number and difficulty distribution.
Return ONLY valid JSON matching this shape: {json.dumps(required, ensure_ascii=False)}

Rules:
- Generate exactly {sum(difficulty_distribution.values())} questions.
- Use only these Changing Technology skills: {json.dumps(changing_skills, ensure_ascii=False)}.
- Use this exact difficulty distribution: {json.dumps(difficulty_distribution)}. Do not change it.
- Do not generate stable Core CS questions such as polymorphism, linked lists, normalization, or generic algorithms.
- Do not decide whether a skill is Core CS or Changing Technology.
- Do not repeat or paraphrase an already-used question.
- Each reference_answer must contain exactly 5 concise, meaningful, technically accurate sentences, with at most 16 words per sentence. Do not use headings, lists, or extra sentences.
- Each expected_concepts list must contain 3 to 6 concise concepts that a correct candidate answer should mention.
- Prefer stable fundamentals of the named technology over version-specific commands or rapidly changing APIs.
- Focus on the candidate's weaker areas when skill performance is provided, while staying within the requested skills.

Job Description: {json.dumps(compact_jd, ensure_ascii=False)}
Changing Technology skills: {json.dumps(changing_skills, ensure_ascii=False)}
Stage-1 average score: {average_score:.2f}
Skill performance: {json.dumps(skill_performance or {{}}, ensure_ascii=False)}
Already-used questions: {json.dumps(compact_used, ensure_ascii=False)}
"""
