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

## Windows setup with an existing database

From the project root, run:

```powershell
.\setup_windows.ps1
```

The script reuses `.venv`, preserves an existing `Backend/.env`, and creates
one from the ignored project `.env` only when needed. It applies only the
additive backend migrations and runs dependency and compilation checks. It
does not create or alter PostgreSQL roles, reset tables, seed data, or run the
bulk ingestion pipeline. PostgreSQL must already be running, and the existing
database settings must point to `rankresume`.

The migration is additive only. It adds company ownership, job processing,
candidate-job links, invitations, integrity telemetry, typing statistics and
draft answers. Candidate APIs never expose reference answers or evaluation
fields. In production, sending from `@rankresume.com` requires the domain's
SMTP service and correctly configured SPF/DKIM.

The existing modules remain outside `Backend/` and are imported from the
project root. Their `RANKRESUME_DB_*`, `GEMINI_API_KEY`, and `GROQ_*` settings
are populated from `Backend/.env` at application startup.

The backend also reads the project-root `.env` when `Backend/.env` is absent.
Database settings accept either the `DB_*` names in `Backend/.env.example` or
the legacy `RANKRESUME_DB_*` names used by the root `.env`; process environment
variables continue to take precedence.
