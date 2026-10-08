# RankResume Core Question Bank

This phase owns only stable core computer-science questions. It does not modify ATS, resume, JD, or candidate-ranking behavior.

## Files

- `question_generator.py`: prints the planned distribution, creates the table, and restartably refreshes/inserts the catalog.
- `question_validator.py`: audits PostgreSQL, writes `question_bank_report.json`, and exports the data-bearing `question_bank.sql`.
- `database.py`: PostgreSQL connection and transaction helpers.
- `question_deduplicator.py`: normalized exact and cached shingle-based near-duplicate checks.
- `bankresume_schema.sql`: stable schema input used by the generator.
- `question_bank.sql`: generated, independently reloadable schema plus COPY data export.

## Run

From `Question_Generation` with the project virtual environment active:

```bash
../.venv/bin/python question_generator.py
../.venv/bin/python question_validator.py
```

The default connection is `localhost:5432`, database `rankresume`, user `root`, password `root`. `RANKRESUME_DB_HOST`, `RANKRESUME_DB_PORT`, `RANKRESUME_DB_NAME`, `RANKRESUME_DB_USER`, and `RANKRESUME_DB_PASSWORD` override these values.

Generation is restartable and uses `question_hash` with `ON CONFLICT` protection. The SQL export is guarded to run against `rankresume`; for a reload test, use a temporary database and adapt only that guard while leaving production untouched.

The current catalog target is 5,194 rows: 250 per core subject and 121 per programming language. The committed database audit report is written to `question_bank_report.json`.
