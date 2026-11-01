from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .core.config import get_settings
from .core.database import init_pool, close_pool
from .core.logging_config import configure_logging
from .routers import auth, dashboard, jobs, candidates, exam_admin, exam_candidate, results, reports
from .services.mail_service import send_email


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    try:
        init_pool()
    except Exception:
        # Health endpoint remains importable when a developer has not started PostgreSQL.
        pass
    yield
    close_pool()


app = FastAPI(title="RankResume API", version="1.0", lifespan=lifespan)
s = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=[s.frontend_origin], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
for router in (auth.router, dashboard.router, jobs.router, candidates.router,
               exam_admin.router, exam_candidate.router, results.router, reports.router):
    app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/dev/test-email")
def test_email():
    if s.env != "dev":
        raise HTTPException(404, "Not found")
    return {"enabled": True, "message": "Use the configured SMTP capture server to send a real invitation."}
