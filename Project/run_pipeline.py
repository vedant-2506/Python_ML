#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RankResume pipeline component; keep alongside run_pipeline.py."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("RankResumePipeline")

from DB_Store.rankresume_pipeline import connect_db, resolve_target_jd_id
from Question_Selection_Generation.db_helper import ensure_schema as ensure_selection_schema, fetch_jd as fetch_jd_record
from Answer_Checking.database import ensure_answer_evaluation_table, get_exam_session_status
from pipeline_screening import (execute_step1_ats_calculation, execute_step2_candidate_ranking,
    choose_jd_by_name, ask_resume_selection)
from pipeline_assessment import (print_banner, check_session_expiration, resolve_candidate_exam_session,
    execute_step3a_stage1, evaluate_candidate_pending_answers, execute_step3b_stage2,
    execute_step4_final_score)

def run_pipeline(
    jd_id: Optional[int] = None,
    top_n: int = 5,
    refresh_llm: bool = False,
    skip_ats: bool = False,
    candidate_id_filter: Optional[int] = None,
    jd_name: Optional[str] = None,
    resume_count: Optional[int] = None,
) -> None:
    """Execute the end-to-end RankResume screening and assessment workflow."""
    print_banner("RANKRESUME: AI RESUME SCREENING & ADAPTIVE INTERVIEW PIPELINE")

    # Connect to PostgreSQL
    connection = connect_db()
    try:
        # Verify and ensure schemas are initialized
        logger.info("Ensuring database schemas exist...")
        ensure_selection_schema(connection)
        ensure_answer_evaluation_table(connection)

        # Resolve target Job Description
        target_jd_id = choose_jd_by_name(connection, jd_name) if jd_name else resolve_target_jd_id(connection, jd_id)
        if target_jd_id is None:
            raise ValueError("No valid Job Description found in database.")

        jd_info = fetch_jd_record(connection, target_jd_id)
        job_title = jd_info.get("job_title", "Unknown Title")
        print(f"Target Job Description : ID {target_jd_id} - '{job_title}'")
        print(f"Evaluation Cohort Size : Top {top_n} candidates")
        if resume_count is not None:
            print(f"Requested resume files : {resume_count}")
            print("[!] Resume folder selection is a preflight check only. This project file "
                  "does not contain the resume ingestion interface, so ATS scoring "
                  "still uses resumes already stored in PostgreSQL. The selected "
                  "folder files are NOT imported or used to filter candidates.")

        # STEP 1: ATS Calculation
        if skip_ats:
            print_section("Step 1: Skipping ATS Score Calculation (--skip-ats enabled)")
        else:
            execute_step1_ats_calculation(connection, target_jd_id, refresh_llm=refresh_llm)

        # STEP 2: Candidate Ranking
        top_candidates = execute_step2_candidate_ranking(connection, target_jd_id, top_n=top_n)

        if len(top_candidates) < top_n:
            print(f"[!] Only {len(top_candidates)} ranked candidates available; requested Top {top_n}.")
        shortlisted = {int(c["candidate_id"]): c for c in top_candidates}
        target_count = len(top_candidates)
        if candidate_id_filter is not None and candidate_id_filter not in shortlisted:
            raise ValueError(
                f"Candidate ID {candidate_id_filter} is not among the Top {top_n} candidates."
            )

        # Evaluate the entire Top N cohort sequentially. No per-candidate report
        # or next-candidate prompt: only the final leaderboard is displayed.
        for position, candidate_info in enumerate(top_candidates, start=1):
            cand_id = int(candidate_info["candidate_id"])
            cand_name = candidate_info.get("candidate_name") or f"Candidate {cand_id}"
            ats_score = float(candidate_info["ats_score"])
            print_banner(f"CANDIDATE {position}/{target_count}: {cand_name} (ID: {cand_id})", char="*")
            try:
                with connection.cursor() as cur:
                    cur.execute(
                        """SELECT exam_id, final_result FROM public.final_evaluation_result
                           WHERE candidate_id = %s AND jd_id = %s
                           ORDER BY calculated_at DESC LIMIT 1""",
                        (cand_id, target_jd_id),
                    )
                    existing = cur.fetchone()
                if existing:
                    print(f"[*] Previously evaluated; reusing stored result for candidate {cand_id}.")
                    continue

                exam_id, is_resumed = resolve_candidate_exam_session(
                    connection, target_jd_id, cand_id
                )
                exam_status = get_exam_session_status(exam_id) or "STAGE1_READY"
                if exam_status == "COMPLETED":
                    raise RuntimeError(
                        f"Exam {exam_id} is marked COMPLETED but no final result exists. "
                        "Reconcile database state before continuing."
                    )
                is_active, _ = check_session_expiration(connection, exam_id)
                if not is_active:
                    raise RuntimeError(
                        f"Exam {exam_id} expired; saved answers preserved."
                    )

                execute_step3a_stage1(
                    connection, target_jd_id, cand_id, cand_name, exam_id
                )
                print("\n[+] Evaluating Stage 1 responses...")
                evaluate_candidate_pending_answers(exam_id, cand_id, target_jd_id)
                execute_step3b_stage2(
                    connection, target_jd_id, cand_id, cand_name, exam_id
                )
                execute_step4_final_score(
                    connection, target_jd_id, cand_id, cand_name,
                    job_title, exam_id, ats_score,
                )
                print("[+] Evaluation stored. Moving to next shortlisted candidate.")
            except (KeyboardInterrupt, EOFError):
                print("\n[!] Interview interrupted; saved answers preserved.")
                break
            except Exception as exc:
                connection.rollback()
                logger.exception("Interview failed for candidate %s: %s", cand_id, exc)
                print(f"[!] Candidate {cand_id} evaluation incomplete: {exc}")
                print("[!] Continuing with the next shortlisted candidate.")

        # FINAL COHORT SUMMARY: read stored results for the current JD and Top N cohort.
        # This includes candidates completed in previous runs, not just this run.
        connection.commit()
        with connection.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (candidate_id) candidate_id, final_result
                   FROM public.final_evaluation_result
                   WHERE jd_id = %s AND candidate_id = ANY(%s)
                   ORDER BY candidate_id, calculated_at DESC""",
                (target_jd_id, list(shortlisted)),
            )
            final_by_candidate = {int(cid): float(score) for cid, score in cur.fetchall()}

        print_banner("FINAL TOP N CANDIDATE LEADERBOARD")
        print(f"Job Role             : {job_title}")
        print(f"Top N Requested      : {top_n}")
        print(f"Candidates Shortlisted: {target_count}")
        print(f"Candidates Evaluated : {len(final_by_candidate)}/{target_count}")
        print("-" * 92)
        print(f"{'Rank':<6} {'Candidate Name':<34} {'ATS Score':>14} {'Final Score':>16}")
        print("-" * 92)
        ordered = sorted(
            top_candidates,
            key=lambda c: (int(c['candidate_id']) not in final_by_candidate,
                           -final_by_candidate.get(int(c['candidate_id']), 0.0),
                           -float(c['ats_score'])),
        )
        for position, candidate in enumerate(ordered, start=1):
            cid = int(candidate['candidate_id'])
            name = str(candidate.get('candidate_name') or f'Candidate {cid}')[:34]
            score = final_by_candidate.get(cid)
            score_text = f"{score:.2f}%" if score is not None else "Pending"
            print(f"{position:<6} {name:<34} {float(candidate['ats_score']):>13.2f}% {score_text:>16}")
        print("=" * 92)
        if len(final_by_candidate) == target_count:
            print("[+] All shortlisted candidates evaluated; final results stored in PostgreSQL.")
        else:
            print("[!] Some candidates are pending. Leaderboard includes existing saved results only.")

    except KeyboardInterrupt:
        print("\n\n[!] Pipeline interrupted by user. Safe session state preserved in database.")
    except Exception as exc:
        logger.exception("Pipeline execution failed: %s", exc)
        print(f"\n[!] Pipeline terminated safely with error: {exc}")
    finally:
        try:
            connection.close()
            logger.info("Database connection closed cleanly.")
        except Exception:
            pass


def main() -> None:
    """Parse command line arguments and execute the RankResume pipeline."""
    parser = argparse.ArgumentParser(
        description="RankResume: AI-Based Resume Screening & Adaptive Interview Pipeline"
    )
    parser.add_argument(
        "--jd-id",
        type=int,
        default=None,
        help="Target Job Description ID (defaults to RANKRESUME_JD_ID or JD 2)",
    )
    parser.add_argument(
        "--jd-name", type=str, default=None,
        help="Select an existing JD by its exact job_title (case-insensitive)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Number of top candidates to evaluate (prompted if omitted)",
    )
    parser.add_argument(
        "--refresh-llm",
        action="store_true",
        help="Force refreshing LLM ATS scores instead of using cached values",
    )
    parser.add_argument(
        "--skip-ats",
        action="store_true",
        help="Skip ATS scoring step and rank from existing ATS scores in database",
    )
    parser.add_argument(
        "--candidate-id",
        type=int,
        default=None,
        help="Evaluate only a specific candidate ID from the cohort",
    )

    args = parser.parse_args()

    target_jd = args.jd_id
    jd_name = args.jd_name
    if target_jd is None and not jd_name:
        jd_name = input("Enter Job Description Name: ").strip()
        if not jd_name:
            print("[!] JD name cannot be empty. Provide a JD name or --jd-id.")
            return

    try:
        _, selected_resumes = ask_resume_selection()
    except (ValueError, KeyboardInterrupt, EOFError) as exc:
        print(f"[!] Resume selection stopped: {exc}")
        return

    print("\n[!] IMPORTANT: The chosen files have only been counted and validated. "
          "The current scoring function reads candidates from PostgreSQL, not "
          "from the selected folder.")
    confirm = input("Continue with database candidates? (yes/no): ").strip().lower()
    if confirm not in ("yes", "y"):
        print("Stopped without scoring or modifying candidate records.")
        return

    if args.top_n is None:
        while True:
            try:
                top_n = int(input("How many Top N candidates do you want to evaluate? ").strip())
                if top_n >= 1:
                    break
            except ValueError:
                pass
            print("[!] Enter a positive whole number.")
    else:
        top_n = args.top_n
        if top_n < 1:
            print("[!] --top-n must be a positive integer.")
            return

    run_pipeline(
        jd_id=target_jd,
        jd_name=jd_name,
        resume_count=len(selected_resumes),
        top_n=top_n,
        refresh_llm=args.refresh_llm,
        skip_ats=args.skip_ats,
        candidate_id_filter=args.candidate_id,
    )


if __name__ == "__main__":
    main()
