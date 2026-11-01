#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RankResume pipeline component; keep alongside run_pipeline.py."""
from __future__ import annotations

import logging
import json
from psycopg2.extras import Json
from DB_Store import rankresume_pipeline as ingestion
from ATS_calculation.ats_calculator import get_batch_gemini_evaluations, reset_gemini_failure_state
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
    candidate_ids: list[int] | None = None,
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
    results = score_selected_candidates(connection, jd_id, candidate_ids) if candidate_ids is not None else score_all_candidates(connection, jd_id=jd_id)
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
    candidate_ids: list[int] | None = None,
) -> List[Dict[str, Any]]:
    """Rank scored candidates for the specified JD and return the Top N cohort.

    Preserves competition ranking and handles equal-score ties cleanly.
    """
    print_section(f"Step 2: Candidate Ranking & Selection (Top {top_n})")
    all_ranked = rank_candidates(connection, jd_id=jd_id)
    if not all_ranked:
        raise RuntimeError(f"No candidates found with valid ATS scores for JD {jd_id}.")

    if candidate_ids is not None:
        allowed = set(candidate_ids)
        all_ranked = [c for c in all_ranked if int(c["candidate_id"]) in allowed]
    if not all_ranked:
        raise RuntimeError("No ATS-scored candidates found among the selected resumes.")
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



def import_selected_resumes(connection: Any, selected_files: list[Path]) -> list[int]:
    """Resolve only selected physical files by SHA256; import new ones without resetting DB.

    Hash matching avoids incorrectly matching same-named resumes from another folder.
    Every selected file must resolve or the run stops before ATS scoring.
    """
    if not selected_files:
        raise ValueError("No resume files selected.")
    # Initialize existing dictionaries required by the existing parse_resume() code.
    ingestion.seed_dictionary(connection)
    ingestion.load_controlled_labels(connection)
    try:
        ingestion.load_esco_labels(connection)
    except Exception as exc:
        logger.warning("ESCO labels unavailable; using existing controlled dictionary: %s", exc)
    ids = []
    for index, path in enumerate(selected_files, 1):
        if not path.is_file() or path.suffix.lower() not in ingestion.RESUME_EXTENSIONS:
            raise ValueError(f"Selected resume is missing or unsupported: {path}")
        digest = ingestion.sha256_file(path)
        with connection.cursor() as cur:
            cur.execute("SELECT candidate_id FROM public.candidate WHERE resume_hash = %s", (digest,))
            row = cur.fetchone()
        if row:
            cid = int(row[0])
            print(f"[{index}/{len(selected_files)}] Reusing existing resume: {path.name} (ID {cid})")
        else:
            print(f"[{index}/{len(selected_files)}] Importing selected resume: {path.name}")
            raw = ingestion.extract_text(path)
            if not raw.strip():
                raise ValueError(f"Resume has no extractable text: {path.name}")
            contacts = ingestion.extract_contacts(raw)
            structured = ingestion.parse_resume(raw)
            errors = ingestion.validate_resume_json(structured)
            if errors:
                raise ValueError(f"Resume {path.name} failed validation: {errors}")
            try:
                with connection.cursor() as cur:
                    cur.execute("""INSERT INTO public.candidate
                        (candidate_name, email, phone, resume_file_name, resume_hash,
                         raw_text, clean_text, structured_data)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING candidate_id""",
                        (contacts["name"], contacts["email"], contacts["phone"], path.name,
                         digest, raw, ingestion.clean_text(raw), Json(structured)))
                    cid = int(cur.fetchone()[0])
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        ids.append(cid)
    if len(set(ids)) != len(selected_files):
        raise ValueError("Some selected files have identical content. Select unique resumes.")
    print(f"[+] Selected cohort resolved: {len(ids)} resumes. No outside resumes included.")
    return ids


def score_selected_candidates(connection: Any, jd_id: int, candidate_ids: list[int]) -> list[dict]:
    """Same existing ATS factor and Gemini batch functions, restricted to candidate IDs."""
    if not candidate_ids:
        raise ValueError("Cannot score an empty selected cohort.")
    reset_gemini_failure_state()
    with connection.cursor() as cur:
        cur.execute("SELECT structured_data FROM public.job_description WHERE jd_id=%s", (jd_id,))
        jd_row = cur.fetchone()
        if not jd_row:
            raise ValueError(f"JD {jd_id} not found")
        cur.execute("""SELECT candidate_id, structured_data FROM public.candidate
                       WHERE candidate_id = ANY(%s) ORDER BY candidate_id""", (candidate_ids,))
        rows = cur.fetchall()
        cur.execute("""SELECT DISTINCT ON (candidate_id) candidate_id, llm_based_score
                       FROM public.ats_score WHERE jd_id=%s AND candidate_id=ANY(%s)
                         AND llm_based_score IS NOT NULL
                       ORDER BY candidate_id, computed_at DESC, id DESC""", (jd_id, candidate_ids))
        cached_rows = cur.fetchall()
    if len(rows) != len(candidate_ids):
        raise RuntimeError("One or more selected candidate IDs are missing from PostgreSQL.")
    jd_data = jd_row[0] if isinstance(jd_row[0], dict) else json.loads(jd_row[0] or '{}')
    if not jd_data:
        raise ValueError("Selected JD has no structured data.")
    parsed = [(int(cid), data if isinstance(data, dict) else json.loads(data or '{}')) for cid, data in rows]
    if any(not data for _, data in parsed):
        raise ValueError("A selected resume has no structured data; cannot score it.")
    refresh = os.getenv('RANKRESUME_REFRESH_LLM_SCORES', '').lower() in {'1','true','yes','on'}
    cached = {} if refresh else {int(cid): float(score) for cid, score in cached_rows}
    needs = [{'candidate_id': cid, 'structured_data': data} for cid, data in parsed if cid not in cached]
    batch = get_batch_gemini_evaluations(jd_data, needs) if needs else {}
    results = []
    for cid, data in parsed:
        item = batch.get(str(cid)) if cid not in cached else None
        llm_score = cached.get(cid) if cid in cached else (item['score'] if item else None)
        ats = ingestion.store_candidate_ats_score(
            connection, cid, jd_id, jd_data, data, llm_score, score_with_llm=False)
        results.append({'candidate_id': cid, 'jd_id': jd_id, 'ats_score': ats,
                        'llm_based_score': llm_score,
                        'scoring_mode': 'hybrid' if llm_score is not None else 'rule-only'})
    return results
