# RankResume Backend

## Run

From the project root:

```bash
cp Backend/.env.example Backend/.env
psql -h localhost -U root -d rankresume -f Backend/sql/001_backend_tables.sql
python -m pip install -r Backend/requirements.txt
python -m aiosmtpd -n -l localhost:1025
uvicorn Backend.main:app --reload --port 8000
cd Frontend && python -m http.server 5500
```

The migration is additive only. It adds company ownership, job processing,
candidate-job links, invitations, integrity telemetry, typing statistics and
draft answers. Candidate APIs never expose reference answers or evaluation
fields. In production, sending from `@rankresume.com` requires the domain's
SMTP service and correctly configured SPF/DKIM.

The existing modules remain outside `Backend/` and are imported from the
project root. Their `RANKRESUME_DB_*`, `GEMINI_API_KEY`, and `GROQ_*` settings
are populated from `Backend/.env` at application startup.
