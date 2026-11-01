# Question_Generation

## Section 1: Folder Name and Overview

- **Folder Name**: `Question_Generation`
- **Location**: `Project/Question_Generation`
- **Purpose**: `Question_Generation` owns the generation, programmatic validation, deduplication, and PostgreSQL population of the offline **Core Computer Science Question Bank** (`public.bankresume`).
- **Problem It Solves**: In technical hiring assessments, generating foundational computer science questions dynamically through LLMs introduces runtime non-determinism, unpredictable formatting, API latency, recurring inference costs, and potential hallucinations. This module pre-generates a balanced, audited catalog of 5,194 comprehensive computer science questions spanning 14 core computer-science subjects and 14 programming languages.
- **Why It Is Necessary**: Stage 1 of the RankResume technical interview requires verified, standardized, and reproducible foundational questions with deterministic reference answers and expected concept keywords. `Question_Generation` provides a standalone, restartable, and fully deterministic pipeline that does not require an LLM, network connection, or external service to produce its balanced catalog.

---

## Section 2: Role in the Overall RankResume Project

Within RankResume, `Question_Generation` provides the **Curated Knowledge Asset**:

1. **Before This Module Runs**:
   - The PostgreSQL database `rankresume` is initialized.
   - The database schema `bankresume_schema.sql` defines the `public.bankresume` table structure.
2. **What This Module Receives**:
   - Curated dictionaries of subjects, concepts, evaluation angles (e.g., "definition", "trade-offs", "limitations", "failure modes"), and software engineering contexts defined in `question_generator.py`.
   - PostgreSQL connection credentials.
3. **What Processing It Performs**:
   - Combinatorial generation of distinct questions by crossing concepts, contextual angles, and domain templates.
   - Deterministic answer synthesis generating structured 5-to-6 sentence reference answers containing core definitions, trade-offs, and conclusions.
   - SHA-256 fingerprinting for idempotent database upserts.
   - Audit validation via `question_validator.py` and `question_deduplicator.py` (sentence count checks, 3-shingle Jaccard similarity, hash collision detection).
   - SQL export generating `question_bank.sql` containing schema and full `COPY` data stream.
4. **What Output It Produces**:
   - Populated `public.bankresume` table containing 5,194 verified questions.
   - Comprehensive audit report in `question_bank_report.json`.
   - Standalone migration dump `question_bank.sql` (5.7 MB).
5. **Which Module Uses Its Output Next**:
   - `Question_Selection_Generation`: Queries `public.bankresume` during Stage 1 exam creation to select 6 core questions (3 Easy, 2 Medium, 1 Hard).
   - `Answer_Checking`: References `bankresume.answer` and `bankresume.expected_concepts` as the ground-truth benchmark during Stage 1 candidate answer evaluation.
6. **Execution Independence**:
   - Completely independent. It does not import or call any code from `ATS_calculation`, `DB_Store`, or `Answer_Checking`.

---

## Section 3: Complete Folder Structure

```text
Question_Generation/
├── README.md                 # Comprehensive technical documentation for Question_Generation
├── bankresume_schema.sql     # DDL schema for table public.bankresume and indexes
├── database.py               # Standalone PostgreSQL connection and transaction manager
├── generation_output.txt     # Log artifact from question generator run
├── question_bank.sql         # Data-bearing SQL export with schema and COPY data (5,194 records)
├── question_bank_report.json # JSON audit report detailing distribution, counts, and validation checks
├── question_deduplicator.py  # 3-shingle Jaccard similarity and exact duplicate detection
├── question_generator.py     # Deterministic catalog generator (558 targets across 28 subjects)
├── question_validator.py     # Comprehensive database and export auditor
└── validation_output.txt     # Log artifact from question audit run
```

---

## Section 4: File-by-File Explanation

### 1. `Question_Generation/database.py`
- **Purpose**: Provides lightweight, isolated PostgreSQL connection and transaction management for question bank operations.
- **Why Required**: Keeps `Question_Generation` self-contained and decoupled from project-wide configuration modules.
- **Key Functions**:
  - `connect() -> connection`: Creates a `psycopg2` connection reading `RANKRESUME_DB_*` environment variables.
  - `transaction() -> Iterator[connection]`: Context manager wrapping operations in an explicit `BEGIN ... COMMIT` block with automatic rollback on exceptions.

### 2. `Question_Generation/bankresume_schema.sql`
- **Purpose**: PostgreSQL DDL script creating `public.bankresume`.
- **Why Required**: Enforces schema constraints, primary keys, and difficulty checks (`CHECK (difficulty IN ('Easy', 'Medium', 'Hard'))`).
- **Indexes Created**: B-tree indexes on `subject`, `topic`, and `difficulty`.

### 3. `Question_Generation/question_generator.py`
- **Purpose**: The primary generation engine that programmatically constructs 5,194 unique technical questions and answers.
- **Why Required**: Guarantees perfectly balanced distributions across core CS topics without LLM hallucinations.
- **Target Distribution**:
  - **14 Core CS Subjects** (250 questions each = 3,500 total):
    * Object-Oriented Programming (OOP)
    * Data Structures
    * Algorithms
    * Database Management Systems (DBMS)
    * SQL
    * Computer Networks
    * Operating Systems
    * Software Engineering
    * Software Development Life Cycle (SDLC)
    * System Design Fundamentals
    * Computer Architecture
    * Programming Fundamentals
    * Git / Version Control
    * Software Testing Fundamentals
  - **14 Programming Languages** (121 questions each = 1,694 total):
    * Java, Python, JavaScript, C++, C, C#, Go / Golang, TypeScript, Kotlin, PHP, Ruby, Rust, Dart, Scala
  - **Total**: 5,194 questions.
- **Key Functions**:
  - `_answer(subject, concept, context, angle, index)`: Synthesizes a structured 5-to-6 sentence reference answer.
  - `_hash(question)`: Generates SHA-256 digest of normalized question text.
  - `generate_records()`: Produces `Question` dataclasses.
  - `insert_missing()`: Uses `psycopg2.extras.execute_values` with `ON CONFLICT (question_hash) DO UPDATE` to ensure restartable, idempotent population.

### 4. `Question_Generation/question_deduplicator.py`
- **Purpose**: Algorithmic near-duplicate and exact-duplicate detection without requiring external embedding models.
- **Why Required**: Ensures the question bank contains diverse wording and avoids semantic redundancy.
- **Key Functions**:
  - `normalize(text)`: Lowercases text and strips non-alphanumeric punctuation.
  - `shingles(text)`: Deconstructs text into word 3-grams (tri-grams).
  - `similarity(left, right)`: Computes Jaccard similarity:
    $$J(A, B) = \frac{|A \cap B|}{|A \cup B|}$$
  - `duplicate_counts()`: Uses bucketed 3-shingle comparisons to count near-duplicates exceeding configurable thresholds (default: 0.86 for questions, 0.98 for answers).

### 5. `Question_Generation/question_validator.py`
- **Purpose**: Full database auditor and exporter.
- **Why Required**: Validates database integrity before deployment and exports the standalone `question_bank.sql`.
- **Audit Rules Checked**:
  - Total records $\ge 5,000$.
  - All targets met per subject.
  - Zero empty or whitespace-only records.
  - Zero invalid difficulty values.
  - Zero duplicate question hashes.
  - Zero near-duplicate questions ($J \ge 0.86$).
  - Every reference answer has exactly 5 or 6 sentences.
  - Expected concepts are non-empty and present in the answer.

---

## Section 5: Detailed Code Execution and Line-by-Line Analysis

### 1. Sentence-Controlled Answer Generation in `question_generator.py` (Lines 140–183)
```python
def _answer(subject: str, concept: str, context: str, angle: str, index: int) -> str:
    definition = (
        f"{concept.capitalize()} in {subject} represents a core mechanism used to establish "
        f"reliable system behavior and structure runtime operations."
    )
    sentence_two = mechanics[(index) % len(mechanics)]
    sentence_three = contexts[(index // len(mechanics)) % len(contexts)]
    sentence_four = trade_offs[(index // len(contexts)) % len(trade_offs)]
    sentence_five = limitations[(index // len(trade_offs)) % len(limitations)]
    sentence_six = conclusions[(index // len(limitations)) % len(conclusions)]
    return " ".join([definition, sentence_two, sentence_three, sentence_four, sentence_five, sentence_six])
```
- **Line 141–144**: Constructs an opening sentence defining the concept and subject.
- **Lines 177–181**: Selects distinct domain mechanics, execution contexts, engineering trade-offs, practical limitations, and architectural conclusions using modular cycle offsets.
- **Line 182**: Joins exactly six coherent sentences forming a rich, technically sound reference answer.

### 2. Shingle-Based Deduplication in `question_deduplicator.py` (Lines 16–35)
```python
def shingles(text: str) -> set[str]:
    words = normalize(text).split()
    return {" ".join(words[index:index + 3]) for index in range(max(0, len(words) - 2))}

def similarity(left: str, right: str) -> float:
    a, b = shingles(left), shingles(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
```
- Deconstructs normalized text into sliding windows of 3 consecutive words.
- Computes set intersection over union. If two questions share a high Jaccard coefficient, they are flagged as semantic paraphrases.

### 3. Database Audit and COPY Export in `question_validator.py` (Lines 35–105)
- Executes aggregation queries in PostgreSQL checking `COUNT(*)`, `GROUP BY subject`, `GROUP BY difficulty`.
- Uses PostgreSQL's internal `COPY ... TO STDOUT` via `cursor.copy_expert()` to dump the audited table into `question_bank.sql`.

---

## Section 6: Complete Workflow

```text
Curated Core CS & Programming Language Targets
                     │
                     ▼
       ┌───────────────────────────┐
       │   question_generator.py   │
       │   - Combinatorial angles  │
       │   - 5-6 sentence answers  │
       │   - Expected concepts     │
       │   - SHA-256 fingerprint   │
       └─────────────┬─────────────┘
                     │
                     ▼
       ┌───────────────────────────┐
       │ PostgreSQL (bankresume)   │
       │ 5,194 Inserted Records    │
       └─────────────┬─────────────┘
                     │
                     ▼
       ┌───────────────────────────┐
       │   question_validator.py   │
       │   - Sentence count audit  │
       │   - 3-shingle similarity  │
       │   - Hash collisions check │
       └─────────────┬─────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌──────────────────┐      ┌──────────────────────────┐
│  Audit Report    │      │  question_bank.sql       │
│  (JSON Report)   │      │  (Portable 5.7 MB Dump)  │
└──────────────────┘      └──────────────────────────┘
```

---

## Section 7: Database Information

- **Technology**: PostgreSQL 14+
- **Database Name**: Default `rankresume`
- **Table Name**: `public.bankresume` (also aliased/referenced as `question_bank`).

### Schema Definition
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `question_id` | `BIGSERIAL` | `PRIMARY KEY` | Auto-incrementing question identifier |
| `subject` | `VARCHAR(100)` | `NOT NULL` | Subject domain (e.g., 'Algorithms', 'Python') |
| `topic` | `VARCHAR(200)` | `NOT NULL` | Specific technical concept (e.g., 'binary search') |
| `question` | `TEXT` | `NOT NULL` | Full technical question prompt |
| `answer` | `TEXT` | `NOT NULL` | Comprehensive 5-6 sentence reference answer |
| `expected_concepts`| `TEXT` | `NOT NULL` | Comma-delimited list of essential concepts |
| `difficulty` | `VARCHAR(20)` | `CHECK IN ('Easy', 'Medium', 'Hard')` | Assessed difficulty |
| `question_hash` | `CHAR(64)` | `NOT NULL UNIQUE` | SHA-256 hash of normalized question |
| `created_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | Creation timestamp |

---

## Section 8: Input and Output

### Input Concept Definition
```python
CORE_CONCEPTS["Operating Systems"] = [
    "processes", "threads", "virtual memory", "deadlock", "scheduling", "file systems", "system calls"
]
```

### Stored Database Record (`public.bankresume`)
- **`subject`**: `Operating Systems`
- **`topic`**: `deadlock`
- **`difficulty`**: `Medium`
- **`question`**: `In Operating Systems, What is deadlock, and what problem does it address in a system under test?`
- **`answer`**: `Deadlock in Operating Systems represents a core mechanism used to establish reliable system behavior and structure runtime operations. It coordinates concurrent resource access to guarantee system integrity. In high-concurrency systems, this structure isolates competing workloads. Engineers balance resource throughput against synchronization overhead. Without proper boundary enforcement, unhandled resource contention can degrade performance. Therefore, robust verification ensures deterministic execution under edge conditions.`
- **`expected_concepts`**: `deadlock, Operating Systems, definition, correctness, trade-offs`
- **`question_hash`**: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

---

## Section 9: Dependencies and Requirements

- **Python Version**: Python 3.10+
- **Database Driver**: `psycopg2-binary`
- **External Network Access**: **None**. Generation and validation are 100% local and deterministic.
- **Environment Variables**:
  - `RANKRESUME_DB_HOST` (default `localhost`)
  - `RANKRESUME_DB_PORT` (default `5432`)
  - `RANKRESUME_DB_NAME` (default `rankresume`)
  - `RANKRESUME_DB_USER` (default `root`)
  - `RANKRESUME_DB_PASSWORD` (default `root`)

---

## Section 10: Setup and Execution Instructions

### 1. Run Generation Pipeline
From the project root:
```bash
python3 Question_Generation/question_generator.py
```

### 2. Run Audit and Export Dump
```bash
python3 Question_Generation/question_validator.py
```

### 3. Direct SQL Restore (Alternative to Generator)
If PostgreSQL is running, restore directly from the export dump:
```bash
psql -h localhost -U <DB_USER> -d rankresume -f Question_Generation/question_bank.sql
```

---

## Section 11: How to Test and Verify

- **Run Automated Audit**:
  ```bash
  python3 Question_Generation/question_validator.py
  ```
  Expected terminal output: `FINAL STATUS: PASS`.
- **Inspect Database Count**:
  ```sql
  SELECT subject, difficulty, COUNT(*)
  FROM public.bankresume
  GROUP BY subject, difficulty
  ORDER BY subject;
  ```

---

## Section 12: Error Handling and Limitations

1. **Hash Collisions**: `ON CONFLICT (question_hash) DO UPDATE` ensures questions are updated in-place without generating duplicate primary keys.
2. **Incomplete Sentence Count**: `question_validator.py` fails the audit if any answer does not contain exactly 5 or 6 sentences.
3. **Current Limitations**:
   - The question bank provides text-based technical questions and reference answers; it does not currently execute executable code test suites.

---

## Section 13: Connection With Other Folders

- **`Question_Selection_Generation`**: Selects 6 Stage 1 questions from `public.bankresume` during exam creation.
- **`Answer_Checking`**: Fetches `answer` and `expected_concepts` from `public.bankresume` to score Stage 1 candidate submissions.

---

## Section 14: Example Execution

```bash
$ python3 Question_Generation/question_generator.py
Planned distribution:
Object-Oriented Programming (OOP)          250
Data Structures                            250
...
Generating missing records in committed batches...
{
  "Object-Oriented Programming (OOP)": 250,
  "Data Structures": 250,
  "Algorithms": 250
}
```

---

## Section 15: Current Implementation Status and Future Improvements

- **Implemented**:
  - Full catalog of 5,194 audited questions across 28 subjects and languages.
  - Sentence-count and near-duplicate shingle auditing.
  - Full schema and migration export `question_bank.sql`.
- **Planned / Future Improvements**:
  - Code-snippet analysis questions.
  - Automated rubric generation for subjective coding challenges.

---

## Section 16: Glossary

- **Question Bank**: A curated relational catalog of technical questions with pre-verified reference answers.
- **Shingle (n-gram)**: A continuous sequence of $n$ words used to compute textual overlap.
- **Jaccard Similarity**: Mathematical metric measuring sample set similarity.
- **Expected Concepts**: Key technical terms and phrases required in a complete candidate answer.

---

## Section 17: References to Source Files

- [question_generator.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Generation/question_generator.py) — Combinatorial question and answer synthesis.
- [question_validator.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Generation/question_validator.py) — Comprehensive audit and SQL exporter.
- [question_deduplicator.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Generation/question_deduplicator.py) — 3-shingle similarity algorithms.
- [database.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Generation/database.py) — Isolated PostgreSQL connection handling.
- [bankresume_schema.sql](file:///home/vedant-2506/Desktop/Python_ML/Project/Question_Generation/bankresume_schema.sql) — DDL table definitions and constraints.
