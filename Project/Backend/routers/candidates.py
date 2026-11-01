from fastapi import APIRouter, Depends, HTTPException
from ..core.database import connection
from ..core.security import current_company
router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.get("/{candidate_id}")
def candidate_detail(candidate_id: int, user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.candidate_id,c.candidate_name,c.email,c.phone,c.structured_data,c.ats_score,c.final_score
                       FROM candidate c WHERE c.candidate_id=%s AND c.comp_id=%s""", (candidate_id,user["comp_id"]))
        row=cur.fetchone()
    if not row: raise HTTPException(404,"Candidate not found")
    return dict(zip(["candidate_id","name","email","phone","structured_data","ats_score","final_score"],row))
