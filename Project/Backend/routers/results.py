import csv, io
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from ..core.database import connection
from ..core.security import current_company
from ..routers.jobs import _owned_job
router=APIRouter(prefix="/api/jobs",tags=["results"])


def _rows(jd_id, comp_id):
    _owned_job(jd_id,comp_id)
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.candidate_id,c.candidate_name,c.email,c.ats_score,
                              r.first_six_average,r.last_four_average,r.final_result,r.calculated_at
                       FROM final_evaluation_result r JOIN candidate c ON c.candidate_id=r.candidate_id
                       WHERE r.jd_id=%s ORDER BY r.final_result DESC NULLS LAST""",(jd_id,))
        return cur.fetchall()


@router.get("/{jd_id}/results")
def results(jd_id:int,user=Depends(current_company)):
    return {"items":[dict(zip(["candidate_id","candidate_name","email","ats_score","exam_score","stage2_score","final_mark","calculated_at"],r))
                     for r in _rows(jd_id,user["comp_id"])]}


@router.get("/{jd_id}/results/export")
def export_results(jd_id:int,user=Depends(current_company)):
    output=io.StringIO(); writer=csv.writer(output)
    writer.writerow(["candidate_id","candidate_name","email","ats_score","exam_score","stage2_score","final_mark","calculated_at"])
    writer.writerows(_rows(jd_id,user["comp_id"])); output.seek(0)
    return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",
                             headers={"Content-Disposition":f"attachment; filename=job-{jd_id}-results.csv"})
