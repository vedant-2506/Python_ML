# Question_Selection_Generation

## Section 1: Folder Name and Overview

- **Folder Name**: `Question_Selection_Generation`
- **Location**: `Project/Question_Selection_Generation`
- **Purpose**: `Question_Selection_Generation` is the adaptive technical exam orchestrator of **RankResume**. It manages the complete lifecycle of a 10-question technical evaluation:
  1. **Stage 1 (Core Computer Science)**: Selects six foundational questions (3 Easy, 2 Medium, 1 Hard; totaling 60 marks) from the pre-generated Question Bank (`public.bankresume`) based on the job description's Core skills.
  2. **Stage 2 (Adaptive Changeable Skills)**: Dynamically generates four specialized questions (totaling 40 marks) using a Groq-hosted Large Language Model (e.g., Llama-3.3-70b-versatile). The difficulty distribution of Stage 2 adapts automatically based on the candidate's actual Stage 1 performance percentage.
- **Problem It Solves**: Fixed, static technical assessments fail to adapt to candidate competency levels and fail to assess job-specific frameworks that vary across roles (e.g., React, FastAPI, Kubernetes). This module ensures every exam begins with standardized core CS questions, then dynamically tailors subsequent questions to the candidate's demonstrated ability.
- **Why It Is Necessary**: It bridges static resume screening with interactive technical assessment. By categorizing skills into stable Core concepts vs. emerging Changeable skills and applying an immutable adaptive scoring policy, RankResume provides fair, automated, and cheat-resistant technical evaluations.

---

## Section 2: Role in the Overall RankResume Project

Within RankResume, `Question_Selection_Generation` represents **Phase 3 (Adaptive Assessment Generation & Orchestration)**:

1. **Before This Module Runs**:
   - `DB_Store` has ingested candidate resumes and job descriptions.
   - `ATS_calculation` has computed match scores and ranked candidates.
   - `Question_Generation` has populated `public.bankresume` with 5,194 core CS questions.
2. **What This Module Receives**:
   - Target Job Description ID (`jd_id`), Candidate ID (`candidate_id`), and an exam session identifier (`exam_id` UUID).
   - In Stage 2, it receives the candidate's completed Stage 1 evaluations from `Answer_Checking`.
3. **What Processing It Performs**:
   - Classifies JD `expected_skills` into **Core Skills** (OOP, DBMS, OS, Networks, etc.), **Changeable Skills** (React, Spring Boot, Docker, AWS, etc.), and **Unclassified Skills**.
   - Selects 6 Stage 1 questions from `public.bankresume` matching Core skills with the exact distribution: 3 Easy (6 marks each), 2 Medium (12 marks each), 1 Hard (18 marks each) = 60 marks total.
   - Creates an exam session in `public.exam_sessions` (30-minute duration).
   - Computes candidate Stage 1 percentage score ($0\text{--}100\%$) using strict Decimal precision.
   - Resolves Stage 2 difficulty distribution:
     * **0–59%**: 3 Easy + 1 Medium
     * **60–80%**: 2 Easy + 2 Medium
     * **81–100%**: 3 Medium + 1 Hard
   - Constructs a prompt for Groq LLM enforcing 5–6 sentence reference answers and 3–6 expected concepts.
   - Validates the untrusted Groq JSON output against strict syntactic and semantic rules.
   - Stores the exam snapshot in `public.question_exam` and `public.ai_question_exam`.
4. **What Output It Produces**:
   - Active exam sessions in `public.exam_sessions`.
   - Immutable question snapshots in `public.question_exam` (questions 1–10) and `public.ai_question_exam` (Stage 2 questions 1–4).
5. **Which Module Uses Its Output Next**:
   - `Answer_Checking`: Delivers questions to the candidate, records answers, and evaluates submissions against the reference answers and expected concepts created here.
6. **Execution Independence**:
   - Stage 1 selection requires PostgreSQL (`question_bank` and `job_description`).
   - Stage 2 generation requires active Groq API access (`GROQ_API_KEY`) and completed Stage 1 evaluations in `public.answer_evaluation`.

---

## Section 3: Complete Folder Structure

```text
Question_Selection_Generation/
├── README.md                            # Comprehensive technical documentation
├── __init__.py                          # Package marker
├── adaptive_policy.py                   # Deterministic scoring policy & difficulty mapping
├── config.py                            # Environment loader for Groq API keys and models
├── db_helper.py                         # PostgreSQL connection and schema creation helpers
├── exam_workflow.py                     # Stage 1 exam session creation & question selection
├── groq_client.py                       # Lightweight urllib-based Groq API client
├── llm_question_generator.py            # Groq Stage 2 generation & untrusted JSON validation
├── question_selector.py                 # Skill classifier, vocabulary loader & bank query logic
├── selection_generation_schema.sql      # DDL schema for exam sessions, question_exam, and ai_question_exam
├── stage2_workflow.py                   # Stage 2 database transaction orchestration & locking
├── LLM_Question_Generation.ipynb        # Jupyter notebook exploring Groq question generation
├── Question_Selection_Generation.ipynb  # Jupyter notebook exploring selection workflows
├── prompts/
│   ├── __init__.py                      # Package marker
│   └── adaptive_question_prompt.py      # Structured JSON prompt contract for Groq
└── tests/
    ├── test_llm_generation.py           # Unit tests for Groq generation validation
    ├── test_question_selection.py       # Unit tests for Stage 1 selection and skill classification
    └── test_stage2.py                   # End-to-end integration tests for Stage 2 workflow
```

---

## Section 4: File-by-File Explanation

### 1. `Question_Selection_Generation/config.py`
- **Purpose**: Centralizes environment variables for Stage 2 Groq LLM generation.
- **Key Settings**:
  - `GROQ_API_KEY`: Authentication bearer token.
  - `GROQ_BASE_URL`: Defaults to `https://api.groq.com/openai/v1`.
  - `GROQ_MODEL`: Defaults to `llama-3.3-70b-versatile`.
  - `GROQ_TIMEOUT`: Default timeout (30.0 seconds).
  - `LLM_PROVIDER`: Default `groq`.

### 2. `Question_Selection_Generation/db_helper.py`
- **Purpose**: Provides database connectivity and schema initialization for exam tables.
- **Key Functions**:
  - `connect()`: Returns connection from `Answer_Checking.config.get_db_config()`.
  - `ensure_schema(connection)`: Executes `selection_generation_schema.sql`.
  - `fetch_jd(connection, jd_id)`: Fetches JD title and structured JSON data.

### 3. `Question_Selection_Generation/adaptive_policy.py`
- **Purpose**: Defines the deterministic mathematical policy governing Stage 1 percentage calculation and Stage 2 difficulty selection.
- **Key Constants & Functions**:
  - `STAGE1_MAX_MARKS = Decimal("60")`
  - `DIFFICULTY_MARKS = {"Easy": Decimal("6"), "Medium": Decimal("12"), "Hard": Decimal("18")}`
  - `calculate_percentage(evaluations) -> Decimal`: Verifies exactly six Stage 1 evaluations, enforces that difficulties match 3 Easy, 2 Medium, 1 Hard, and computes percentage score rounded to two decimal places.
  - `determine_stage2_difficulty(percentage) -> dict`:
    * $\le 59\%$: `{"Easy": 3, "Medium": 1, "Hard": 0}`
    * $60\text{--}80\%$: `{"Easy": 2, "Medium": 2, "Hard": 0}`
    * $\ge 81\%$: `{"Easy": 0, "Medium": 3, "Hard": 1}`
  - `resolve_stage2_difficulty(evaluations) -> tuple`: Returns the adaptive distribution if 6 completed evaluations exist, or falls back to default distribution `{"Easy": 2, "Medium": 2, "Hard": 0}` if evaluations are pending.

### 4. `Question_Selection_Generation/groq_client.py`
- **Purpose**: Dependency-light HTTP client using Python's standard `urllib.request` to communicate with the Groq API.
- **Key Functions**:
  - `_request(path, method, body)`: Issues HTTP requests with `Authorization: Bearer <KEY>` headers.
  - `verify_model(model)`: Queries `/models` to confirm the configured LLM is actively served.
  - `generate_json(prompt, model)`: Sends prompt with `response_format: {"type": "json_object"}` and returns parsed JSON.

### 5. `Question_Selection_Generation/question_selector.py`
- **Purpose**: Skill classification and Stage 1 question bank selection.
- **Key Classes & Functions**:
  - `classify_skills(expected_skills, project_vocabulary) -> SkillClassification`: Categorizes skills into `core` (e.g., Python, C++, Data Structures), `changeable` (e.g., React, Django, Docker), and `unresolved`.
  - `select_stage1_questions(connection, core_subjects, rng=None) -> list[SelectedQuestion]`: Queries `public.question_bank` for 3 Easy, 2 Medium, and 1 Hard questions across the matched core subjects. Randomly samples within each difficulty while preserving the required order: Questions 1–3 Easy, 4–5 Medium, and 6 Hard.
  - `validate_stage1_questions(questions)`: Verifies non-empty fields, exactly 6 questions, unique question IDs, unique texts, and exact difficulty counts.

### 6. `Question_Selection_Generation/exam_workflow.py`
- **Purpose**: Creates and manages the initial 30-minute exam session in PostgreSQL.
- **Key Functions**:
  - `create_exam(connection, jd_id, rng=None)`: Creates a new UUID `exam_id` in `public.exam_sessions` with `status = 'STAGE1_READY'` and saves 6 selected Stage 1 questions into `public.question_exam`.

### 7. `Question_Selection_Generation/llm_question_generator.py`
- **Purpose**: Coordinates Groq LLM Stage 2 question generation and untrusted response validation.
- **Key Functions**:
  - `validate_generated_questions(payload, changeable_skills, difficulty_distribution, existing_questions) -> list[GeneratedQuestion]`:
    * Validates that exactly 4 questions are returned.
    * Ensures skills belong to allowed Changeable Skills.
    * Enforces that every reference answer has exactly 5 or 6 sentences.
    * Enforces 1 to 8 expected concepts per question.
    * Rejects questions with sequence similarity $\ge 0.88$ against already-used questions.
    * Verifies that difficulty counts strictly match the adaptive policy.
  - `generate_stage2_questions()`: Builds prompt, calls Groq, runs validation, and retries with corrective prompts if needed.

### 8. `Question_Selection_Generation/stage2_workflow.py`
- **Purpose**: Database transaction orchestration and PostgreSQL advisory locking for idempotent Stage 2 batch generation.
- **Key Functions**:
  - `generate_or_reuse_stage2(exam_id, jd_id, candidate_id) -> dict`:
    * Acquires transactional advisory lock `pg_advisory_xact_lock(hashtextextended('stage2:<exam_id>', 0))` to prevent concurrent duplicate generation.
    * Checks if Stage 2 questions already exist; if so, reuses them.
    * Reads candidate's Stage 1 scores via `fetch_stage1_evaluations()`.
    * Computes adaptive difficulty and generates 4 Changeable Skill questions via Groq.
    * Atomically inserts rows into `public.generated_questions`, `public.ai_question_exam`, and `public.question_exam` (questions 7–10).

### 9. `Question_Selection_Generation/prompts/adaptive_question_prompt.py`
- **Purpose**: Formats the system and user prompt sent to Groq enforcing valid JSON output and strict technical constraints.

---

## Section 5: Detailed Code Execution and Line-by-Line Analysis

### 1. Stage 1 Question Selection in `question_selector.py` (Lines 248–285)
```python
def select_stage1_questions(
    connection, core_subjects: list[str], rng: random.Random | None = None,
) -> list[SelectedQuestion]:
    rng = rng or random.SystemRandom()
    chosen: list[tuple] = []
    used_ids: set[int] = set()
    used_hashes: set[str] = set()
    shortages: dict[str, int] = {}
    for difficulty, count in (("Easy", 3), ("Medium", 2), ("Hard", 1)):
        candidates = []
        for row in _query_for_subjects(connection, core_subjects, difficulty):
            normalized = normalize_question(row[3])
            if row[0] not in used_ids and normalized and normalized not in used_hashes:
                candidates.append(row)
        if len(candidates) < count:
            shortages[difficulty] = count - len(candidates)
            continue
        selected = rng.sample(candidates, count)
        chosen.extend(selected)
        used_ids.update(row[0] for row in selected)
        used_hashes.update(normalize_question(row[3]) for row in selected)
```
- **Lines 254–255**: Iterates through required difficulties: Easy (3), Medium (2), Hard (1).
- **Lines 256–260**: Queries `question_bank` for questions matching the candidate's core subjects, filtering out already-selected IDs and duplicate texts.
- **Lines 264–267**: Uses cryptographically safe random sampling (`SystemRandom`) to pick questions without replacement.
- **Question selection**: Randomly samples within each difficulty band, then runs `validate_stage1_questions()` to ensure zero duplicate IDs, the required display order, and non-empty fields.

### 2. Adaptive Policy Logic in `adaptive_policy.py` (Lines 15–75)
```python
def calculate_percentage(evaluations: Iterable[dict[str, Any]]) -> Decimal:
    rows = list(evaluations)
    if len(rows) != 6:
        raise ValueError(f"exactly six Stage 1 evaluations are required; found {len(rows)}")
    ...
    total_max = Decimal("0")
    obtained = Decimal("0")
    for row in ordered:
        marks = Decimal(str(row["obtained_marks"]))
        max_marks = Decimal(str(row.get("max_marks") or DIFFICULTY_MARKS[row["difficulty"]]))
        obtained += marks
        total_max += max_marks
    percentage = (obtained / STAGE1_MAX_MARKS * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return percentage
```
- Enforces strict input validation: requires exactly 6 completed evaluations.
- Uses Python `Decimal` with `ROUND_HALF_UP` to prevent floating-point inaccuracies.
- Verifies that max marks sum to exactly 60.

### 3. Untrusted LLM Response Validation in `llm_question_generator.py` (Lines 44–95)
- Checks that root payload contains exactly 4 questions.
- Rejects any question where `skill` is not in the JD's allowed Changeable Skills list.
- Uses `sentence_count()` to reject reference answers that do not have exactly 5 or 6 sentences.
- Computes `SequenceMatcher` ratio against all prior questions (threshold 0.88) to prevent near-duplicate questions.
- Checks that the generated difficulty tally matches the adaptive distribution.

---

## Section 6: Complete Workflow

```text
Job Description (expected_skills)
               │
               ▼
┌──────────────────────────────┐
│  Skill Classification        │
│  - Core Skills (OOP, OS...)  │
│  - Changeable (React, AWS..) │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Stage 1 Question Selection  │
│  Query public.bankresume     │
│  Select 3 Easy, 2 Med, 1 Hard│
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Create Exam Session         │
│  public.exam_sessions (UUID) │
│  Save to public.question_exam│
└──────────────┬───────────────┘
               │
               ▼
     [Candidate Takes Stage 1]
     [Answer_Checking Evaluates]
               │
               ▼
┌──────────────────────────────┐
│  Stage 1 Scored Percentage   │
│  (0-100% via Decimal)        │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Adaptive Policy Engine      │
│  0-59%  -> 3 Easy + 1 Medium │
│  60-80% -> 2 Easy + 2 Medium │
│  81-100%-> 3 Medium + 1 Hard │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Groq LLM Generation         │
│  Llama-3.3-70b-versatile     │
│  Generate 4 Changeable Skills│
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Strict Validation Engine    │
│  - 5-6 sentence answers      │
│  - 3-6 expected concepts     │
│  - Anti-paraphrase checks    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Stage 2 Persistence         │
│  public.ai_question_exam     │
│  public.question_exam (7-10) │
└──────────────────────────────┘
```

---

## Section 7: Database Information

- **Technology**: PostgreSQL 14+
- **Database Name**: Default `rankresume`
- **Tables Managed**:

### 1. Table `public.exam_sessions`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `exam_id` | `UUID` | `PRIMARY KEY` | Unique exam session identifier |
| `jd_id` | `BIGINT` | `REFERENCES job_description(jd_id)` | Associated job description |
| `started_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | Exam start timestamp |
| `ends_at` | `TIMESTAMP` | | Expiration timestamp |
| `duration_minutes`| `SMALLINT`| `DEFAULT 30 CHECK (= 30)` | Enforced 30-minute exam window |
| `status` | `VARCHAR(30)` | `CHECK IN ('STAGE1_READY', 'STAGE1_SUBMITTED', 'STAGE2_READY', 'COMPLETED')` | Lifecycle state |

### 2. Table `public.question_exam`
Stores the unified 10-question snapshot for an exam session.
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `exam_question_id`| `BIGSERIAL` | `PRIMARY KEY` | Unique record identifier |
| `exam_id` | `UUID` | `REFERENCES exam_sessions(exam_id)` | Associated exam |
| `jd_id` | `BIGINT` | `REFERENCES job_description(jd_id)` | Job description |
| `question_order` | `SMALLINT` | `CHECK BETWEEN 1 AND 10` | Display order (1–6 Stage 1, 7–10 Stage 2) |
| `stage` | `SMALLINT` | `CHECK IN (1, 2)` | Exam stage |
| `source` | `VARCHAR(20)` | `CHECK IN ('Question Bank', 'LLM')` | Origin of question |
| `question_id` | `BIGINT` | `REFERENCES bankresume(question_id)` | Populated for Stage 1 |
| `generated_question_id`| `BIGINT`| `REFERENCES generated_questions(...)` | Populated for Stage 2 |
| `question` | `TEXT` | `NOT NULL` | Question text |
| `reference_answer` | `TEXT` | `NOT NULL` | Expected answer text |
| `expected_concepts`| `JSONB` | `NOT NULL` | Essential concepts |
| `difficulty` | `VARCHAR(20)` | `CHECK IN ('Easy', 'Medium', 'Hard')` | Assessed difficulty |
| `skill` | `VARCHAR(200)` | | Targeted skill |

### 3. Table `public.ai_question_exam`
Stores the candidate-specific Stage 2 question snapshot.
- Columns: `ai_question_exam_id`, `exam_id`, `jd_id`, `candidate_id`, `question_order` (1–4), `source` (`'groq_llm'`), `question`, `answer`, `reference_answer`, `expected_concepts` (`JSONB`), `difficulty`, `skill`, `question_hash`, `model_name`.
- Constraints: `UNIQUE (exam_id, candidate_id, question_order)`.

---

## Section 8: Input and Output

### Input (Job Description Structured Data)
```json
{
  "job_title": "Full Stack Python Developer",
  "expected_skills": ["Python", "Object-Oriented Programming (OOP)", "FastAPI", "Docker", "PostgreSQL"]
}
```

### Stage 1 Selection Output
6 questions from `public.bankresume`:
- Q1: Easy (Python, 6 marks)
- Q2: Easy (OOP, 6 marks)
- Q3: Easy (PostgreSQL, 6 marks)
- Q4: Medium (OOP, 12 marks)
- Q5: Medium (PostgreSQL, 12 marks)
- Q6: Hard (Python, 18 marks)
*Total: 60 marks.*

### Stage 2 Adaptive Output (Candidate scored 75% in Stage 1)
Adaptive Policy selects: **2 Easy + 2 Medium** from Changeable Skills (`FastAPI`, `Docker`).
- Q7 (Order 1): Easy (FastAPI, 6 marks)
- Q8 (Order 2): Easy (Docker, 6 marks)
- Q9 (Order 3): Medium (FastAPI, 12 marks)
- Q10 (Order 4): Medium (Docker, 12 marks)
*Total: 40 marks (Combined 100 marks).*

---

## Section 9: Dependencies and Requirements

- **Python Version**: Python 3.10+
- **Database Driver**: `psycopg2-binary`
- **External API**: Groq Cloud API (`https://api.groq.com/openai/v1`)
- **Environment Variables**:
  - `GROQ_API_KEY`: Required for Stage 2 question generation.
  - `GROQ_MODEL`: Default `llama-3.3-70b-versatile`.
  - `RANKRESUME_DB_*`: PostgreSQL database connection settings.

---

## Section 10: Setup and Execution Instructions

### 1. Apply Schema Migrations
```bash
psql -h localhost -U <DB_USER> -d rankresume -f Question_Selection_Generation/selection_generation_schema.sql
```

### 2. Configure Groq API Key
In `.env`:
```env
GROQ_API_KEY=<YOUR_GROQ_API_KEY>
GROQ_MODEL=llama-3.3-70b-versatile
```

### 3. Run Automated Test Suite
From the project root:
```bash
python3 -m unittest discover Question_Selection_Generation/tests/
```

---

## Section 11: How to Test and Verify

- **Test Files**:
  - `tests/test_question_selection.py`: Verifies skill classification and Stage 1 question distribution.
  - `tests/test_llm_generation.py`: Verifies Groq JSON response validation, sentence counting, and anti-duplication logic.
  - `tests/test_stage2.py`: Tests the transactional Stage 2 workflow and adaptive difficulty policy.
- **Database Inspection**:
  ```sql
  SELECT exam_id, question_order, stage, source, difficulty, skill
  FROM public.question_exam
  ORDER BY exam_id, question_order;
  ```

---

## Section 12: Error Handling and Limitations

1. **Groq API Outage / Missing Key**: If `GROQ_API_KEY` is not configured, `groq_client.py` raises `GroqError`. Stage 2 will fail gracefully without corrupting Stage 1 data.
2. **Shortage of Changeable Skills**: If a JD contains no changeable skills (e.g., only pure core CS topics), `stage2_workflow.py` raises `Stage2StateError` rather than generating irrelevant questions.
3. **Concurrent Generation**: PostgreSQL advisory locks (`pg_advisory_xact_lock`) prevent multiple concurrent processes from generating duplicate Stage 2 batches for the same exam session.
4. **Current Limitations**:
   - Stage 2 generation relies on external Groq API availability; an active internet connection is required for Stage 2.

---

## Section 13: Connection With Other Folders

- **`DB_Store`**: Reads job descriptions (`public.job_description.structured_data`) to extract `expected_skills`.
- **`Question_Generation`**: Reads `public.bankresume` to select Stage 1 questions.
- **`Answer_Checking`**: Provides completed Stage 1 evaluation scores to compute adaptive Stage 2 difficulty, and delivers generated Stage 2 questions to candidates.

---

## Section 14: Example Execution

```python
from Question_Selection_Generation.adaptive_policy import determine_stage2_difficulty

# Scenario A: Candidate achieves 52% in Stage 1
dist_a = determine_stage2_difficulty(52.0)
print("Score 52% Stage 2 Distribution:", dist_a)
# Output: {'Easy': 3, 'Medium': 1, 'Hard': 0}

# Scenario B: Candidate achieves 85% in Stage 1
dist_b = determine_stage2_difficulty(85.0)
print("Score 85% Stage 2 Distribution:", dist_b)
# Output: {'Easy': 0, 'Medium': 3, 'Hard': 1}
```

---

## Section 15: Current Implementation Status and Future Improvements

- **Implemented**:
  - Skill classification into Core, Changeable, and Unclassified.
  - Deterministic Stage 1 selection (3 Easy, 2 Medium, 1 Hard).
  - Adaptive Stage 2 policy based on Stage 1 percentage.
  - Groq LLM integration with structured JSON validation and sentence count verification.
  - Advisory locking and snapshot persistence in `exam_sessions`, `question_exam`, and `ai_question_exam`.
- **Planned / Future Improvements**:
  - Local Ollama fallback for Stage 2 when internet access is unavailable.
  - Multi-candidate simultaneous exam session pooling.

---

## Section 16: Glossary

- **Core Skills**: Foundational, stable computer science subjects (OOP, DBMS, Networks, Data Structures).
- **Changeable Skills**: Fast-evolving, job-specific technical frameworks and tools (e.g., React, Flutter, Kubernetes).
- **Adaptive Policy**: An automated algorithm that adjusts assessment difficulty according to real-time candidate performance.
- **Advisory Lock**: A PostgreSQL transactional locking mechanism that synchronizes concurrent application threads without locking tables.

---

## Section 17: References to Source Files

- [exam_workflow.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Selection_Generation/exam_workflow.py) — Stage 1 exam session creation and bank selection.
- [stage2_workflow.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Selection_Generation/stage2_workflow.py) — Stage 2 database transaction and advisory lock management.
- [question_selector.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Selection_Generation/question_selector.py) — Skill classification and Question Bank query builder.
- [adaptive_policy.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Selection_Generation/adaptive_policy.py) — Mathematical formulas and difficulty distribution rules.
- [llm_question_generator.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Selection_Generation/llm_question_generator.py) — Groq LLM generation and untrusted response validator.
- [groq_client.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Selection_Generation/groq_client.py) — Minimal HTTP client for Groq API.
- [selection_generation_schema.sql](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Selection_Generation/selection_generation_schema.sql) — DDL table definitions and indexes.
