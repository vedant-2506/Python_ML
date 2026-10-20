"""Interactive, idempotent ten-question RankResume exam workflow."""
from __future__ import annotations

import argparse
import inspect
from collections import Counter
from typing import Any

# ----------------------------------------------------------------------
# Core workflow helpers – try the ``Project.`` prefixed import first,
# fall back to a plain import for environments where the package root is
# already on PYTHONPATH.
# ----------------------------------------------------------------------
try:
    from Project.Question_Selection_Generation.db_helper import (
        connect,
        ensure_schema,
    )
    from Project.Question_Selection_Generation.exam_workflow import (
        Stage1Selection,
        select_questions,
    )
    from Project.Question_Selection_Generation.stage2_workflow import (
        Stage2StateError,
        generate_or_reuse_stage2,
    )
except ModuleNotFoundError:
    from Question_Selection_Generation.db_helper import (
        connect,
        ensure_schema,
    )
    from Question_Selection_Generation.exam_workflow import (
        Stage1Selection,
        select_questions,
    )
    from Question_Selection_Generation.stage2_workflow import (
        Stage2StateError,
        generate_or_reuse_stage2,
    )

# ----------------------------------------------------------------------
# Final-result helper – **import once**.
# ----------------------------------------------------------------------
from .final_result import calculate_and_store_final_result

# ----------------------------------------------------------------------
# Other Answer-Checking utilities
# ----------------------------------------------------------------------
from .answer_evaluator import evaluate_pending_record
from .database import (
    get_candidate_all_exam_ids,
    get_candidate_exam_ids,
    get_database_connection,
    get_exam_evaluation_rows,
    get_exam_session_status,
    get_latest_exam_id,
    get_pending_answers,
    get_stage1_questions,
    save_candidate_answer,
    supersede_duplicate_pending_stage1,
    update_evaluation_result,
    update_exam_session_status,
)

# ----------------------------------------------------------------------
# Helper: read a multiline answer from the terminal
# ----------------------------------------------------------------------
def collect_multiline_answer() -> str:
    """Read a multiline candidate answer until a line containing only ``done``."""
    print(
        "Enter Candidate Answer (type 'done' on a separate line when finished):"
    )
    lines: list[str] = []
    while True:
        raw = input()
        if raw.strip().lower() == "done":
            break
        lines.append(raw)
    return "\n".join(lines)

# ----------------------------------------------------------------------
# Database-schema guard (runs DDL only once)
# ----------------------------------------------------------------------
def _ensure_exam_schema() -> None:
    """Ensure the required tables exist; do not re‑run DDL on every call."""
    try:
        conn = get_database_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'exam_sessions'
                    """
                )
                if cursor.fetchone():
                    return
        finally:
            conn.close()
    except Exception:
        pass

    connection = connect()
    try:
        ensure_schema(connection)
    finally:
        connection.close()

# ----------------------------------------------------------------------
# JD / Candidate validation
# ----------------------------------------------------------------------
def _validate_jd_and_candidate(jd_id: int, candidate_id: int) -> None:
    """Raise a clear error if the JD or candidate does not exist."""
    try:
        conn = get_database_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM public.job_description WHERE jd_id = %s",
                    (jd_id,),
                )
                if not cursor.fetchone():
                    raise ValueError(f"Job description {jd_id} was not found.")
                cursor.execute(
                    "SELECT 1 FROM public.candidate WHERE candidate_id = %s",
                    (candidate_id,),
                )
                if not cursor.fetchone():
                    raise ValueError(f"Candidate {candidate_id} was not found.")
        finally:
            conn.close()
    except Exception:
        raise

# ----------------------------------------------------------------------
# Evaluation helpers (cleaned of stray imports)
# ----------------------------------------------------------------------
def _evaluate_pending(exam_id: str, candidate_id: int, jd_id: int) -> None:
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    pending = {item["evaluation_id"]: item for item in get_pending_answers()}
    for row in rows:
        if row["evaluation_status"] != "Pending":
            continue
        record = pending.get(row["evaluation_id"])
        if record is None:
            raise Stage2StateError(
                f"pending evaluation {row['evaluation_id']} disappeared"
            )
        update_evaluation_result(
            record["evaluation_id"], evaluate_pending_record(record)
        )


def _stage1_question_ids(exam_id: str, jd_id: int) -> list[int]:
    questions = get_stage1_questions(jd_id, exam_id)
    return [int(q["question_id"]) for q in questions]


def _validate_stage1_scope(
    exam_id: str, candidate_id: int, jd_id: int
) -> list[dict]:
    question_ids = _stage1_question_ids(exam_id, jd_id)
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    stage1_rows = [
        r
        for r in rows
        if r["question_id"] in question_ids
        and r.get("question_source") in ("Question Bank", None)
        and r["evaluation_status"] != "Superseded"
    ]
    counts = Counter(r["question_id"] for r in stage1_rows)
    if any(c != 1 for c in counts.values()) or len(counts) != 6:
        raise Stage2StateError(
            "the selected exam has duplicate or missing Stage 1 answer records; "
            "refusing to overwrite or regenerate this attempt"
        )
    return stage1_rows


def _collect_stage1(
    jd_id: int,
    candidate_id: int,
    exam_id: str,
    questions: list[dict],
    existing_rows: list[dict] | None = None,
) -> None:
    answered_ids = {
        int(r["question_id"])
        for r in (existing_rows or [])
        if r.get("question_source") in ("Question Bank", None)
        and r["evaluation_status"] != "Superseded"
    }
    for order, question in enumerate(questions, start=1):
        qid = int(question["question_id"])
        if qid in answered_ids:
            continue
        print(f"\nQuestion {order} of {len(questions)}")
        diff = question.get("difficulty")
        if diff:
            print(f"Difficulty: {diff}")
        print(f"Question {order}: {question['question']}")
        answer = collect_multiline_answer()
        save_candidate_answer(jd_id, qid, answer, candidate_id, exam_id)
        print(f"Question {order} saved successfully.")
        answered_ids.add(qid)


def _collect_stage2(
    jd_id: int, candidate_id: int, exam_id: str, questions: list[dict]
) -> None:
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    saved_ids = {
        int(row["question_id"])
        for row in rows
        if row.get("question_source") in ("groq_llm", "LLM")
        and row["evaluation_status"] != "Superseded"
    }
    print("\n========================================")
    print("STAGE 2: ADAPTIVE ASSESSMENT")
    print("========================================")
    for question in questions:
        generated_id = int(question["ai_question_exam_id"])
        order = int(question["question_order"])
        if generated_id in saved_ids:
            continue
        print(f"\nQuestion {order} of 10")
        diff = question.get("difficulty")
        if diff:
            print(f"Difficulty: {diff}")
        print(f"Question {order}: {question['question']}")
        answer = collect_multiline_answer()
        save_candidate_answer(jd_id, generated_id, answer, candidate_id, exam_id)
        print(f"Question {order} saved successfully.")
        saved_ids.add(generated_id)


def _verify_completed_exam(
    exam_id: str, candidate_id: int, jd_id: int
) -> None:
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    valid_rows = [r for r in rows if r["evaluation_status"] != "Superseded"]
    stage1_rows = [
        r
        for r in valid_rows
        if r.get("question_source") in ("Question Bank", None)
    ]
    stage2_rows = [
        r
        for r in valid_rows
        if r.get("question_source") in ("groq_llm", "LLM")
    ]
    if len(valid_rows) != 10 or len(stage1_rows) != 6 or len(stage2_rows) != 4:
        raise Stage2StateError(
            f"final verification failed: expected 6 Stage 1 and 4 Stage 2 answers "
            f"(total 10). Found {len(stage1_rows)} Stage 1, "
            f"{len(stage2_rows)} Stage 2, total {len(valid_rows)}."
        )
    evaluated = [
        r
        for r in valid_rows
        if r["evaluation_status"] in {"Completed", "Review Required"}
    ]
    if len(evaluated) != 10:
        raise Stage2StateError(
            f"final verification failed: expected 10 evaluated answers, found "
            f"{len(evaluated)}."
        )


def _load_or_create_exam(
    jd_id: int, candidate_id: int, explicit_exam_id: str | None = None
) -> tuple[str, list[dict]]:
    """Resolve a candidate exam and persist Stage 1 questions if needed."""
    candidate_exams = get_candidate_exam_ids(jd_id, candidate_id)
    if explicit_exam_id:
        exam_id = explicit_exam_id
    elif len(candidate_exams) == 1:
        exam_id = candidate_exams[0]
    elif len(candidate_exams) > 1:
        raise ValueError(
            f"multiple candidate attempts exist: {', '.join(candidate_exams)}"
        )
    else:
        try:
            exam_id = get_latest_exam_id(jd_id)
        except ValueError as exc:
            if "No complete Stage 1 exam session found" not in str(exc):
                raise
            exam_id = None
    questions: list[dict] = []
    if exam_id:
        try:
            questions = get_stage1_questions(jd_id, exam_id)
        except ValueError as exc:
            if explicit_exam_id or candidate_exams:
                raise ValueError(
                    f"Existing exam {exam_id} does not have a valid Stage 1 "
                    f"question set; refusing to change an existing candidate "
                    f"attempt."
                )
    if not questions:
        conn = get_database_connection()
        try:
            print("Selecting Stage 1 questions...")
            selector_params = inspect.signature(select_questions)
            selector_kwargs = {"refresh": False}
            if "exam_id" in selector_params.parameters:
                selector_kwargs["exam_id"] = exam_id
            elif exam_id is not None:
                raise ValueError(
                    "The selector cannot target an existing exam ID; refusing "
                    "to create questions under another session."
                )
            selection = select_questions(conn, jd_id, **selector_kwargs)
            exam_id = str(selection.exam_id)
            conn.commit()
        finally:
            conn.close()
        questions = get_stage1_questions(jd_id, exam_id)
    if len(questions) != 6:
        raise ValueError(
            f"JD {jd_id} must have exactly 6 Stage 1 questions; found "
            f"{len(questions)}."
        )
    return exam_id, questions

# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect and complete a RankResume ten‑question exam."
    )
    parser.add_argument("--exam-id", help="Use a specific verified exam session.")
    args, _ = parser.parse_known_args()

    print("========================================")
    print("     RANKRESUME EXAM")
    print("========================================")
    try:
        jd_id = int(input("Enter JD ID: ").strip())
        candidate_id = int(input("Enter Candidate ID: ").strip())
        if jd_id < 1 or candidate_id < 1:
            raise ValueError(
                "JD ID and Candidate ID must be positive integers."
            )
        print("\nLoading job description...")
        print("Validating candidate...")
        print("Preparing exam session...")
        _validate_jd_and_candidate(jd_id, candidate_id)
        _ensure_exam_schema()
        exam_id, questions = _load_or_create_exam(jd_id, candidate_id, args.exam_id)
    except (ValueError, Stage2StateError) as exc:
        print(f"Could not load a safe exam attempt: {exc}")
        return
    except Exception as exc:
        print(f"Database error while loading the exam: {exc}")
        return

    try:
        print("\n========================================")
        print("STAGE 1: INITIAL ASSESSMENT")
        print("========================================")
        existing_rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
        stage1_ids = {int(q["question_id"]) for q in questions}
        stage1_answers = [
            r
            for r in existing_rows
            if r["question_id"] in stage1_ids
            and r.get("question_source") in ("Question Bank", None)
            and r["evaluation_status"] != "Superseded"
        ]
        if len(stage1_answers) < len(questions):
            _collect_stage1(
                jd_id, candidate_id, exam_id, questions, stage1_answers
            )
        while input("\nType finish to complete submission: ").strip().lower() != "finish":
            print("Please type finish to complete submission.")
        try:
            update_exam_session_status(exam_id, "STAGE1_SUBMITTED")
        except Exception:
            pass
        print("\nStage 1 answers saved: 6/6")
        print("Evaluating initial answers...")
        _evaluate_pending(exam_id, candidate_id, jd_id)
        evaluated_stage1 = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
        completed_stage1 = [
            r
            for r in evaluated_stage1
            if r["evaluation_status"] in {"Completed", "Review Required"}
            and r["question_id"] in stage1_ids
            and r.get("question_source") in ("Question Bank", None)
        ]
        if len(completed_stage1) != 6:
            raise Stage2StateError(
                "initial assessment did not produce six eligible evaluation records"
            )
        print("\nGenerating four additional questions using the LLM...")
        summary = generate_or_reuse_stage2(exam_id, jd_id, candidate_id)
        pct = summary.get("percentage")
        dist = summary.get("distribution")
        if pct is not None:
            print(f"Stage 1 average: {pct}%")
        if dist:
            print(f"Adaptive difficulty distribution: {dist}")
        try:
            update_exam_session_status(exam_id, "STAGE2_READY")
        except Exception:
            pass
        _collect_stage2(jd_id, candidate_id, exam_id, summary["questions"])
        print("\nEvaluating adaptive answers...")
        _evaluate_pending(exam_id, candidate_id, jd_id)
        _verify_completed_exam(exam_id, candidate_id, jd_id)
        try:
            update_exam_session_status(exam_id, "COMPLETED")
        except Exception:
            pass
        current_status = "COMPLETED"
        try:
            current_status = get_exam_session_status(exam_id)
        except Exception:
            pass
        print("\n========================================")
        print("EXAM SUBMISSION SUMMARY")
        print("========================================")
        print(f"Job Description ID: {jd_id}")
        print(f"Candidate ID: {candidate_id}")
        print(f"Exam ID: {exam_id}\n")
        print("Initial questions: 6")
        print("Adaptive questions: 4")
        print("Total questions: 10")
        print("Candidate answers saved: 10")
        print("Stage 1 evaluations: 6")
        print("Stage 2 evaluations: 4\n")
        if current_status == "COMPLETED":
            print("Exam status: COMPLETED")
            calculate_and_store_final_result(exam_id, candidate_id, jd_id)
            print("Final result calculated and stored successfully.\n")
            print(
                "All ten questions and candidate responses have been saved and "
                "verified successfully."
            )
        else:
            print(f"Exam status: {current_status or 'INCOMPLETE'}")
    except (ValueError, Stage2StateError) as exc:
        print(f"Exam stopped safely: {exc}")
    except Exception as exc:
        print(f"Exam failed safely: {exc}")


if __name__ == "__main__":
    main()
