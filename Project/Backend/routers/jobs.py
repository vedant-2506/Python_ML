import asyncio
import tempfile
import uuid
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from ..core.database import connection, transaction
from ..core.security import current_company
from ..schemas.common import StatusUpdate
from ..services.ingestion_service import process_job
from ..services.ats_service import ranked_candidates

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _update_processing(job_id, **values):
    fields = {"stage": values.get("stage"), "message": values.get("message")}
    if "total_files" in values: fields["total_files"] = values["total_files"]
    if "processed" in values: fields["processed"] = values["processed"]
    if "failed" in values: fields["failed"] = values["failed"]
    assignments = [f"{k}=%s" for k,v in fields.items() if v is not None]
    params = [v for v in fields.values() if v is not None]
    if values.get("started"):
        assignments.append("started_at=NOW()")
    if values.get("finished"):
        assignments.append("finished_at=NOW()")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE processing_job SET " + ",".join(assignments) + " WHERE job_id=%s",
                        (*params, str(job_id)))


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    with destination.open("wb") as target:
        while chunk := await upload.read(1024 * 1024):
            target.write(chunk)


@router.post("")
async def create_job(background: BackgroundTasks, title: str = Form(...), jd_file: UploadFile = File(...),
                     resumes_zip: UploadFile = File(...), department: str | None = Form(None),
                     experience_level: str | None = Form(None), positions: int | None = Form(None),
                     skills: str | None = Form(None), user=Depends(current_company)):
    if Path(jd_file.filename or "").suffix.lower() not in {".pdf", ".doc", ".docx"}:
        raise HTTPException(415, "JD must be PDF, DOC, or DOCX")
    if Path(resumes_zip.filename or "").suffix.lower() != ".zip":
        raise HTTPException(415, "Resumes upload must be a ZIP")
    root = Path(tempfile.mkdtemp(prefix="rankresume-upload-"))
    jd_path, zip_path = root / Path(jd_file.filename).name, root / Path(resumes_zip.filename).name
    await _save_upload(jd_file, jd_path)
    await _save_upload(resumes_zip, zip_path)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO job_description(job_title,jd_file_name,comp_id,department,
                         experience_level,positions,status,structured_data)
                         VALUES(%s,%s,%s,%s,%s,%s,'Active','{}') RETURNING jd_id""",
                        (title, jd_path.name, user["comp_id"], department, experience_level, positions))
            jd_id = cur.fetchone()[0]
            job_id = uuid.uuid4()
            cur.execute("INSERT INTO processing_job(job_id,jd_id,comp_id,stage,message) VALUES(%s,%s,%s,'uploading','Queued')",
                        (str(job_id), jd_id, user["comp_id"]))
    background.add_task(_run_job, jd_id, user["comp_id"], title, jd_path, zip_path, job_id, root)
    return {"jd_id": jd_id, "job_id": str(job_id)}


def _run_job(jd_id, comp_id, title, jd_path, zip_path, job_id, root):
    try:
        _update_processing(job_id, started=True, stage="extracting", message="Processing started")
        process_job(jd_id, comp_id, title, jd_path, zip_path,
                    lambda **values: _update_processing(job_id, **values))
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


@router.get("")
def list_jobs(search: str | None = None, status: str | None = None,
              page: int = Query(1, ge=1), user=Depends(current_company)):
    with connection() as conn, conn.cursor() as cur:
        clauses, params = ["comp_id=%s"], [user["comp_id"]]
        if search: clauses.append("job_title ILIKE %s"); params.append(f"%{search}%")
        if status: clauses.append("status=%s"); params.append(status)
        cur.execute("SELECT jd_id,job_title,status,positions,created_at FROM job_description WHERE " +
                    " AND ".join(clauses) + " ORDER BY created_at DESC LIMIT 50 OFFSET %s", (*params,(page-1)*50))
        rows = cur.fetchall()
    return {"items": [{"jd_id":r[0],"title":r[1],"status":r[2],"positions":r[3],"created_at":r[4]} for r in rows],
            "page": page}


def _owned_job(jd_id, comp_id):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT jd_id,job_title,status,department,experience_level,positions,created_at FROM job_description WHERE jd_id=%s AND comp_id=%s",
                    (jd_id, comp_id))
        row = cur.fetchone()
    if not row: raise HTTPException(404, "Job not found")
    return row


@router.get("/{jd_id}")
def job_detail(jd_id: int, user=Depends(current_company)):
    r = _owned_job(jd_id,user["comp_id"])
    return dict(zip(["jd_id","title","status","department","experience_level","positions","created_at"],r))


@router.patch("/{jd_id}/status")
def job_status(jd_id: int, payload: StatusUpdate, user=Depends(current_company)):
    _owned_job(jd_id,user["comp_id"])
    if payload.status not in {"Active","Inactive"}: raise HTTPException(400,"Status must be Active or Inactive")
    with transaction() as conn, conn.cursor() as cur: cur.execute("UPDATE job_description SET status=%s WHERE jd_id=%s",(payload.status,jd_id))
    return {"jd_id": jd_id, "status": payload.status}


@router.delete("/{jd_id}")
def delete_job(jd_id: int, user=Depends(current_company)):
    _owned_job(jd_id,user["comp_id"])
    with transaction() as conn, conn.cursor() as cur: cur.execute("UPDATE job_description SET status='Inactive' WHERE jd_id=%s",(jd_id,))
    return {"deleted": True}


@router.get("/{jd_id}/processing-status")
def processing_status(jd_id: int, user=Depends(current_company)):
    _owned_job(jd_id,user["comp_id"])
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT job_id,stage,total_files,processed,failed,message,started_at,finished_at FROM processing_job WHERE jd_id=%s ORDER BY started_at DESC NULLS LAST LIMIT 1",(jd_id,))
        r=cur.fetchone()
    if not r: raise HTTPException(404,"Processing job not found")
    return dict(zip(["job_id","stage","total_files","processed","failed","message","started_at","finished_at"],r))


@router.get("/{jd_id}/candidates")
def candidates(jd_id:int, search:str|None=None, page:int=Query(1,ge=1), user=Depends(current_company)):
    _owned_job(jd_id,user["comp_id"])
    with connection() as conn:
        rows=ranked_candidates(conn,jd_id)
        if search: rows=[r for r in rows if search.lower() in (r["candidate_name"] or "").lower()]
    return {"items": rows[(page-1)*50:page*50], "page":page, "total":len(rows)}
