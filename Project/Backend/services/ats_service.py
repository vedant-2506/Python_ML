def ranked_candidates(conn, jd_id: int) -> list[dict]:
    """Rank ONLY the candidates linked to this job.
    Final ATS = 0.60 * rule + 0.40 * LLM (rule only if no LLM score), read from the
    per-job ats_score row, so scores for different jobs never overwrite each other.
    Equal scores share a rank (1, 2, 2, 4)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (c.candidate_id)
                   c.candidate_id, c.candidate_name, c.email,
                   CASE WHEN a.llm_based_score IS NULL THEN a.rule_based_score
                        ELSE 0.60 * a.rule_based_score + 0.40 * a.llm_based_score END AS final_score
            FROM job_candidate jc
            JOIN candidate c ON c.candidate_id = jc.candidate_id
            JOIN ats_score a ON a.candidate_id = jc.candidate_id AND a.jd_id = jc.jd_id
            WHERE jc.jd_id = %s
            ORDER BY c.candidate_id, a.computed_at DESC
        """, (jd_id,))
        rows = cur.fetchall()
    rows.sort(key=lambda r: (-(float(r[3]) if r[3] is not None else -1), r[0]))
    out, prev, rank = [], None, 0
    for i, (cid, name, email, score) in enumerate(rows, start=1):
        score = round(float(score), 2) if score is not None else None
        if score != prev:
            rank = i
            prev = score
        out.append({"rank": rank, "candidate_id": cid, "candidate_name": name,
                    "email": email, "ats_score": score})
    return out



def _as_dict(value) -> dict:
    import json
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        return json.loads(value)
    return {}


def score_job_candidates(conn, jd_id: int) -> int:
    """Score ONLY the candidates linked to this job, reusing DB_Store's own scoring
    functions (same logic as score_all_candidates, minus the other jobs' candidates)."""
    from DB_Store import rankresume_pipeline as pipeline
    pipeline.reset_gemini_failure_state()
    with conn.cursor() as cur:
        cur.execute("SELECT structured_data FROM job_description WHERE jd_id=%s", (jd_id,))
        row = cur.fetchone()
        jd_data = _as_dict(row[0]) if row else {}
        cur.execute("""SELECT c.candidate_id, c.structured_data FROM candidate c
                       JOIN job_candidate jc ON jc.candidate_id = c.candidate_id
                       WHERE jc.jd_id = %s ORDER BY c.candidate_id""", (jd_id,))
        candidates = [(cid, _as_dict(data)) for cid, data in cur.fetchall()]
        cur.execute("""SELECT candidate_id, llm_based_score FROM ats_score
                       WHERE jd_id = %s AND llm_based_score IS NOT NULL""", (jd_id,))
        cached = {cid: float(score) for cid, score in cur.fetchall()}
    candidates = [(cid, data) for cid, data in candidates if jd_data and data]
    pending = [{"candidate_id": cid, "structured_data": data}
               for cid, data in candidates if cid not in cached]
    batch_scores = pipeline.get_batch_gemini_evaluations(jd_data, pending) if pending else {}
    for cid, data in candidates:
        if cid in cached:
            llm_score = cached[cid]
        else:
            result = batch_scores.get(str(cid))
            llm_score = result["score"] if result else None
        pipeline.store_candidate_ats_score(conn, cid, jd_id, jd_data, data, llm_score,
                                           score_with_llm=False)
    return len(candidates)