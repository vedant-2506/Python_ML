# RankResume — Question Selection & Generation

## 1. Overview

The `Question_Selection_Generation` folder is responsible for selecting technical interview questions for a candidate based on the skills extracted from a Job Description (JD).

This folder connects the existing Question Bank with the exam workflow in RankResume.

The Question Bank already contains approximately **5,194 questions and answers** in the PostgreSQL `rankresume` database. This phase selects six suitable questions from that existing bank and stores them in the `question_exam` table.

The current implementation focuses on **Stage 1: Question Bank Selection**.

The generation of four additional questions using a local LLM is a later phase and is not part of the current execution workflow.

### Main objectives

- Read the expected skills from a JD.
- Classify skills into Core Skills and Changeable Skills.
- Match Core Skills with relevant Question Bank subjects and topics.
- Select six unique technical questions.
- Maintain the required difficulty distribution.
- Store the selected questions in PostgreSQL.
- Prevent duplicate exam sessions and question sets when the code is rerun.
- Support intentional question refresh when it is safe.
- Provide a reproducible setup for team members.

---

## 2. Position in the RankResume Project

The overall project workflow is:

```text
DB_Store
   |
   | Resume and JD processing
   v
JD / Resume JSON
   |
   v
ATS_calculation
   |
   | ATS scoring and candidate evaluation
   v
Question_Selection_Generation
   |
   | Read JD expected_skills
   | Classify Core and Changeable Skills
   | Select 6 questions from bankresume
   v
exam_sessions
   |
   v
question_exam
   |
   | Candidate answers are collected
   v
Answer_Checking
   |
   | Evaluate the first six answers
   v
Later stage: Generate 4 LLM questions
   |
   v
Final exam evaluation
```

The diagram describes the intended application flow. Exact table relationships and execution order must follow the current database schema and implementation.

---

## 3. Project Directory Structure

The overall project root is:

```text
/home/vedant-2506/Desktop/Python_ML/Project
```

The current module is:

```text
Project/
└── Question_Selection_Generation/
    ├── Question_Selection_Generation.ipynb
    ├── question_selector.py
    ├── exam_workflow.py
    ├── db_helper.py
    ├── selection_generation_schema.sql
    ├── tests/
    │   └── test_question_selection.py
    └── README.md
```

This is the intended structure based on the current implementation plan. Check the actual directory before relying on every filename.

### File responsibilities

| File                                  | Responsibility                                                                               |
| ------------------------------------- | -------------------------------------------------------------------------------------------- |
| `question_selector.py`                | Skill normalization, classification, Question Bank matching, and selection of six questions. |
| `exam_workflow.py`                    | Exam-session lookup, transactional persistence, duplicate prevention, and safe refresh.      |
| `db_helper.py`                        | PostgreSQL connection and transaction utilities.                                             |
| `selection_generation_schema.sql`     | SQL schema and required constraints or indexes for question selection.                       |
| `Question_Selection_Generation.ipynb` | Notebook for running and inspecting the Stage 1 selection workflow.                          |
| `tests/test_question_selection.py`    | Unit tests for classification, selection rules, and validation.                              |
| `README.md`                           | Project documentation and local setup instructions.                                          |

Do not create duplicate modules if equivalent files already exist. Update the existing implementation when possible.

---

## 4. Technologies Used

The folder uses the following technologies:

- Python 3.10 or newer, subject to the project's actual dependency requirements.
- PostgreSQL.
- SQL for database queries and schema management.
- Jupyter Notebook for interactive execution.
- Python database connectivity through the existing database helper.
- Python testing tools for validating skill classification and selection logic.
- JSON processing for JD expected skills.
- Optional NLP normalization utilities already available in RankResume.

The selection phase does not require an LLM to select the first six questions.

### Recommended VS Code extensions

Install these extensions in Visual Studio Code:

| Extension                                                 | Purpose                                                               |
| --------------------------------------------------------- | --------------------------------------------------------------------- |
| Python — Microsoft                                        | Python execution, interpreter selection, debugging, and IntelliSense. |
| Jupyter — Microsoft                                       | Opening and running `.ipynb` notebooks.                               |
| Pylance — Microsoft                                       | Python code completion and static analysis.                           |
| PostgreSQL extension or SQLTools with a PostgreSQL driver | Optional database browsing and SQL execution inside VS Code.          |
| GitLens — optional                                        | Reviewing Git changes and collaborating with teammates.               |

The PostgreSQL extension is optional. All database operations can also be performed from the terminal.

---

## 5. Database Configuration

### PostgreSQL connection details

The development database is:

| Setting  | Value              |
| -------- | ------------------ |
| Database | `rankresume`       |
| Host     | `localhost`        |
| Port     | `5432`             |
| Username | `root`             |
| Password | Locally configured |

The password should be configured separately on each machine. Do not commit real passwords to GitHub or store them directly in notebooks.

The existing `db_helper.py` should be treated as the preferred connection interface if it already supports the required configuration.

### Environment variables

If the implementation uses the `RANKRESUME_DB_*` variables, configure them in the terminal:

```bash
export RANKRESUME_DB_HOST=localhost
export RANKRESUME_DB_PORT=5432
export RANKRESUME_DB_NAME=rankresume
export RANKRESUME_DB_USER=root
export RANKRESUME_DB_PASSWORD='your-local-password'
```

Replace `your-local-password` with the password configured on your machine.

These variables apply to the current shell and programs launched from it. Configure them in your local environment if you need them in future terminal sessions.

If the existing project uses `DATABASE_URL`, a `.env` file, or another configuration mechanism, follow that implementation instead of maintaining two competing configurations.

### Important PostgreSQL authentication note

On Ubuntu, this command may fail if PostgreSQL uses peer authentication:

```bash
psql -U root -d rankresume
```

An administrative connection can be opened with:

```bash
sudo -u postgres psql
```

Then connect to the project database:

```sql
\c rankresume
```

Use the existing database helper for Python execution rather than embedding database passwords in the notebook.

---

## 6. Database Tables and Data Storage

The module interacts with the Question Bank and exam tables. The JD source and candidate-answer tables are managed by other project phases.

### 6.1 `bankresume` — Question Bank

**Purpose:** Stores the existing pool of technical questions and their reference answers.

Expected logical fields include:

```text
question_id
subject
topic
question
answer
expected_concepts
difficulty
```

The actual column names and data types must be verified in PostgreSQL.

This table is created and populated by the `Question_Generation` phase.

It is a source table for this module. The selection workflow must not regenerate, clear, or modify the Question Bank.

To inspect the table:

```sql
SELECT COUNT(*)
FROM bankresume;
```

To inspect the distribution of available questions:

```sql
SELECT
    subject,
    topic,
    difficulty,
    COUNT(*) AS total_questions
FROM bankresume
GROUP BY subject, topic, difficulty
ORDER BY subject, topic, difficulty;
```

The development database previously contained 5,194 rows. Confirm the actual count on each machine.

### 6.2 JD source table

**Purpose:** Stores the Job Description and its structured expected skills.

The actual table name and schema must be discovered from `DB_Store` and the database.

The selection module needs at least:

- A stable JD identifier.
- The expected skills extracted from the JD.
- Any other fields required by the existing project.

The JD JSON is the source of truth for classifying Core Skills and Changeable Skills.

Do not invent a new JD table if an existing table already serves this purpose.

### 6.3 `exam_sessions` — Exam session

**Purpose:** Represents an exam session associated with a JD or the application's exam workflow.

The actual schema determines how a JD is linked to a session and how session status is managed.

The module should reuse the correct existing session when appropriate. It must not create a new session every time the notebook is executed.

### 6.4 `question_exam` — Selected exam questions

**Purpose:** Stores the selected question snapshots for an exam.

The table has previously been observed with fields similar to:

```text
exam_question_id
exam_id
jd_id
question_order
stage
source
question_id
generated_question_id
question
reference_answer
expected_concepts
difficulty
skill
created_at
```

Verify the actual schema before querying or modifying it.

For Stage 1, each row should identify the source Question Bank question and retain the information needed by the exam workflow.

The question snapshot may include the question text, reference answer, expected concepts, difficulty, and skill so the exam and answer-checking phases can use consistent data.

The `question_exam.exam_id` foreign key references `exam_sessions.exam_id`. Therefore, deleting a session can fail while question rows still reference it.

**Do not clear `exam_sessions` as part of normal question selection.**

### 6.5 `answer_store` or candidate-answer table

**Purpose:** Stores submitted candidate answers, if that is the table used by the current implementation.

The exact table name and foreign keys must be verified.

The refresh workflow must inspect these dependencies before replacing exam questions. It must not remove candidate answers or other submitted exam data as a shortcut.

---

## 7. Skill Classification Strategy

The JD's expected skills are divided into three output groups:

1. Core Skills.
2. Changeable Skills.
3. Unclassified Skills.

Unclassified skills are retained for review rather than silently discarded.

### 7.1 Core Skills

Core Skills are relatively stable computer science fundamentals, programming languages, and engineering practices used to select the first six questions.

Examples:

- OOP.
- Data Structures.
- Algorithms and DSA.
- DBMS.
- SQL.
- Operating Systems.
- Computer Networks.
- Computer Architecture.
- Software Engineering.
- SDLC.
- Programming Fundamentals.
- C, C++, C#, Java, and Python.
- JavaScript and TypeScript.
- Git / Version Control.
- Testing Fundamentals.
- System Design Fundamentals.

The exact categories depend on the existing project taxonomy.

### 7.2 Changeable Skills

Changeable Skills include frameworks, libraries, platforms, tools, and other technologies that may vary significantly between job descriptions.

Examples:

- Spring Boot.
- React.
- Angular.
- Node.js.
- Django.
- Flask.
- Docker.
- Kubernetes.
- AWS.
- Azure.
- Terraform.
- Kafka.
- Redis.
- Elasticsearch.
- TensorFlow.

These skills are not used to select the first six Question Bank questions under the current policy. They are intended for the later dynamic-question stage.

### 7.3 Normalization and alias mapping

Skill names may appear in different forms:

```text
OOP
Object Oriented Programming
Object-Oriented Programming

SDLC
Software Development Life Cycle

Git
Git Version Control
Git / Version Control
```

Normalize case, whitespace, and known aliases before classification.

Programming language matching must use exact aliases or token-aware rules.

For example:

- `C` must not match `C++`.
- `C` must not match `C#`.
- `Java` must not match `JavaScript`.
- `C++` must remain distinct from `C`.

Do not use arbitrary substring matching to classify skills.

### 7.4 Example

Given the following JD skills:

```json
{
  "expected_skills": [
    "SDLC",
    "C",
    "C++",
    "Java",
    "SQL",
    "Git",
    "Spring Boot",
    "Docker"
  ]
}
```

The expected classification is:

**Core Skills**

```text
SDLC
C
C++
Java
SQL
Git
```

**Changeable Skills**

```text
Spring Boot
Docker
```

**Unclassified Skills**

```text
None for this example
```

This is the expected result under the stated classification policy.

---

## 8. Question Selection Algorithm

The selection workflow is driven by the JD's Core Skills.

### Step 1 — Load the JD

Read the JD using its actual identifier and load `expected_skills` from the existing structured JD data.

Support the JSON representation used by the current project.

### Step 2 — Classify skills

Normalize the skills and separate them into Core, Changeable, and Unclassified groups.

Display the classification so it can be inspected before selection.

### Step 3 — Map Core Skills to Question Bank categories

Map Core Skills to the actual `bankresume.subject` and `bankresume.topic` values.

For example, the taxonomy may map:

```text
DSA → DSA, Data Structures, Algorithms
SDLC → SDLC, Software Engineering
Git → Git / Version Control
SQL → SQL, DBMS
OOP → OOP, Object-Oriented Programming
```

Use categories that actually exist in the database.

Do not select a question merely because a raw word appears somewhere in its subject or question text.

### Step 4 — Retrieve eligible questions

Query the Question Bank using parameterized SQL.

Check:

- Subject and topic relevance.
- Difficulty.
- Valid question text.
- Valid reference answer.
- Unique Question Bank ID.
- Duplicate normalized question text.

### Step 5 — Select six questions

The required distribution is:

| Difficulty | Number of questions |
| ---------- | ------------------: |
| Easy       |                   3 |
| Medium     |                   2 |
| Hard       |                   1 |
| **Total**  |               **6** |

The distribution approximates the desired 40% Easy, 40% Medium, and 20% Hard ratio.

Do not repeat a question to fill a missing category. If six valid unique questions cannot be selected, report the shortage and avoid committing a partial selection.

### Step 6 — Store the selected questions

Persist the selected question snapshots in `question_exam` with the correct:

- Exam ID.
- JD ID.
- Question order.
- Stage.
- Source.
- Question Bank ID.
- Question text.
- Reference answer.
- Expected concepts.
- Difficulty.
- Skill metadata, where applicable.

Use the existing schema and transaction mechanism.

### Step 7 — Verify the result

Read the saved records back from PostgreSQL.

Confirm:

- Exactly six Stage 1 questions exist for the target exam.
- The question orders are 1 through 6.
- The six Question Bank IDs are unique.
- The normalized question texts are unique.
- The difficulty distribution is 3 Easy, 2 Medium, and 1 Hard.
- The rows belong to the correct JD and exam session.

---

## 9. Duplicate Prevention and Idempotency

A notebook may be executed multiple times during development. Rerunning it must not create extra question sets.

### Normal execution

The normal call is conceptually:

```python
select_questions(jd_id=5, refresh=False)
```

Expected behavior:

1. Find the correct JD.
2. Identify or reuse the correct exam session.
3. Check the existing Stage 1 selection.
4. If six valid questions already exist, return those saved questions.
5. Do not create another session.
6. Do not add another six questions.

The expected result is:

```text
First run:  6 questions
Second run: 6 questions
Third run:  6 questions
```

### Transaction safety

Database writes must be transactional.

If an insertion fails, the transaction should roll back rather than leave an incomplete question set.

Where appropriate, use database uniqueness constraints and locking to protect against concurrent execution.

Application-level checks alone are not sufficient when multiple processes could execute the same selection simultaneously.

---

## 10. Explicit Question Refresh

Sometimes a developer may intentionally want a fresh set of six questions for the same JD.

The refresh operation is separate from normal execution:

```python
select_questions(jd_id=5, refresh=True)
```

### Refresh rules

- Target only the selected JD and its correct exam session.
- Replace only that session's Stage 1 question rows.
- Preserve the session itself unless the existing design requires another approach.
- Select a new valid set of six unique questions.
- Use a transaction so the replacement is atomic.
- Never delete questions from `bankresume`.
- Never delete another JD's questions.
- Never delete candidate answers or other related data blindly.
- Refuse unsafe refreshes if submitted answers or session status make replacement inappropriate.

If an exam has started or answers have been submitted, preserve the exam and require a safe workflow.

Do not use a broad deletion command such as:

```sql
DELETE FROM question_exam;
```

as part of normal application execution.

---

## 11. SQL Schema Setup

The schema file should be maintained in the existing folder, for example:

```text
Question_Selection_Generation/selection_generation_schema.sql
```

This filename must match the actual file in the repository.

The schema setup should preserve existing tables and data. It should not drop, truncate, or recreate `exam_sessions`, `question_exam`, or `bankresume`.

It should define or add only the required schema elements that are compatible with the existing database.

### Inspect the existing tables

Connect to PostgreSQL:

```bash
sudo -u postgres psql
```

Then:

```sql
\c rankresume
```

Inspect the tables:

```sql
\d bankresume
\d exam_sessions
\d question_exam
```

If an answer table exists, inspect that too:

```sql
\dt
```

Use the actual schema before adding constraints or indexes. If historical rows violate a proposed uniqueness constraint, resolve the data issue deliberately rather than forcing the migration.

### Apply the schema file

From the repository root, use the project's configured database connection. If `DATABASE_URL` is supported:

```bash
psql "$DATABASE_URL" \
  -v ON_ERROR_STOP=1 \
  -f Question_Selection_Generation/selection_generation_schema.sql
```

If the project does not use `DATABASE_URL`, supply the correct connection parameters or use the project's established migration method.

Do not assume the SQL file can be safely applied without reviewing its contents first.

---

## 12. Local Machine Setup for a Collaborator

These instructions assume Ubuntu or a similar Linux environment. Windows users may need to adjust activation and environment-variable commands.

### Step 1 — Clone the repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd Project
```

Replace the placeholder with the actual repository URL.

If the repository is already cloned, open the existing project rather than cloning it again.

### Step 2 — Check Python

```bash
python3 --version
```

Use a Python version compatible with the project and its dependencies.

### Step 3 — Create a virtual environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

If virtual environment creation fails, install the appropriate Python venv package for the operating system.

### Step 4 — Install dependencies

If the repository contains a `requirements.txt`:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If dependencies are managed through another file or tool, follow the project's existing setup instructions.

The selection phase typically needs the existing PostgreSQL driver and Jupyter dependencies. Do not install duplicate libraries without checking the project's dependency configuration.

### Step 5 — Configure PostgreSQL

Ensure PostgreSQL is running and the `rankresume` database exists.

The database must contain:

- The JD source table and its structured skills.
- The existing `bankresume` Question Bank.
- The compatible `exam_sessions` table.
- The compatible `question_exam` table and required constraints.

The Question Bank must be loaded using the existing Question Generation setup or a valid database backup. Do not regenerate it simply to run selection.

Configure the collaborator's database credentials using the existing project configuration mechanism.

### Step 6 — Verify the Question Bank

Connect to the database and run:

```sql
SELECT COUNT(*)
FROM bankresume;
```

Check the subject and difficulty values:

```sql
SELECT
    subject,
    difficulty,
    COUNT(*) AS total_questions
FROM bankresume
GROUP BY subject, difficulty
ORDER BY subject, difficulty;
```

If the bank is empty or the required categories are missing, fix the database setup before executing selection.

### Step 7 — Apply the schema

Review and apply the correct SQL schema file using the instructions in Section 11.

Do not execute destructive schema commands from another phase without understanding their effect.

### Step 8 — Run tests

From the repository root, run the test command matching the actual directory layout.

For example, if the folder is directly under the current root:

```bash
python -m unittest discover \
  -s Question_Selection_Generation/tests \
  -p 'test_*.py'
```

If the repository has a different root layout, adjust the path accordingly.

### Step 9 — Open the notebook

From the repository root:

```bash
code Question_Selection_Generation/Question_Selection_Generation.ipynb
```

Alternatively, open the notebook through the VS Code file explorer.

Select the Python interpreter from the project's virtual environment.

### Step 10 — Execute Stage 1

Set the JD identifier in the notebook's designated input cell.

Run the notebook from top to bottom.

Review the displayed:

- JD identifier.
- Expected skills.
- Core Skills.
- Changeable Skills.
- Unclassified Skills.
- Selected questions.
- Difficulty distribution.
- Database validation results.

Do not run the later LLM-generation stage as part of this task.

---

## 13. Database Verification Queries

Run these queries in the `rankresume` database after selection.

### 13.1 Count Stage 1 questions per exam

```sql
SELECT
    exam_id,
    jd_id,
    stage,
    COUNT(*) AS question_count
FROM question_exam
WHERE stage = 1
GROUP BY exam_id, jd_id, stage
ORDER BY jd_id, exam_id;
```

Each completed Stage 1 exam should have six rows.

Historical sessions may appear separately. Inspect the correct current session rather than assuming that all historical sessions for a JD are one exam.

### 13.2 Check difficulty distribution

```sql
SELECT
    exam_id,
    jd_id,
    difficulty,
    COUNT(*) AS question_count
FROM question_exam
WHERE stage = 1
GROUP BY exam_id, jd_id, difficulty
ORDER BY jd_id, exam_id, difficulty;
```

For a newly completed selection, the intended distribution is:

```text
Easy:   3
Medium: 2
Hard:   1
```

### 13.3 Check duplicate Question Bank IDs

```sql
SELECT
    exam_id,
    question_id,
    COUNT(*) AS occurrences
FROM question_exam
WHERE stage = 1
  AND question_id IS NOT NULL
GROUP BY exam_id, question_id
HAVING COUNT(*) > 1;
```

This query should return no rows for exams that satisfy the uniqueness rule.

### 13.4 Check duplicate question orders

```sql
SELECT
    exam_id,
    question_order,
    COUNT(*) AS occurrences
FROM question_exam
WHERE stage = 1
GROUP BY exam_id, question_order
HAVING COUNT(*) > 1;
```

This query should return no rows for exams with unique question orders.

### 13.5 Inspect selected questions

```sql
SELECT
    exam_id,
    jd_id,
    question_order,
    source,
    question_id,
    question,
    difficulty,
    skill
FROM question_exam
WHERE stage = 1
ORDER BY jd_id, exam_id, question_order;
```

Review the question content, source, and skill metadata—not only the row count.

---

## 14. Testing Strategy

The following cases should be tested before the feature is considered ready.

| Test                                     | Expected behavior                                        |
| ---------------------------------------- | -------------------------------------------------------- |
| First execution for a JD                 | Six valid Stage 1 questions are stored.                  |
| Second execution for the same JD         | The existing valid six questions are reused.             |
| Third execution for the same JD          | No additional rows are created.                          |
| Different JD                             | Its selection does not overwrite another JD's selection. |
| Mixed Core and Changeable Skills         | Classification follows the configured taxonomy.          |
| C and C++ in one JD                      | Both are recognized separately.                          |
| Insufficient hard questions              | A clear error is reported; no duplicates are inserted.   |
| Fewer than six eligible unique questions | Selection fails without a partial committed set.         |
| Explicit refresh                         | Only the permitted target Stage 1 selection is replaced. |
| Submitted candidate answers exist        | Unsafe refresh is refused.                               |
| Database insertion fails                 | The transaction rolls back.                              |
| Duplicate question text exists           | Duplicate logical questions are excluded where required. |

Use an isolated test database or controlled fixtures for destructive refresh tests.

Do not test refresh behavior by deleting live candidate data.

---

## 15. Troubleshooting

### Problem: PostgreSQL connection fails

Check:

```bash
sudo systemctl status postgresql
```

Confirm that the database, user, port, and credentials match the local configuration.

On Ubuntu, peer authentication can cause `psql -U root` to fail even when PostgreSQL is running. Use the established authentication method for the local environment.

### Problem: `bankresume` does not exist

The Question Bank may not have been loaded into the current database or schema.

Check:

```sql
\dt
```

Confirm that the connection is to `rankresume` and that the Question Generation setup has been completed.

### Problem: Only Git questions are selected

Inspect the actual JD `expected_skills` structure, the classifier output, and the values in `bankresume.subject` and `bankresume.topic`.

Check whether the alias mapping covers the JD skills. Do not solve this by blindly matching arbitrary substrings.

### Problem: More than six questions are stored

Inspect `exam_sessions` and `question_exam` by JD, exam ID, and stage.

Check whether the code creates a new session on every execution or appends questions without checking for an existing valid selection.

Fix the lookup-or-create logic and relevant constraints. Do not clear the tables as a shortcut.

### Problem: Foreign-key error during deletion

A related table may reference the row being deleted.

Inspect the foreign-key relationships and candidate-answer dependencies before changing any data. Preserve submitted answers and exam sessions.

### Problem: Notebook cannot import local modules

Open VS Code at the project root, select the project's Python interpreter, and confirm that the existing package structure and import paths are correct.

Do not create duplicate helper modules merely to bypass an import error.

### Problem: Difficulty distribution is incorrect

Inspect the actual difficulty labels in `bankresume`. Normalize capitalization and known label variations in the selection code.

Do not silently relabel questions to force the desired distribution.

---

## 16. Git and Collaboration

Before committing changes:

```bash
git status
git diff
```

Review the changes to Python files, notebooks, SQL, and documentation.

Do not commit passwords, `.env` files containing credentials, database dumps containing private candidate data, or unrelated local artifacts.

Commit only the intended project files.

Example:

```bash
git add Question_Selection_Generation/
git commit -m "Fix idempotent Stage 1 question selection"
```

Coordinate schema changes with the collaborator so both local databases use compatible table structures and constraints.

---

## 17. Current Scope and Future Work

### Current scope

- Read the existing JD skills.
- Classify Core Skills and Changeable Skills.
- Map Core Skills to Question Bank categories.
- Select six unique questions.
- Maintain the 3 Easy / 2 Medium / 1 Hard distribution.
- Store question snapshots in `question_exam`.
- Prevent duplicate selections on reruns.
- Support safe, explicit refresh.
- Verify database results.
- Document setup for collaborators.

### Later phase

The following work is outside the current scope:

- Generating four additional LLM questions from Changeable Skills.
- Adaptive question difficulty based on the first six answers.
- Evaluating candidate answers.
- Calculating the final exam score.

These features should integrate with the current schema and workflow in their respective project folders. They must not be implemented prematurely in the Stage 1 notebook.

---



**Final goal:** For each eligible JD, RankResume must select and persist exactly six unique Stage 1 questions from the existing Question Bank, with the required difficulty distribution, and remain safe when the notebook is executed repeatedly.
