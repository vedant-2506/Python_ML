# RankResume Question Selection

This folder implements the first exam stage: selecting six snapshots from the
existing `bankresume` Question Bank. It does not regenerate the Question Bank,
generate the four later LLM questions, or change answer checking.

## Files

- `question_selector.py` normalizes and classifies JD skills, maps Core Skills
  to Question Bank categories, and selects 3 Easy, 2 Medium, and 1 Hard row.
- `exam_workflow.py` provides transactional, locked, idempotent session lookup
  and Stage 1 storage. `select_questions(jd_id, refresh=False)` is the normal
  entry point; use `refresh=True` only for an intentional replacement.
- `db_helper.py` reuses the project's PostgreSQL connection configuration.
- `selection_generation_schema.sql` defines the exam snapshot tables and
  Stage 1 uniqueness indexes without dropping existing data.
- `Question_Selection_Generation.ipynb` is the Stage 1-only execution notebook.
- `tests/test_question_selection.py` contains unit tests for classification and
  selection validation.

## Prerequisites and configuration

Use Python 3.10 or newer and install the project's dependencies, including
`psycopg2-binary` and Jupyter. From the repository root:

```bash
python -m pip install -r requirements.txt
```

The existing connection helper reads these environment variables; defaults are
shown for local development only and are not stored in source or notebooks:

```bash
export RANKRESUME_DB_HOST=localhost
export RANKRESUME_DB_PORT=5432
export RANKRESUME_DB_NAME=rankresume
export RANKRESUME_DB_USER=root
export RANKRESUME_DB_PASSWORD='your-local-password'
```

Do not commit a password or print it in notebook output. A `.env` file may be
used only if the collaborator's existing environment loader is configured to
load it.

## Database setup and verification

The PostgreSQL database must contain the existing `job_description` and
`bankresume` tables. Apply the additive schema file from `rankresume`:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f Question_Selection_Generation/selection_generation_schema.sql
```

If `DATABASE_URL` is not used, supply `-h`, `-p`, `-U`, and `-d` explicitly.
The file does not drop, truncate, or recreate `exam_sessions`,
`question_exam`, or Question Bank data. On an existing database it adds only
the missing Stage 1 uniqueness indexes when historical rows do not conflict.

Verify the Question Bank before running selection:

```sql
SELECT COUNT(*) FROM bankresume;
SELECT subject, topic, difficulty, COUNT(*)
FROM bankresume
GROUP BY subject, topic, difficulty
ORDER BY subject, topic, difficulty;
```

The current development database contains 5,194 Question Bank rows. A
different count is not automatically an error, but investigate schema or
migration differences before selection.

## Running the notebook

Open `Question_Selection_Generation.ipynb`, set `JD_ID` in the Stage 1 cell,
and run all cells. It loads the JD, displays Core/Changeable/unclassified
skills, selects or reuses six rows, verifies the stored rows, and prints the
database validation summary. It intentionally stops before the later LLM
stage.

The Python API can be used without the notebook:

```python
from Question_Selection_Generation.db_helper import transaction
from Question_Selection_Generation.exam_workflow import select_questions

with transaction() as connection:
    result = select_questions(connection, jd_id=5, refresh=False)
print(result.exam_id, result.reused, result.classification.unclassified_skills)
```

Normal reruns lock the JD, reuse its newest valid exam session and six Stage 1
rows, and do not create another session. A valid selection is never randomly
replaced during a normal rerun.

An explicit refresh is separate:

```python
with transaction() as connection:
    result = select_questions(connection, jd_id=5, refresh=True)
```

Refresh preserves the session and deletes only its Stage 1 rows. It is refused
when the session is not `STAGE1_READY` or `answer_store` contains a submitted
answer for those questions. This protects candidate answers and exam
integrity. It never removes rows for another JD.

## Classification policy

Core Skills are stable fundamentals and practices, including OOP, data
structures, algorithms, DBMS, SQL, operating systems, networks, architecture,
software engineering, SDLC, programming languages, Git/version control,
testing, and system design fundamentals. Changeable Skills include frameworks,
libraries, platforms, cloud technologies, containers, and ML tools such as
Spring Boot, React, Docker, Kubernetes, AWS, Azure, Kafka, Redis, and
TensorFlow.

Names are compared after trimming, whitespace normalization, case folding, and
explicit alias normalization. Programming-language names use exact aliases:
`C`, `C++`, `C#`, `Java`, and `JavaScript` cannot match one another.
Unknown skills are returned in `unclassified_skills` for review rather than
silently discarded. The Question Bank query uses exact normalized subject or
topic category names, not arbitrary substring matching.

## Selection rules and verification

Every new Stage 1 snapshot contains six unique Question Bank IDs and normalized
question texts, with orders 1 through 6 and difficulty distribution 3 Easy,
2 Medium, and 1 Hard. Insufficient candidates cause a clear error and no
partial insert is committed.

Useful checks:

```sql
SELECT exam_id, jd_id, stage, COUNT(*) AS question_count
FROM question_exam
WHERE stage = 1
GROUP BY exam_id, jd_id, stage
ORDER BY jd_id, exam_id;

SELECT exam_id, jd_id, difficulty, COUNT(*) AS question_count
FROM question_exam
WHERE stage = 1
GROUP BY exam_id, jd_id, difficulty
ORDER BY jd_id, exam_id, difficulty;

SELECT exam_id, question_id, COUNT(*) AS occurrences
FROM question_exam
WHERE stage = 1 AND question_id IS NOT NULL
GROUP BY exam_id, question_id
HAVING COUNT(*) > 1;

SELECT exam_id, question_order, COUNT(*) AS occurrences
FROM question_exam
WHERE stage = 1
GROUP BY exam_id, question_order
HAVING COUNT(*) > 1;

SELECT exam_id, jd_id, question_order, source, question_id,
       question, difficulty, skill
FROM question_exam
WHERE stage = 1
ORDER BY jd_id, exam_id, question_order;
```

Historical sessions are reported separately by `exam_id`; do not aggregate
them as one current exam.

## Tests and troubleshooting

Run focused tests from the repository root:

```bash
python -m unittest discover -s Project/Question_Selection_Generation/tests -p 'test_*.py'
```

For connection errors, verify PostgreSQL is running, the database/user exist,
and the `RANKRESUME_DB_*` variables are set in the same shell as Jupyter. For
missing-table or column errors, inspect `information_schema.columns` and
apply the schema files in `Question_Generation` and this folder in the
project's normal order. For foreign-key errors during refresh, inspect
`answer_store` and the session status; do not delete the exam session.

To reproduce locally, clone the repository, install the same Python
dependencies, create or restore the `rankresume` database, load the unchanged
Question Bank, set the environment variables, apply the additive schema, run
the unit tests, and execute the notebook with a JD that has six eligible
questions. The completed feature is Stage 1 selection and safe persistence;
four LLM-generated Stage 2 questions remain a later phase.
