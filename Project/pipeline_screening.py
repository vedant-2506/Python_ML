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

from DB_Store.rankresume_pipeline import score_all_candidates
from ATS_calculation.ranking import rank_candidates
from pipeline_assessment import print_section

def execute_step1_ats_calculation(
    connection: Any,
    jd_id: int,
    refresh_llm: bool = False,
) -> List[Dict[str, Any]]:
    """Compute and store ATS match scores for candidates against the given JD.

    Uses `score_all_candidates` from `DB_Store.rankresume_pipeline` which computes
    the 6-factor rule-based score, queries LLM evaluation (with Gemini/Ollama
    batching & caching), applies 60% rule + 40% LLM blend, saves detailed factor
    scores in `public.ats_score`, and updates `candidate.ats_score`.
    """
    print_section(f"Step 1: Calculating ATS Scores for Job Description {jd_id}")
    if refresh_llm:
        os.environ["RANKRESUME_REFRESH_LLM_SCORES"] = "1"
    else:
        os.environ.pop("RANKRESUME_REFRESH_LLM_SCORES", None)

    logger.info("Executing ATS scoring against JD ID %s...", jd_id)
    results = score_all_candidates(connection, jd_id=jd_id)
    if not results:
        logger.warning("No candidate scores were returned for JD %s.", jd_id)
        return []

    hybrid_count = sum(1 for r in results if r.get("scoring_mode") == "hybrid")
    rule_only_count = len(results) - hybrid_count
    logger.info(
        "Scored %s candidates for JD %s (%s hybrid, %s rule-only fallback).",
        len(results),
        jd_id,
        hybrid_count,
        rule_only_count,
    )
    print(f"[+] Processed ATS scores for {len(results)} candidate resumes.")
    print(f"  - Hybrid (Rule + LLM) scored : {hybrid_count}")
    print(f"  - Rule-based only fallback   : {rule_only_count}")
    print("[+] Stored granular factor scores in table 'ats_score' and updated 'candidate.ats_score'.")
    return results


def execute_step2_candidate_ranking(
    connection: Any,
    jd_id: int,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """Rank scored candidates for the specified JD and return the Top N cohort.

    Preserves competition ranking and handles equal-score ties cleanly.
    """
    print_section(f"Step 2: Candidate Ranking & Selection (Top {top_n})")
    all_ranked = rank_candidates(connection, jd_id=jd_id)
    if not all_ranked:
        raise RuntimeError(f"No candidates found with valid ATS scores for JD {jd_id}.")

    top_candidates = all_ranked[:top_n]

    print(f"\nLeaderboard for Job Description ID {jd_id} (Top {len(top_candidates)} of {len(all_ranked)} candidates):")
    print("=" * 76)
    print(f"{'Rank':<6} | {'Candidate ID':<14} | {'Candidate Name':<34} | {'ATS Score':>12}")
    print("-" * 76)
    for c in top_candidates:
        name = (c.get("candidate_name") or f"Candidate {c['candidate_id']}")[:34]
        print(f"{c['rank']:<6} | {c['candidate_id']:<14} | {name:<34} | {c['ats_score']:>11.2f}%")
    print("=" * 76)

    return top_candidates


def choose_jd_by_name(connection: Any, name: str) -> int:
    """Find one JD by its stored job_title; never silently choose a different JD."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT jd_id, job_title FROM public.job_description "
            "WHERE lower(trim(job_title)) = lower(trim(%s)) ORDER BY jd_id",
            (name,),
        )
        matches = cursor.fetchall()
    if not matches:
        raise ValueError(f"No job description named {name!r} exists in the database.")
    if len(matches) > 1:
        ids = ", ".join(str(row[0]) for row in matches)
        raise ValueError(f"More than one JD is named {name!r} (IDs: {ids}). Use --jd-id to disambiguate.")
    return int(matches[0][0])


def ask_resume_selection() -> tuple[Path, list[Path]]:
    """Validate a resume folder and choose the requested number of files."""
    while True:
        raw = input("Enter resume folder path: ").strip().strip('"').strip("'")
        folder = Path(raw).expanduser()
        if folder.is_dir():
            break
        print("[!] Folder not found. Please enter an existing folder path.")
    extensions = {".pdf", ".doc", ".docx"}
    files = sorted((f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in extensions), key=lambda f: f.name.lower())
    if not files:
        raise ValueError(f"No PDF, DOC or DOCX resumes found in {folder}.")
    print(f"Found {len(files)} resume files in: {folder}")
    while True:
        raw_count = input(f"How many resumes do you want to process? (1-{len(files)}): ").strip()
        try:
            count = int(raw_count)
            if 1 <= count <= len(files):
                break
        except ValueError:
            pass
        print(f"[!] Enter a whole number between 1 and {len(files)}.")
    selected = files[:count]
    print(f"Selected {len(selected)} resumes (alphabetical filename order):")
    for f in selected:
        print(f"  - {f.name}")
    return folder, selected

