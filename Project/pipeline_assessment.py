#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RankResume pipeline component; keep alongside run_pipeline.py."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
from contextlib import contextmanager
logger = logging.getLogger("RankResumePipeline")

from Question_Selection_Generation.exam_workflow import select_questions
from Question_Selection_Generation.stage2_workflow import Stage2StateError, fetch_stage1_evaluations, generate_or_reuse_stage2
from Question_Selection_Generation.adaptive_policy import resolve_stage2_difficulty
from Answer_Checking.database import (get_candidate_exam_ids, get_exam_evaluation_rows,
    get_pending_answers, get_stage1_questions, save_candidate_answer,
    update_evaluation_result, update_exam_session_status)
from Answer_Checking.answer_evaluator import evaluate_pending_record
from Answer_Checking.final_result import calculate_and_store_final_result
from Answer_Checking.manual_answer_input import _verify_completed_exam, collect_multiline_answer

def print_banner(text: str, width: int = 80, char: str = "=") -> None:
    """Print a clean visual banner in the terminal."""
    print("\n" + char * width)
    print(text.center(width))
    print(char * width + "\n")


def print_section(title: str, width: int = 80) -> None:
    """Print a section header."""
    print("\n" + "-" * width)
    print(f" {title.upper()} ".center(width, "-"))
    print("-" * width)


def prompt_answer(prompt_label: str = "Enter your answer:") -> str:
    """Collect candidate answer from the terminal using multiline input."""
    print(f"\n{prompt_label}")
    return collect_multiline_answer()


def check_session_expiration(connection: Any, exam_id: str) -> Tuple[bool, int]:
    """Check if the 30-minute exam session has expired.

    Returns:
        (is_active: bool, remaining_seconds: int)
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT started_at, ends_at FROM public.exam_sessions WHERE exam_id = %s",
            (str(exam_id),),
        )
        row = cursor.fetchone()
    if row is None:
        return True, 1800

    started_at, ends_at = row
    now = datetime.now(timezone.utc)
    if ends_at.tzinfo is None:
        now_cmp = datetime.utcnow()
    else:
        now_cmp = now

    remaining = int((ends_at - now_cmp).total_seconds())
    return (remaining > 0), max(0, remaining)


def resolve_candidate_exam_session(
    connection: Any,
    jd_id: int,
    candidate_id: int,
    explicit_exam_id: Optional[str] = None,
) -> Tuple[str, bool]:
    """Find an existing active session or provision a new isolated candidate session.

    Returns:
        (exam_id: str, is_resumed: bool)
    """
    if explicit_exam_id:
        return explicit_exam_id, True

    # Check if this candidate already has an exam session
    candidate_exams = get_candidate_exam_ids(jd_id, candidate_id)
    if candidate_exams:
        exam_id = candidate_exams[0]
        logger.info(
            "Candidate %s has an existing exam session %s.", candidate_id, exam_id
        )
        return exam_id, True

    # Never reuse an unallocated session: it may belong to another candidate.
    # A newly created session needs a durable candidate association for reliable
    # resume-before-first-answer; see integration note accompanying this file.

    # Otherwise, create a clean session for this candidate
    new_id = uuid.uuid4()
    started_at = datetime.utcnow()
    ends_at = started_at + timedelta(minutes=30)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.exam_sessions
                (exam_id, jd_id, started_at, ends_at, duration_minutes, status)
            VALUES (%s, %s, %s, %s, 30, 'STAGE1_READY')
            """,
            (str(new_id), jd_id, started_at, ends_at),
        )
    connection.commit()
    logger.info(
        "Created new 30-minute exam session %s for Candidate %s on JD %s.",
        new_id,
        candidate_id,
        jd_id,
    )
    return str(new_id), False


def execute_step3a_stage1(
    connection: Any,
    jd_id: int,
    candidate_id: int,
    candidate_name: str,
    exam_id: str,
) -> None:
    """Select Stage 1 bank questions, display in terminal, collect answers, and evaluate."""
    # Ensure Stage 1 questions exist in question_exam
    questions = []
    try:
        questions = get_stage1_questions(jd_id, exam_id)
    except Exception:
        pass

    if len(questions) != 6:
        logger.info("Selecting 6 Stage 1 core CS questions for Exam %s...", exam_id)
        selection = select_questions(connection, jd_id, exam_id=exam_id)
        connection.commit()
        questions = get_stage1_questions(jd_id, exam_id)

    if len(questions) != 6:
        raise RuntimeError(
            f"Expected exactly 6 Stage 1 questions, but found {len(questions)} for exam {exam_id}."
        )

    # Check already answered questions to support interruption resumption
    existing_rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    answered_qids = {
        int(r["question_id"])
        for r in existing_rows
        if r.get("question_source") in ("Question Bank", None)
        and r["evaluation_status"] != "Superseded"
    }

    difficulty_marks = {"Easy": 6, "Medium": 12, "Hard": 18}

    print_section("STAGE 1: CORE COMPUTER SCIENCE QUESTIONS (60 MARKS)")
    print("Stage 1 covers 6 core CS questions: 3 Easy (6m), 2 Medium (12m), 1 Hard (18m).")
    print("Submit your response for each question. Type 'done' on a new line when finished.\n")

    for order, q in enumerate(questions, start=1):
        qid = int(q["question_id"])
        if qid in answered_qids:
            print(f"[*] Question {order}/6 already submitted. Skipping.")
            continue

        difficulty = q.get("difficulty", "Easy")
        max_marks = difficulty_marks.get(difficulty, 6)

        print("\n" + "=" * 60)
        print("RANKRESUME INTERVIEW")
        print("=" * 60)
        print(f"Candidate ID   : {candidate_id}")
        print(f"Candidate Name : {candidate_name}")
        print(f"JD ID          : {jd_id}")
        print()
        print(f"Stage 1 - Question {order}/6")
        print(f"Difficulty     : {difficulty}")
        print(f"Maximum Marks  : {max_marks}")
        print()
        print("Question:")
        print(q["question"], flush=True)
        print(flush=True)

        # Check time limit; log the operation in case the database blocks.
        logger.info("Stage 1: checking remaining time before question %s", order)
        is_active, rem_sec = check_session_expiration(connection, exam_id)
        logger.info("Stage 1: time check finished for question %s", order)
        if not is_active:
            raise RuntimeError(
                f"Exam session {exam_id} has exceeded its 30-minute time limit."
            )
        mins, secs = divmod(rem_sec, 60)
        print(f"[Time Remaining: {mins:02d}:{secs:02d}]", flush=True)

        answer_text = prompt_answer("Enter your answer:")
        connection.commit()  # Release the main connection's read transaction.
        save_candidate_answer(
            jd_id=jd_id,
            question_id=qid,
            candidate_answer=answer_text,
            candidate_id=candidate_id,
            exam_id=exam_id,
            question_source="Question Bank",
        )
        print(f"\n[+] Question {order}/6 saved successfully.")
        answered_qids.add(qid)

    # Require explicit Stage 1 submission, matching manual_answer_input.py.
    while input("\nType finish to complete Stage 1 submission: ").strip().lower() != "finish":
        print("Please type finish to complete submission.")

    connection.commit()
    # Update exam status to STAGE1_SUBMITTED
    try:
        update_exam_session_status(exam_id, "STAGE1_SUBMITTED")
    except Exception as exc:
        logger.warning("Could not update session status to STAGE1_SUBMITTED: %s", exc)

    print("\n[+] Stage 1 answers saved: 6/6.")


def evaluate_candidate_pending_answers(
    exam_id: str,
    candidate_id: int,
    jd_id: int,
) -> int:
    """Evaluate all pending answer records for this candidate and exam."""
    rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    pending = {item["evaluation_id"]: item for item in get_pending_answers()}
    evaluated_count = 0

    for row in rows:
        if row["evaluation_status"] != "Pending":
            continue
        record = pending.get(row["evaluation_id"])
        if record is None:
            continue

        result = evaluate_pending_record(record)
        update_evaluation_result(record["evaluation_id"], result)
        evaluated_count += 1

    return evaluated_count


@contextmanager
def trace_stage2_groq_calls():
    """Log model verification and each generation attempt without editing other modules.

    Instrument only for the duration of the synchronous Stage 2 call. This does
    not enforce a hard deadline or alter Groq request/validation behavior.
    """
    from Question_Selection_Generation import llm_question_generator as generator

    original_verify = generator.verify_model
    original_generate = generator.generate_json
    attempts = 0

    def traced_verify(model):
        started = time.perf_counter()
        logger.info("Stage 2: verifying Groq model %s", model)
        try:
            result = original_verify(model)
            logger.info("Stage 2: model verification finished in %.2fs", time.perf_counter() - started)
            return result
        except Exception:
            logger.exception("Stage 2: model verification failed after %.2fs", time.perf_counter() - started)
            raise

    def traced_generate(prompt, model):
        nonlocal attempts
        attempts += 1
        started = time.perf_counter()
        logger.info("Stage 2: Groq generation attempt %d started (model=%s)", attempts, model)
        try:
            result = original_generate(prompt, model)
            logger.info("Stage 2: Groq attempt %d returned JSON in %.2fs; validating batch next", attempts, time.perf_counter() - started)
            return result
        except Exception:
            logger.exception("Stage 2: Groq attempt %d failed after %.2fs", attempts, time.perf_counter() - started)
            raise

    generator.verify_model = traced_verify
    generator.generate_json = traced_generate
    try:
        yield
    finally:
        generator.verify_model = original_verify
        generator.generate_json = original_generate
        logger.info("Stage 2: Groq generation calls made: %d", attempts)


def execute_step3b_stage2(
    connection: Any,
    jd_id: int,
    candidate_id: int,
    candidate_name: str,
    exam_id: str,
) -> None:
    """Generate 4 adaptive Stage 2 questions, collect answers, and evaluate."""
    print_section("STAGE 2: ADAPTIVE QUESTIONS (CHANGEABLE SKILLS)")

    # Read evaluated Stage 1 answers and compute adaptive difficulty
    evaluations = fetch_stage1_evaluations(connection, exam_id, candidate_id, jd_id)
    distribution, percentage, is_adaptive = resolve_stage2_difficulty(evaluations)

    pct_display = f"{percentage:.2f}%" if percentage is not None else "N/A"
    print(f"Stage 1 Evaluated Score   : {pct_display}")
    print(f"Adaptive Policy Applied   : {is_adaptive}")
    print(f"Stage 2 Target Difficulty : {distribution}\n")
    print("Generating/loading 4 adaptive questions targeting Job Description Changeable Skills...")

    # Trace Groq calls from the pipeline, without modifying generation modules.
    # The existing GROQ_TIMEOUT from .env/config.py still applies per network operation.
    started = time.perf_counter()
    logger.info("Stage 2: starting generation/reuse for candidate=%s exam=%s", candidate_id, exam_id)
    logger.info("Stage 2: configured Groq network timeout=%ss (not an overall deadline)",
                os.getenv("GROQ_TIMEOUT", "60"))
    try:
        with trace_stage2_groq_calls():
            summary = generate_or_reuse_stage2(exam_id, jd_id, candidate_id)
    except Exception:
        logger.exception("Stage 2 failed after %.2fs for exam=%s", time.perf_counter() - started, exam_id)
        raise
    logger.info("Stage 2: generation/reuse completed in %.2fs (reused=%s)",
                time.perf_counter() - started, summary.get("reused", False))
    questions = summary.get("questions", [])
    if len(questions) != 4:
        raise Stage2StateError(
            f"Stage 2 requires exactly 4 questions; found {len(questions)} for exam {exam_id}."
        )

    # The pipeline keeps a separate PostgreSQL connection open. Finish any
    # read transaction before updating the exam on this SAME connection;
    # otherwise a helper opening another connection can wait on our own locks.
    logger.info("Stage 2: verified %d questions; updating exam status", len(questions))
    connection.commit()
    status_started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            cursor.execute(
                "UPDATE public.exam_sessions SET status = %s WHERE exam_id = %s",
                ("STAGE2_READY", str(exam_id)),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Exam session {exam_id} not found while updating Stage 2 status")
        connection.commit()
    except Exception:
        connection.rollback()
        logger.exception("Stage 2: exam status update failed after %.2fs", time.perf_counter() - status_started)
        raise
    logger.info("Stage 2: exam status update finished in %.2fs", time.perf_counter() - status_started)

    # Identify questions already answered for resumption.
    # Stage 2 is already persisted; never regenerate merely to display it.
    # This helper may use its own database connection, so instrument it separately.
    logger.info("Stage 2: fetching existing answers for candidate=%s exam=%s", candidate_id, exam_id)
    fetch_started = time.perf_counter()
    try:
        rows = get_exam_evaluation_rows(exam_id, candidate_id, jd_id)
    except Exception:
        logger.exception("Stage 2: answer lookup failed after %.2fs", time.perf_counter() - fetch_started)
        raise
    logger.info("Stage 2: answer lookup finished in %.2fs; %d rows", time.perf_counter() - fetch_started, len(rows))
    saved_ids = {
        int(row["question_id"])
        for row in rows
        if row.get("question_source") in ("groq_llm", "LLM")
        and row["evaluation_status"] != "Superseded"
    }

    logger.info("Stage 2: %d of 4 adaptive questions already have saved answers", sum(int(q["ai_question_exam_id"]) in saved_ids for q in questions))
    print("\n[+] Four adaptive questions loaded for this candidate.", flush=True)
    print("\n[+] Stage 2 questions are ready. Displaying unanswered questions...", flush=True)
    for idx, q in enumerate(questions, start=1):
        generated_id = int(q["ai_question_exam_id"])
        overall_order = idx + 6
        if generated_id in saved_ids:
            logger.info("Stage 2: skipping already answered question %s (ID=%s)", overall_order, generated_id)
            print(f"[*] Question {overall_order}/10 already submitted. Skipping.", flush=True)
            continue

        difficulty = q.get("difficulty", "Medium")

        print("\n" + "=" * 60)
        print("STAGE 2 - ADAPTIVE QUESTIONS", flush=True)
        print("=" * 60)
        print(f"Candidate ID   : {candidate_id}")
        print(f"Question       : {overall_order}/10 (Adaptive {idx}/4)")
        print(f"Skill Tested   : {q.get('skill', 'Technical')}")
        print(f"Difficulty     : {difficulty}")
        print()
        print("Question:")
        print(q["question"], flush=True)
        print(flush=True)

        # Check time limit; log the operation in case the database blocks.
        logger.info("Stage 2: checking remaining time before question %s", overall_order)
        is_active, rem_sec = check_session_expiration(connection, exam_id)
        logger.info("Stage 2: time check finished for question %s", overall_order)
        if not is_active:
            raise RuntimeError(
                f"Exam session {exam_id} has exceeded its 30-minute time limit."
            )
        mins, secs = divmod(rem_sec, 60)
        print(f"[Time Remaining: {mins:02d}:{secs:02d}]", flush=True)

        answer_text = prompt_answer("Enter your answer:")
        connection.commit()  # release read transaction before helper's own connection
        logger.info("Stage 2: saving answer for question %s", overall_order)
        save_candidate_answer(
            jd_id=jd_id,
            question_id=generated_id,
            candidate_answer=answer_text,
            candidate_id=candidate_id,
            exam_id=exam_id,
            question_source="groq_llm",
        )
        logger.info("Stage 2: saved answer for question %s", overall_order)
        print(f"\n[+] Question {overall_order}/10 saved successfully.", flush=True)
        saved_ids.add(generated_id)

    print("\n[+] All four adaptive questions have answers saved.", flush=True)
    connection.commit()
    print("[+] Evaluating adaptive answers...", flush=True)
    evaluated_stage2 = evaluate_candidate_pending_answers(exam_id, candidate_id, jd_id)
    logger.info("Evaluated %s pending Stage 2 answers.", evaluated_stage2)

    # Verify all 10 questions are accounted for and evaluated
    logger.info("Stage 2: verifying all 10 evaluated answers")
    _verify_completed_exam(exam_id, candidate_id, jd_id)

    print("[+] All 10 answers evaluated and verified. Calculating final result...", flush=True)


def execute_step4_final_score(
    connection: Any,
    jd_id: int,
    candidate_id: int,
    candidate_name: str,
    job_title: str,
    exam_id: str,
    ats_score: float,
) -> Dict[str, Any]:
    """Compute and store final 60/40 weighted score, and update candidate.final_score."""
    print_section("Step 4: Final Exam Score Calculation")

    # Compute final score (0.60 * Stage 1 avg + 0.40 * Stage 2 avg)
    connection.commit()  # release any read transaction before final-result helper
    calculate_and_store_final_result(exam_id, candidate_id, jd_id)

    # Query the stored final result
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT first_six_average, last_four_average, final_result,
                   evaluation_status, calculated_at
            FROM public.final_evaluation_result
            WHERE exam_id = %s AND candidate_id = %s
            """,
            (exam_id, candidate_id),
        )
        row = cursor.fetchone()

    if not row:
        raise RuntimeError(
            f"Final evaluation result was not found for exam {exam_id}, candidate {candidate_id}."
        )

    first_six_avg, last_four_avg, final_result, eval_status, calc_at = row
    final_score_val = float(final_result)

    # Update candidate.final_score in candidate table
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE public.candidate SET final_score = %s WHERE candidate_id = %s",
            (round(final_score_val, 2), candidate_id),
        )
    connection.commit()
    logger.info("Final result saved; marking exam COMPLETED")
    update_exam_session_status(exam_id, "COMPLETED")
    logger.info("Updated candidate.final_score = %s for Candidate %s.", final_score_val, candidate_id)

    # Persist silently; the only score report is the final Top N leaderboard.
    logger.info("Stored final result for candidate %s (exam %s)", candidate_id, exam_id)

    return {
        "candidate_id": candidate_id,
        "candidate_name": candidate_name,
        "ats_score": ats_score,
        "first_six_average": float(first_six_avg),
        "last_four_average": float(last_four_avg),
        "final_result": final_score_val,
        "evaluation_status": eval_status,
        "exam_id": exam_id,
    }

