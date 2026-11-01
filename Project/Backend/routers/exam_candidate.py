from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request
from ..core.database import connection, transaction
from ..schemas.common import AnswerRequest, EventsRequest
from ..services.exam_service import resolve_token, public_questions, generate_stage2
from ..services.evaluation_service import save_and_evaluate, calculate_final

router=APIRouter(prefix="/api/exam",tags=["candidate exam"])


def _ctx(token, allow_completed=False):
    try: return resolve_token(token)
    except LookupError as exc: raise HTTPException(404,str(exc)) from exc
    except TimeoutError as exc: raise HTTPException(410,str(exc)) from exc
    except PermissionError as exc:
        if allow_completed: raise HTTPException(409,str(exc)) from exc
        raise HTTPException(409,str(exc)) from exc


def _expire(ctx):
    if ctx["ends_at"] and ctx["ends_at"] <= datetime.now(timezone.utc):
        with transaction() as conn, conn.cursor() as cur:
            cur.execute("UPDATE exam_sessions SET status='COMPLETED' WHERE exam_id=%s AND status<>'COMPLETED'",(ctx["exam_id"],))
            cur.execute("UPDATE exam_invitation SET status='COMPLETED' WHERE invitation_id=%s",(ctx["invitation_id"],))
        raise HTTPException(410,"Exam time has expired")


@router.get("/{token}/info")
def info(token:str):
    ctx=_ctx(token)
    with connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT j.job_title,c.company_name,ca.candidate_name
                       FROM job_description j JOIN company c ON c.comp_id=j.comp_id
                       JOIN candidate ca ON ca.candidate_id=%s
                       JOIN job_candidate jc ON jc.candidate_id=ca.candidate_id AND jc.jd_id=j.jd_id
                       WHERE j.jd_id=%s""",(ctx["candidate_id"],ctx["jd_id"]))
        row=cur.fetchone()
    if not row:
        raise HTTPException(404, "This invitation is not valid for the selected job and candidate")
    return {"job_title":row[0],"company_name":row[1],"candidate_name":row[2],
            "rules":["30 minutes","10 questions","one attempt","no paste","stay on this tab"],
            "status":ctx["invitation_status"]}


@router.post("/{token}/start")
def start(token:str):
    ctx=_ctx(token); now=datetime.utcnow(); now_aware=now.replace(tzinfo=timezone.utc)
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM exam_sessions WHERE exam_id=%s FOR UPDATE",(ctx["exam_id"],))
        status=cur.fetchone()[0]
        if status=="STAGE1_READY":
            cur.execute("UPDATE exam_sessions SET started_at=%s,ends_at=%s WHERE exam_id=%s",
                        (now,now+timedelta(minutes=30),ctx["exam_id"]))
            cur.execute("UPDATE exam_invitation SET opened_at=COALESCE(opened_at,NOW()),status='STARTED' WHERE invitation_id=%s",(ctx["invitation_id"],))
    return {"started":True,"ends_at":(now_aware+timedelta(minutes=30)).isoformat()}


def _state(ctx):
    _expire(ctx)
    with connection() as conn, conn.cursor() as cur:
        questions=public_questions(conn,ctx["exam_id"])
        cur.execute("""SELECT question_order,text FROM answer_draft WHERE exam_id=%s AND candidate_id=%s""",(ctx["exam_id"],ctx["candidate_id"]))
        drafts={r[0]:r[1] for r in cur.fetchall()}
    stage=2 if ctx["exam_status"] in ("STAGE2_READY","COMPLETED") else 1
    visible=[q for q in questions if q["stage"]==1 or (stage==2 and q["stage"]==2)]
    now=datetime.now(timezone.utc)
    return {"server_time":now.isoformat(),"ends_at":ctx["ends_at"].isoformat() if ctx["ends_at"] else None,
            "remaining_seconds":max(0,int((ctx["ends_at"]-now).total_seconds())) if ctx["ends_at"] else 1800,
            "stage":stage,"status":ctx["exam_status"],"questions":visible,
            "drafts":drafts}


@router.get("/{token}/state")
def state(token:str): return _state(_ctx(token))


@router.put("/{token}/answers/{order}")
def draft(token:str,order:int,payload:AnswerRequest):
    ctx=_ctx(token); _expire(ctx)
    if not 1<=order<=10: raise HTTPException(422,"Question order must be 1..10")
    if order>6 and ctx["exam_status"]!="STAGE2_READY": raise HTTPException(409,"Stage 2 is not ready")
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM question_exam WHERE exam_id=%s AND question_order=%s",(ctx["exam_id"],order))
        if not cur.fetchone(): raise HTTPException(404,"Question not found")
        cur.execute("""INSERT INTO answer_draft(exam_id,candidate_id,question_order,text) VALUES(%s,%s,%s,%s)
                       ON CONFLICT(exam_id,candidate_id,question_order) DO UPDATE SET text=EXCLUDED.text,updated_at=NOW()""",
                    (ctx["exam_id"],ctx["candidate_id"],order,payload.text.strip()))
    return {"saved":True,"order":order}


def _submit_stage(ctx, first:int,last:int,source:str):
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT question_order,text FROM answer_draft WHERE exam_id=%s AND candidate_id=%s AND question_order BETWEEN %s AND %s",
                    (ctx["exam_id"],ctx["candidate_id"],first,last))
        answers={r[0]:r[1] for r in cur.fetchall()}
        if first == 1:
            cur.execute("SELECT question_order,question_id FROM question_exam WHERE exam_id=%s AND question_order BETWEEN %s AND %s ORDER BY question_order",
                        (ctx["exam_id"],first,last))
        else:
            cur.execute("SELECT question_order+6,ai_question_exam_id FROM ai_question_exam WHERE exam_id=%s AND question_order BETWEEN 1 AND 4 ORDER BY question_order",
                        (ctx["exam_id"],))
        questions=cur.fetchall()
    for order,qid in questions:
        save_and_evaluate(ctx["exam_id"],ctx["jd_id"],ctx["candidate_id"],qid,answers.get(order,""),source,1 if first==1 else 2)


@router.post("/{token}/submit-stage1")
def submit_stage1(token:str):
    ctx=_ctx(token); _expire(ctx)
    if ctx["exam_status"]!="STAGE1_READY": raise HTTPException(409,"Stage 1 has already been submitted")
    started=datetime.now(timezone.utc)
    _submit_stage(ctx,1,6,"Question Bank")
    try: generate_stage2(ctx["exam_id"],ctx["jd_id"],ctx["candidate_id"])
    except Exception as exc: raise HTTPException(503,"Stage 2 is temporarily unavailable; retry-stage2 may be used") from exc
    elapsed=(datetime.now(timezone.utc)-started).total_seconds()
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("UPDATE exam_sessions SET status='STAGE2_READY',ends_at=ends_at+make_interval(secs=>%s) WHERE exam_id=%s",(elapsed,ctx["exam_id"]))
        cur.execute("UPDATE exam_invitation SET status='STAGE1_SUBMITTED' WHERE invitation_id=%s",(ctx["invitation_id"],))
    return {"status":"STAGE2_READY"}


@router.get("/{token}/stage2-status")
def stage2_status(token:str):
    ctx=_ctx(token)
    return {"status":"ready" if ctx["exam_status"]=="STAGE2_READY" else "preparing" if ctx["exam_status"]=="STAGE1_SUBMITTED" else "error" if ctx["exam_status"]=="ERROR" else "preparing"}


@router.post("/{token}/retry-stage2")
def retry_stage2(token:str):
    ctx=_ctx(token)
    try: generate_stage2(ctx["exam_id"],ctx["jd_id"],ctx["candidate_id"])
    except Exception as exc: raise HTTPException(503,"Stage 2 generation failed; try again") from exc
    with transaction() as conn, conn.cursor() as cur: cur.execute("UPDATE exam_sessions SET status='STAGE2_READY' WHERE exam_id=%s",(ctx["exam_id"],))
    return {"status":"ready"}


@router.post("/{token}/submit")
def submit(token:str):
    ctx=_ctx(token); _expire(ctx)
    if ctx["exam_status"]!="STAGE2_READY": raise HTTPException(409,"Stage 2 is not ready")
    _submit_stage(ctx,7,10,"groq_llm")
    calculate_final(ctx["exam_id"],ctx["candidate_id"],ctx["jd_id"])
    with transaction() as conn, conn.cursor() as cur:
        cur.execute("UPDATE exam_sessions SET status='COMPLETED' WHERE exam_id=%s",(ctx["exam_id"],))
        cur.execute("UPDATE exam_invitation SET status='COMPLETED' WHERE invitation_id=%s",(ctx["invitation_id"],))
    return {"submitted":True}


@router.post("/{token}/events")
def events(token:str,payload:EventsRequest):
    ctx=_ctx(token)
    with transaction() as conn, conn.cursor() as cur:
        for event in payload.events:
            cur.execute("""INSERT INTO exam_integrity_event(exam_id,candidate_id,question_order,event_type,meta)
                           VALUES(%s,%s,%s,%s,%s)""",(ctx["exam_id"],ctx["candidate_id"],event.question_order,event.event_type, event.meta))
        for stat in payload.typing_stats:
            cur.execute("""INSERT INTO answer_typing_stats(exam_id,candidate_id,question_order,keystrokes,backspaces,paste_attempts,avg_interkey_ms,first_key_delay_ms,total_typing_ms)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(exam_id,candidate_id,question_order) DO UPDATE SET keystrokes=EXCLUDED.keystrokes,backspaces=EXCLUDED.backspaces,paste_attempts=EXCLUDED.paste_attempts,avg_interkey_ms=EXCLUDED.avg_interkey_ms,first_key_delay_ms=EXCLUDED.first_key_delay_ms,total_typing_ms=EXCLUDED.total_typing_ms""",
                        (ctx["exam_id"],ctx["candidate_id"],stat.get("question_order"),stat.get("keystrokes",0),stat.get("backspaces",0),stat.get("paste_attempts",0),stat.get("avg_interkey_ms"),stat.get("first_key_delay_ms"),stat.get("total_typing_ms")))
    return {"recorded":True}
