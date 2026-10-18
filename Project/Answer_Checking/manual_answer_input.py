"""Interactive, idempotent ten-question RankResume exam workflow."""

from __future__ import annotations

import argparse
from collections import Counter

try:
    from Project.Question_Selection_Generation.db_helper import connect, ensure_schema
    from Project.Question_Selection_Generation.stage2_workflow import (
        Stage2StateError,
        generate_or_reuse_stage2,
    )
except ModuleNotFoundError:
    from Question_Selection_Generation.db_helper import connect, ensure_schema
    from Question_Selection_Generation.stage2_workflow import (
        Stage2StateError,
        generate_or_reuse_stage2,
    )

from .answer_evaluator import evaluate_pending_record
from .database import (
    get_candidate_exam_ids,
    get_database_connection,
    get_exam_evaluation_rows,
    get_latest_exam_id,
    get_pending_answers,
    get_stage1_questions,
    save_candidate_answer,
    supersede_duplicate_pending_stage1,
    update_evaluation_result,
)


def collect_multiline_answer() -> str:
    """Read a multiline candidate answer until ``done`` is entered."""

    print("Enter Candidate Answer:")
    print("(Type done on a separate line when this answer is complete)")
    lines = []
    while True:
        raw = input()
        if raw.strip().lower() == "done":
            break
        lines.append(raw)
    return "\n".join(lines)


def _ensure_exam_schema() -> None:
    connection = connect()
    try:
        ensure_schema(connection)
    finally:
        connection.close()


def _evaluate_pending(exam_id: str, candidate_id: int, jd_id: int) -> None:
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    pending = {item["evaluation_id"]: item for item in get_pending_answers()}
    for row in rows:
        if row["evaluation_status"] != "Pending":
            continue
        record = pending.get(row["evaluation_id"])
        if record is None:
            raise Stage2StateError(f"pending evaluation {row['evaluation_id']} disappeared")
        update_evaluation_result(record["evaluation_id"], evaluate_pending_record(record))


def _stage1_question_ids(exam_id: str, jd_id: int) -> list[int]:
    questions = get_stage1_questions(jd_id, exam_id)
    return [int(question["question_id"]) for question in questions]


def _validate_stage1_scope(exam_id: str, candidate_id: int, jd_id: int) -> list[dict]:
    question_ids = _stage1_question_ids(exam_id, jd_id)
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    stage1_rows = [
        row
        for row in rows
        if row["question_id"] in question_ids and row["evaluation_status"] != "Superseded"
    ]
    counts = Counter(row["question_id"] for row in stage1_rows)
    if any(count != 1 for count in counts.values()) or len(counts) != 6:
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
    answered_ids = {int(r["question_id"]) for r in (existing_rows or [])}
    for order, question in enumerate(questions, start=1):
        qid = int(question["question_id"])
        if qid in answered_ids:
            continue
        print(f"\nQuestion {order}: {question['question']}")
        answer = collect_multiline_answer()
        save_candidate_answer(jd_id, qid, answer, candidate_id, exam_id)
        print(f"Question {order} saved.")
        answered_ids.add(qid)


def _collect_stage2(jd_id: int, candidate_id: int, exam_id: str, questions: list[dict]) -> None:
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    saved_ids = {int(row["question_id"]) for row in rows if row["evaluation_status"] != "Superseded"}
    for question in questions:
        generated_id = int(question["ai_question_exam_id"])
        order = int(question["question_order"]) + 6
        if generated_id in saved_ids:
            continue
        print(f"\nQuestion {order}: {question['question']}")
        answer = collect_multiline_answer()
        save_candidate_answer(jd_id, generated_id, answer, candidate_id, exam_id)
        print(f"Question {order} saved.")
        saved_ids.add(generated_id)


def _verify_completed_exam(exam_id: str, candidate_id: int, jd_id: int) -> None:
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    valid_rows = [row for row in rows if row["evaluation_status"] != "Superseded"]
    if len(valid_rows) != 10:
        raise Stage2StateError(f"final verification failed: expected 10 answers, found {len(valid_rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect and complete a RankResume ten-question exam.")
    parser.add_argument("--exam-id", help="Use a specific verified exam session.")
    args, _unknown = parser.parse_known_args()

    print("========================================")
    print("     RANKRESUME EXAM")
    print("========================================")
    try:
        jd_id = int(input("Enter JD ID: ").strip())
        candidate_id = int(input("Enter Candidate ID: ").strip())
        if jd_id < 1 or candidate_id < 1:
            raise ValueError("JD ID and Candidate ID must be positive integers.")
        _ensure_exam_schema()
        candidate_exams = get_candidate_exam_ids(jd_id, candidate_id)
        if args.exam_id:
            exam_id = args.exam_id
        elif len(candidate_exams) == 1:
            exam_id = candidate_exams[0]
        elif len(candidate_exams) > 1:
            raise ValueError(f"multiple candidate attempts exist: {', '.join(candidate_exams)}")
        else:
            exam_id = get_latest_exam_id(jd_id)
        questions = get_stage1_questions(jd_id, exam_id)
    except (ValueError, Stage2StateError) as exc:
        print(f"Could not load a safe exam attempt: {exc}")
        return
    except Exception as exc:
        print(f"Database error while loading the exam: {exc}")
        return

    try:
        existing_rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
        stage1_ids = {int(q["question_id"]) for q in questions}
        stage1_answers = [
            r for r in existing_rows
            if r["question_id"] in stage1_ids and r["evaluation_status"] != "Superseded"
        ]

        if len(stage1_answers) < len(questions):
            _collect_stage1(jd_id, candidate_id, exam_id, questions, stage1_answers)

        while input("\nType finish to complete submission: ").strip().lower() != "finish":
            print("Please type finish to complete submission.")

        print("\nStage 1 answers saved successfully.")
        print("Evaluating initial answers...")
        _evaluate_pending(exam_id, candidate_id, jd_id)
        evaluated_stage1 = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
        completed_stage1 = [
            row for row in evaluated_stage1
            if row["evaluation_status"] in {"Completed", "Review Required"}
            and row["question_id"] in stage1_ids
        ]
        if len(completed_stage1) != 6:
            raise Stage2StateError(
                "initial assessment did not produce six eligible evaluation records"
            )
        print("Generating four additional questions using the LLM...")
        summary = generate_or_reuse_stage2(exam_id, jd_id, candidate_id)
        _collect_stage2(jd_id, candidate_id, exam_id, summary["questions"])
        print("Evaluating adaptive answers...")
        _evaluate_pending(exam_id, candidate_id, jd_id)
        _verify_completed_exam(exam_id, candidate_id, jd_id)
        print("\nEXAM SUBMISSION SUMMARY")
        print("-----------------------")
        print("Initial questions: 6")
        print("Adaptive questions: 4")
        print("Total paper questions: 10")
        print("Candidate answers saved: 10")
        print("All ten questions and candidate responses have been saved.")
    except (ValueError, Stage2StateError) as exc:
        print(f"Exam stopped safely: {exc}")
    except Exception as exc:
        print(f"Exam failed safely: {exc}")


if __name__ == "__main__":
    main()
