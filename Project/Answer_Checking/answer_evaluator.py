"""Final evaluator that combines semantic similarity and factual correctness."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .database import update_evaluation_result
from .config import get_max_marks_for_difficulty
from .factual_correctness import calculate_factual_correctness, normalize_expected_facts
from .semantic_similarity import calculate_semantic_score


def classify_answer(answer_score: float) -> str:
    if answer_score >= 70:
        return "Correct"
    if answer_score >= 40:
        return "Partially Correct"
    return "Incorrect"


def calculate_obtained_marks(answer_score: Optional[float], classification: str, max_marks: Optional[float]) -> Optional[float]:
    if classification == "Incorrect":
        return 0.0
    if max_marks is None:
        return None
    if answer_score is None:
        return None
    return (answer_score / 100.0) * float(max_marks)


def evaluate_pending_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate one pending answer record and return updated values."""

    candidate_answer = record.get("candidate_answer")
    expected_answer = record.get("expected_answer")
    expected_facts = record.get("expected_facts")
    max_marks = get_max_marks_for_difficulty(record.get("difficulty"), record.get("max_marks"))

    notes = []

    if candidate_answer is None or not str(candidate_answer).strip():
        result = {
            "semantic_score": 0.0,
            "factual_correctness_score": 0.0,
            "answer_score": 0.0,
            "classification": "Incorrect",
            "obtained_marks": 0.0,
            "max_marks": max_marks,
            "evaluation_status": "Completed",
            "evaluation_notes": "Candidate answer was empty; zero marks assigned.",
        }
        return result

    semantic_score, semantic_meta = calculate_semantic_score(expected_answer or "", candidate_answer)
    factual_context = normalize_expected_facts(expected_facts)
    if expected_answer is not None and str(expected_answer).strip():
        factual_context.append(str(expected_answer))
        if not normalize_expected_facts(expected_facts):
            notes.append("expected_facts missing: the reference answer was used for factual verification.")
    elif not factual_context:
        notes.append("Expected facts and reference answer are missing; factual verification requires review.")

    factual_result = calculate_factual_correctness(candidate_answer, factual_context)
    factual_score = factual_result.get("score")
    factual_note = factual_result.get("notes", "Factual correctness computed.")
    if factual_result.get("status") == "Review Required":
        notes.append(factual_note)

    if factual_score is None or semantic_score is None:
        result = {
            "semantic_score": semantic_score,
            "factual_correctness_score": factual_score,
            "answer_score": None,
            "classification": None,
            "obtained_marks": None,
            "max_marks": max_marks,
            "evaluation_status": "Review Required",
            "evaluation_notes": "; ".join(notes) or "Evaluation required manual review.",
        }
        return result

    answer_score = 0.5 * semantic_score + 0.5 * factual_score
    classification = classify_answer(answer_score)
    obtained_marks = calculate_obtained_marks(answer_score, classification, max_marks)
    evaluation_status = (
        "Review Required"
        if factual_result.get("status") == "Review Required"
        else "Completed"
    )
    notes.append(semantic_meta.get("note", "Semantic similarity computed."))
    if factual_result.get("status") != "Review Required":
        notes.append(factual_note)

    result = {
        "semantic_score": float(semantic_score),
        "factual_correctness_score": float(factual_score),
        "answer_score": float(answer_score),
        "classification": classification,
        "obtained_marks": obtained_marks,
        "max_marks": max_marks,
        "evaluation_status": evaluation_status,
        "evaluation_notes": "; ".join(notes),
    }
    return result


def evaluate_record_by_id(evaluation_id: int) -> Dict[str, Any]:
    """Evaluate a saved evaluation row and persist the result."""

    from .database import get_evaluation_by_id

    record = get_evaluation_by_id(evaluation_id)
    if record is None:
        raise ValueError(f"No evaluation record found for evaluation_id={evaluation_id}")
    if record.get("evaluation_status") != "Pending":
        raise ValueError(
            f"Evaluation {evaluation_id} is not pending; refusing to replace its existing result."
        )

    result = evaluate_pending_record(record)
    update_evaluation_result(evaluation_id, result)
    return result
