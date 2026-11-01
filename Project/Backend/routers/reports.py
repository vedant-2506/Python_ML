from fastapi import APIRouter, Depends, Query
from ..core.database import connection
from ..core.security import current_company
router=APIRouter(prefix="/api/reports",tags=["reports"])


@router.get("/summary")
def report_summary(range: str = Query("30d"), user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(DISTINCT jc.candidate_id), coalesce(avg(a.score),0)
                       FROM job_candidate jc JOIN job_description j ON j.jd_id=jc.jd_id
                       LEFT JOIN LATERAL (
                         SELECT CASE WHEN s.llm_based_score IS NULL THEN s.rule_based_score
                                     ELSE .60*s.rule_based_score+.40*s.llm_based_score END score
                         FROM ats_score s WHERE s.jd_id=jc.jd_id AND s.candidate_id=jc.candidate_id
                         ORDER BY s.computed_at DESC NULLS LAST LIMIT 1
                       ) a ON TRUE
                       WHERE j.comp_id=%s AND (j.status IS NULL OR j.status NOT IN ('Inactive','Closed','Archived'))""",
                    (user["comp_id"],))
        count, ats = cur.fetchone()
        cur.execute("""SELECT coalesce(avg(r.final_result),0)
                       FROM final_evaluation_result r JOIN job_description j ON j.jd_id=r.jd_id
                       WHERE j.comp_id=%s""", (user["comp_id"],))
        final = cur.fetchone()[0]
        cur.execute("""SELECT width_bucket(score,0,100,5),count(*) FROM (
                         SELECT CASE WHEN a.llm_based_score IS NULL THEN a.rule_based_score
                                     ELSE .60*a.rule_based_score+.40*a.llm_based_score END score
                         FROM ats_score a JOIN job_description j ON j.jd_id=a.jd_id
                         WHERE j.comp_id=%s AND (j.status IS NULL OR j.status NOT IN ('Inactive','Closed','Archived'))
                       ) scores WHERE score IS NOT NULL GROUP BY 1 ORDER BY 1""", (user["comp_id"],))
        distribution = [0] * 5
        for bucket, total in cur.fetchall():
            if 1 <= bucket <= 5:
                distribution[bucket - 1] = total
    return {"range": range, "candidates": count, "average_ats": round(float(ats), 2),
            "average_final": round(float(final), 2), "ats_distribution": distribution}
