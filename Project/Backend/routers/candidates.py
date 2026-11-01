from fastapi import APIRouter, Depends, HTTPException, Query
from ..core.database import connection
from ..core.security import current_company
router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.get("/{candidate_id}")
def candidate_detail(candidate_id: int, jd_id: int | None = Query(None), user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.candidate_id,c.candidate_name,c.email,c.phone,c.structured_data,
                              COALESCE(a.ats_score,c.ats_score),c.final_score
                       FROM candidate c
                       LEFT JOIN LATERAL (
                           SELECT CASE WHEN s.llm_based_score IS NULL THEN s.rule_based_score
                                       ELSE .60*s.rule_based_score+.40*s.llm_based_score END ats_score
                           FROM ats_score s JOIN job_description j ON j.jd_id=s.jd_id
                           WHERE s.candidate_id=c.candidate_id AND j.comp_id=%s
                             AND (%s IS NULL OR s.jd_id=%s)
                           ORDER BY s.computed_at DESC NULLS LAST LIMIT 1
                       ) a ON TRUE
                       WHERE c.candidate_id=%s AND c.comp_id=%s""",
                    (user["comp_id"], jd_id, jd_id, candidate_id, user["comp_id"]))
        row=cur.fetchone()
    if not row: raise HTTPException(404,"Candidate not found")
    return dict(zip(["candidate_id","name","email","phone","structured_data","ats_score","final_score"],row))
