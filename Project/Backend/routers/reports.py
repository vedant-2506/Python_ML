from fastapi import APIRouter, Depends, Query
from ..core.database import connection
from ..core.security import current_company
router=APIRouter(prefix="/api/reports",tags=["reports"])


@router.get("/summary")
def report_summary(range: str = Query("30d"), user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*), coalesce(avg(ats_score),0), coalesce(avg(final_score),0)
                       FROM candidate WHERE comp_id=%s""",(user["comp_id"],))
        count,ats,final=cur.fetchone()
    return {"range":range,"candidates":count,"average_ats":round(float(ats),2),"average_final":round(float(final),2)}
