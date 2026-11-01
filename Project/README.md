# RankResume

## Run the product locally

From `Project/`:

1. `psql -h localhost -U root -d rankresume -f Backend/sql/001_backend_tables.sql`
2. `python3 -m pip install -r Backend/requirements.txt` (use a virtual environment on externally-managed Python installations)
3. Start a local mail catcher: `python -m aiosmtpd -n -l localhost:1025`
4. `uvicorn Backend.main:app --reload --port 8000`
5. In another terminal: `cd Frontend && python -m http.server 5500`

Open `http://localhost:5500/html/login.html`. Exam links use
`http://localhost:5500/html/exam-start.html?token=...`.

The migration is additive. Existing AI/ML modules remain in their original
directories and are imported by the backend from the project root. For real
mail from `@rankresume.com`, configure that domain's SMTP provider and SPF/DKIM.
