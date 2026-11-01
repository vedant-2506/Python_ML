# Answer_Checking

## Section 1: Folder Name and Overview

- **Folder Name**: `Answer_Checking`
- **Location**: `Project/Answer_Checking`
- **Purpose**: `Answer_Checking` is the automated natural language answer-evaluation and scoring engine of **RankResume**. It provides a rigorous, two-factor evaluation pipeline that scores subjective, free-text candidate answers against ground-truth reference answers and expected concepts without human grader fatigue.
- **Problem It Solves**: In technical assessments, evaluating descriptive candidate answers typically requires senior engineering personnel, leading to high operational costs, grading inconsistencies, and severe evaluation delays. Naive automated systems (e.g., pure keyword matching or basic string distance) fail to understand synonymous phrasing or, conversely, reward superficially similar answers that contain factual errors or contradictions.
- **Why It Is Necessary**: `Answer_Checking` combines two complementary NLP techniques into a balanced 50/50 score:
  1. **Semantic Similarity (50%)**: Measures conceptual alignment and embedding proximity using Sentence Transformers (`sentence-transformers/all-MiniLM-L6-v2`).
  2. **Factual Correctness (50%)**: Performs atomic claim extraction and Natural Language Inference (NLI) using a Cross-Encoder (`cross-encoder/nli-deberta-v3-small`) to verify whether candidate statements are entailed by, contradicted by, or unsupported by the reference facts.

---

## Section 2: Role in the Overall RankResume Project

Within RankResume, `Answer_Checking` serves as **Phase 4 (Candidate Evaluation & Final Scoring)**:

1. **Before This Module Runs**:
   - `DB_Store` has ingested candidate resumes and job descriptions.
   - `ATS_calculation` has screened and ranked top candidates.
   - `Question_Selection_Generation` has generated the 10-question technical exam (`public.question_exam` and `public.ai_question_exam`).
2. **What This Module Receives**:
   - Terminal multiline input from candidates responding to Stage 1 and Stage 2 questions (via `manual_answer_input.py` or `pipeline_assessment.py`).
   - Question metadata, ground-truth reference answers, and expected concepts from `public.question_exam` or `public.bankresume`.
3. **What Processing It Performs**:
   - Records candidate submissions in `public.answer_evaluation` with `evaluation_status = 'Pending'`.
   - Normalizes text and computes cosine similarity of dense 384-dimensional transformer embeddings.
   - Deconstructs candidate answers into atomic factual claims via `claim_extractor.py`.
   - Runs cross-encoder NLI between reference facts (premises) and candidate claims (hypotheses), classifying each claim as `Supported` (entailed), `Contradicted`, or `Unverified`.
   - Blends scores:
     $$\text{Answer Score} = (0.50 \times \text{Semantic Score}) + (0.50 \times \text{Factual Score})$$
   - Classifies answers into `Correct` ($\ge 70$), `Partially Correct` ($40\text{--}69$), or `Incorrect` ($< 40$).
   - Calculates obtained marks based on question maximum marks (Easy=6, Medium=12, Hard=18).
   - Once all 10 questions are completed, `final_result.py` computes the weighted final interview result:
     $$\text{Final Result} = (0.60 \times \text{Stage 1 Average}) + (0.40 \times \text{Stage 2 Average})$$
4. **What Output It Produces**:
   - Evaluated records in `public.answer_evaluation` with granular scores, classifications, obtained marks, and explanatory notes.
   - Consolidated exam results in `public.final_evaluation_result`.
5. **Which Module Uses Its Output Next**:
   - `Question_Selection_Generation`: Consumes Stage 1 scores via `fetch_stage1_evaluations()` to dynamically determine Stage 2 adaptive difficulty.
   - Recruiters / Frontend Dashboard: Displays detailed candidate answer reviews, factor breakdowns, and overall rank scores.
6. **Execution Independence**:
   - Can evaluate individual candidate answers via CLI (`run_evaluation.py`) or full interactive exams (`manual_answer_input.py`).
   - Relies on active PostgreSQL tables created by `Answer_Checking/sql/`.

---

## Section 3: Complete Folder Structure

```text
Answer_Checking/
├── README.md                      # Comprehensive technical documentation
├── __init__.py                    # Public API exports for answer evaluation
├── answer_evaluator.py            # Main evaluator blending semantic similarity & factual correctness
├── claim_extractor.py             # Atomic factual claim segmentation & sentence splitting
├── config.py                      # Model names, database settings & difficulty mark definitions
├── database.py                    # 724-line PostgreSQL persistence manager for answers & sessions
├── factual_correctness.py         # Cross-Encoder DeBERTa-v3 NLI pipeline & claim scoring
├── final_result.py                # 60% Stage 1 + 40% Stage 2 final weighted score aggregator
├── manual_answer_input.py         # Terminal CLI for interactive 10-question candidate exam sessions
├── requirements.txt               # Standalone dependencies for Answer_Checking
├── run_evaluation.py              # CLI utility to evaluate pending answer rows
├── semantic_similarity.py         # Sentence-Transformers MiniLM embedding & cosine similarity engine
├── sql/
│   ├── create_answer_evaluation.sql       # DDL schema for public.answer_evaluation table
│   └── create_final_evaluation_result.sql # DDL schema for public.final_evaluation_result table
└── tests/
    ├── __init__.py                # Test package marker
    ├── test_answer_evaluator.py   # Tests for score combination and mark calculations
    ├── test_assessment_workflow.py# Tests for multi-stage exam execution
    ├── test_complete_workflow.py  # End-to-end integration tests
    ├── test_database.py           # Database CRUD and query unit tests
    ├── test_factual_correctness.py# Tests for claim extraction and NLI classification
    ├── test_final_result.py       # Tests for final weighted 60/40 score aggregation
    ├── test_manual_answer_input.py# Tests for CLI input validation
    ├── test_run_evaluation.py     # Tests for batch evaluation runner
    └── test_semantic_similarity.py# Tests for embedding similarity and calibration
```

---

## Section 4: File-by-File Explanation

### 1. `Answer_Checking/config.py`
- **Purpose**: Defines configuration constants, database connection helpers, and difficulty mark mappings.
- **Key Functions**:
  - `get_max_marks_for_difficulty(difficulty, fallback=None) -> float`: Returns configured maximum marks: Easy = 6.0, Medium = 12.0, Hard = 18.0 (default fallback: 10.0).
  - `get_db_config() -> DatabaseConfig`: Reads database host, port, name, user, and password from environment variables.
  - `get_semantic_model_name()`: Returns `sentence-transformers/all-MiniLM-L6-v2`.
  - `get_nli_model_name()`: Returns `cross-encoder/nli-deberta-v3-small`.
  - `get_default_calibration_thresholds()`: Returns entailment (0.6), contradiction (0.6), and neutral (0.5) thresholds.

### 2. `Answer_Checking/claim_extractor.py`
- **Purpose**: Breaks candidate text into atomic, testable factual claims.
- **Why Required**: Candidates often write complex compound sentences. Verifying claims individually prevents an entire paragraph from being marked wrong due to a single false detail.
- **Key Functions**:
  - `normalize_text(value)`: Normalizes line endings and whitespace.
  - `split_claims(text)`: Splits text along sentence boundaries (`.!?`) and coordinating conjunctions (`and`, `but`, `however`, `although`, `therefore`, `thus`, `so`) while preserving technical context.

### 3. `Answer_Checking/semantic_similarity.py`
- **Purpose**: Computes dense vector semantic similarity between expected answers and candidate responses.
- **Why Required**: Assesses whether the candidate is discussing the correct general subject matter and concepts, even if using different wording.
- **Key Functions**:
  - `load_semantic_model()`: Caches and returns `SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')`.
  - `cosine_similarity(vec_a, vec_b) -> float`: Computes dot product over L2 norms.
  - `provisional_calibration(similarity) -> float`: Normalizes raw cosine similarity to a balanced 0–1 score.
  - `calculate_semantic_score(expected, candidate) -> tuple[float, dict]`: Returns calibrated percentage score ($0\text{--}100$) and metadata.

### 4. `Answer_Checking/factual_correctness.py`
- **Purpose**: Natural Language Inference (NLI) pipeline that checks candidate claims against reference facts.
- **Why Required**: High semantic similarity alone cannot catch factual falsehoods (e.g., stating "TCP is an unreliable, connectionless protocol" has high semantic similarity to networking definitions but is factually false).
- **Key Functions**:
  - `load_nli_model()`: Loads `AutoModelForSequenceClassification` and `AutoTokenizer` for `cross-encoder/nli-deberta-v3-small`.
  - `run_nli_prediction(premise, hypothesis) -> dict`: Computes softmax probabilities for `entailment`, `contradiction`, and `neutral`.
  - `classify_claim_status(probabilities) -> str`: Assigns `Supported`, `Contradicted`, or `Unverified`.
  - `calculate_factual_correctness(candidate_answer, expected_facts) -> dict`: Scores all extracted claims ($100\%$ for Supported, $0\%$ for Contradicted, entailment-margin for Unverified) and computes a weighted average.

### 5. `Answer_Checking/answer_evaluator.py`
- **Purpose**: Main evaluator combining semantic similarity and factual correctness into the unified answer score.
- **Key Functions**:
  - `classify_answer(answer_score) -> str`: Returns `Correct` ($\ge 70$), `Partially Correct` ($40\text{--}69$), or `Incorrect` ($< 40$).
  - `calculate_obtained_marks(answer_score, classification, max_marks) -> float`: Assigns $0.0$ if Incorrect, or $(\text{score} / 100) \times \text{max\_marks}$.
  - `evaluate_pending_record(record) -> dict`: Computes 50% semantic + 50% factual score, generates diagnostic notes, and assigns final marks.
  - `evaluate_record_by_id(evaluation_id)`: Loads row from DB, runs evaluation, and updates the record in PostgreSQL.

### 6. `Answer_Checking/database.py`
- **Purpose**: Comprehensive database operations module (724 lines) managing answer evaluations, exam queries, and status updates.
- **Key Functions**:
  - `get_question_details()`: Dynamically retrieves reference answers and expected concepts from `question_exam`, `ai_question_exam`, or `bankresume`.
  - `save_candidate_answer()`: Inserts a pending answer into `public.answer_evaluation`.
  - `get_pending_answers()`: Queries pending evaluations awaiting grading.
  - `update_evaluation_result()`: Persists evaluated scores, classification, marks, and notes.
  - `get_first_six_average()`: Computes candidate Stage 1 average score without modifying records.

### 7. `Answer_Checking/final_result.py`
- **Purpose**: Final score aggregator executed after all 10 questions are evaluated.
- **Key Functions**:
  - `calculate_and_store_final_result(exam_id, candidate_id, jd_id)`: Validates that all 10 answers are in `Completed` status, splits rows into Stage 1 (6 questions) and Stage 2 (4 questions), computes averages, calculates $0.60 \times \text{Stage 1} + 0.40 \times \text{Stage 2}$, and upserts the result into `public.final_evaluation_result`.

### 8. `Answer_Checking/manual_answer_input.py`
- **Purpose**: Interactive terminal CLI allowing candidates to complete their 10-question technical interview session.
- **Key Functions**:
  - Collects candidate ID and JD ID.
  - Creates or loads active exam session.
  - Presents Stage 1 questions one by one and records answers.
  - Automatically triggers `evaluate_pending()` after Stage 1 to enable adaptive Stage 2 generation.
  - Generates adaptive Stage 2 questions via `Question_Selection_Generation`.
  - Collects Stage 2 answers and persists final results.

### 9. `Answer_Checking/run_evaluation.py`
- **Purpose**: Background batch evaluator CLI for evaluating all pending rows in `public.answer_evaluation`.

---

## Section 5: Detailed Code Execution and Line-by-Line Analysis

### 1. Two-Factor Score Blending in `answer_evaluator.py` (Lines 40–95)
```python
def evaluate_pending_record(record: Dict[str, Any]) -> Dict[str, Any]:
    candidate_answer = record.get("candidate_answer")
    expected_answer = record.get("expected_answer")
    expected_facts = record.get("expected_facts")
    max_marks = get_max_marks_for_difficulty(record.get("difficulty"), record.get("max_marks"))

    if candidate_answer is None or not str(candidate_answer).strip():
        return {
            "semantic_score": 0.0, "factual_correctness_score": 0.0,
            "answer_score": 0.0, "classification": "Incorrect",
            "obtained_marks": 0.0, "max_marks": max_marks,
            "evaluation_status": "Completed",
            "evaluation_notes": "Candidate answer was empty; zero marks assigned."
        }

    semantic_score, semantic_meta = calculate_semantic_score(expected_answer or "", candidate_answer)
    factual_context = normalize_expected_facts(expected_facts)
    if expected_answer is not None and str(expected_answer).strip():
        factual_context.append(str(expected_answer))

    factual_result = calculate_factual_correctness(candidate_answer, factual_context)
    factual_score = factual_result.get("score")

    answer_score = 0.5 * semantic_score + 0.5 * factual_score
    classification = classify_answer(answer_score)
    obtained_marks = calculate_obtained_marks(answer_score, classification, max_marks)
```
- **Lines 47–56**: Guards against empty answers: immediately assigns 0 marks and marks evaluation `Completed`.
- **Line 58**: Computes dense vector similarity ($0\text{--}100$).
- **Lines 59–65**: Merges reference concepts and full reference answer into `factual_context`.
- **Line 67**: Runs cross-encoder NLI claim verification.
- **Line 87**: Blends 50% semantic and 50% factual correctness.
- **Lines 88–89**: Classifies performance and scales marks against question maximums.

### 2. Natural Language Inference Claim Classification in `factual_correctness.py` (Lines 210–255)
```python
for claim in claims:
    for fact in facts:
        probabilities = run_nli_prediction(fact, claim, model=model)
        status = classify_claim_status(probabilities, entailment_threshold, contradiction_threshold)
    if best_status == "Supported":
        claim_score = 100.0
    elif best_status == "Contradicted":
        claim_score = 0.0
    else:
        entailment = best_probabilities.get("entailment", 0.0)
        contradiction = best_probabilities.get("contradiction", 0.0)
        claim_score = max(0.0, (entailment - contradiction) * 100.0)
```
- For each claim, finds the best supporting or contradicting reference fact.
- Supported claims receive $100.0$; contradicted claims receive $0.0$; unverified claims receive conservative entailment-margin credit.
- Computes claim-weighted factual correctness score.

### 3. Weighted Final Result Aggregation in `final_result.py` (Lines 110–155)
```python
first_six_avg = _calculate_averages(conn, stage1_rows, divisor=6)
last_four_avg = _calculate_averages(conn, stage2_rows, divisor=4)
final_result = 0.6 * first_six_avg + 0.4 * last_four_avg
```
- Averages the 6 Stage 1 answer scores.
- Averages the 4 Stage 2 answer scores.
- Computes the final $60/40$ weighted interview score and upserts into `public.final_evaluation_result`.

---

## Section 6: Complete Workflow

```text
Candidate Input (manual_answer_input.py / terminal)
                     │
                     ▼
       ┌───────────────────────────┐
       │   save_candidate_answer   │
       │   public.answer_evaluation│
       │   status = 'Pending'      │
       └─────────────┬─────────────┘
                     │
                     ▼
       ┌───────────────────────────┐
       │  answer_evaluator.py      │
       └──────┬─────────────┬──────┘
              │             │
              ▼             ▼
     ┌────────────────┐ ┌────────────────┐
     │Semantic Engine │ │Factual Engine  │
     │SentenceTransf. │ │Claim Extractor │
     │all-MiniLM-L6-v2│ │DeBERTa-v3 NLI  │
     │(50% Weight)    │ │(50% Weight)    │
     └────────┬───────┘ └───────┬────────┘
              │                 │
              └────────┬────────┘
                       ▼
        ┌───────────────────────────┐
        │ Combined Answer Score     │
        │ 0.5 * Semantic + 0.5 * NLI│
        └──────────────┬────────────┘
                       │
                       ▼
        ┌───────────────────────────┐
        │ Classification & Marks    │
        │ Correct / Partial / Incorr│
        │ Scaled by Max Marks (6/12/18)
        └──────────────┬────────────┘
                       │
                       ▼
        ┌───────────────────────────┐
        │ Final Result Calculation  │
        │ final_result.py           │
        │ 60% Stage 1 + 40% Stage 2 │
        │ public.final_evaluation...│
        └───────────────────────────┘
```

---

## Section 7: Database Information

- **Technology**: PostgreSQL 14+
- **Database Name**: Default `rankresume`
- **Tables Managed**:

### 1. Table `public.answer_evaluation`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `evaluation_id` | `BIGSERIAL` | `PRIMARY KEY` | Unique evaluation identifier |
| `candidate_id` | `INTEGER` | | Evaluated candidate ID |
| `exam_id` | `UUID` | `REFERENCES exam_sessions(exam_id)` | Associated exam session |
| `jd_id` | `BIGINT` | `NOT NULL` | Job description ID |
| `question_id` | `BIGINT` | `NOT NULL` | Question ID |
| `expected_answer`| `TEXT` | | Ground-truth reference answer |
| `candidate_answer`| `TEXT` | | Submitted candidate text |
| `difficulty` | `VARCHAR(50)`| | Question difficulty |
| `max_marks` | `NUMERIC(10,2)`| | Maximum marks (6, 12, or 18) |
| `expected_facts`| `JSONB` | | Essential concept list |
| `semantic_score`| `NUMERIC(5,2)` | | Semantic similarity score (0–100) |
| `factual_correctness_score`| `NUMERIC(5,2)` | | Factual correctness score (0–100) |
| `answer_score` | `NUMERIC(5,2)` | | Combined answer score (0–100) |
| `classification`| `VARCHAR(30)` | | Correct / Partially Correct / Incorrect |
| `obtained_marks`| `NUMERIC(10,2)`| | Marks awarded |
| `evaluation_status`| `VARCHAR(30)` | `DEFAULT 'Pending'` | Pending / Completed / Review Required |
| `evaluation_notes`| `TEXT` | | Explanatory diagnostic notes |
| `evaluated_at` | `TIMESTAMPTZ` | `DEFAULT NOW()` | Evaluation timestamp |
| `question_source`| `VARCHAR(50)` | | 'Question Bank' or 'groq_llm' |

### 2. Table `public.final_evaluation_result`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `exam_id` | `UUID` | `NOT NULL` | Exam session identifier |
| `jd_id` | `BIGINT` | `NOT NULL` | Job description ID |
| `candidate_id` | `INTEGER` | `NOT NULL` | Candidate ID |
| `first_six_average`| `NUMERIC(5,2)` | `NOT NULL` | Unweighted average of Stage 1 scores |
| `last_four_average`| `NUMERIC(5,2)` | `NOT NULL` | Unweighted average of Stage 2 scores |
| `final_result` | `NUMERIC(5,2)` | `NOT NULL` | Blended score: $0.60 \times S1 + 0.40 \times S2$ |
| `evaluation_status`| `VARCHAR(30)` | `DEFAULT 'Completed'` | Completed / Review Required |
| `calculated_at`| `TIMESTAMPTZ` | `DEFAULT NOW()` | Calculation timestamp |
- Constraint: `UNIQUE (exam_id, candidate_id)`.

---

## Section 8: Input and Output

### Input Example
```text
Question: In Operating Systems, what is deadlock and what conditions cause it?
Candidate Answer: Deadlock occurs when multiple processes are blocked because each is holding a resource and waiting for another resource held by another process. The four Coffman conditions are mutual exclusion, hold and wait, no preemption, and circular wait.
```

### Evaluated Output Record (`public.answer_evaluation`)
- **`semantic_score`**: `92.40`
- **`factual_correctness_score`**: `95.00`
- **`answer_score`**: `93.70`
- **`classification`**: `Correct`
- **`max_marks`**: `12.00` (Medium difficulty)
- **`obtained_marks`**: `11.24`
- **`evaluation_status`**: `Completed`
- **`evaluation_notes`**: `Transformer embedding similarity with provisional calibration.; Claim-level scores were combined using configured claim weights.`

---

## Section 9: Dependencies and Requirements

- **Python Version**: Python 3.10+
- **Machine Learning & NLP Frameworks**:
  - `sentence-transformers`: Dense vector embeddings.
  - `transformers`, `torch`: Hugging Face model loading and cross-encoder inference.
  - `numpy`: Cosine similarity math.
- **Database Driver**: `psycopg2-binary`
- **NLP Models Used**:
  - `sentence-transformers/all-MiniLM-L6-v2` (~80 MB)
  - `cross-encoder/nli-deberta-v3-small` (~500 MB)
- **Environment Variables**:
  - `RANKRESUME_DB_*`: PostgreSQL database settings.
  - `ANSWER_CHECKING_SEMANTIC_MODEL`: Custom embedding model override.
  - `ANSWER_CHECKING_NLI_MODEL`: Custom NLI cross-encoder override.

---

## Section 10: Setup and Execution Instructions

### 1. Apply Database Schemas
```bash
psql -h localhost -U <DB_USER> -d rankresume -f Answer_Checking/sql/create_answer_evaluation.sql
psql -h localhost -U <DB_USER> -d rankresume -f Answer_Checking/sql/create_final_evaluation_result.sql
```

### 2. Run Interactive Terminal Exam
To start a candidate interview session:
```bash
python3 -m Answer_Checking.manual_answer_input
```

### 3. Run Batch Evaluation on Pending Submissions
To evaluate any un-evaluated answers stored in the database:
```bash
python3 -m Answer_Checking.run_evaluation
```

### 4. Calculate Final Result Manually
```bash
python3 -m Answer_Checking.final_result <EXAM_UUID> <CANDIDATE_ID> <JD_ID>
```

---

## Section 11: How to Test and Verify

- **Run Automated Test Suite**:
  ```bash
  python3 -m unittest discover Answer_Checking/tests/
  ```
- **Inspect Evaluated Submissions**:
  ```sql
  SELECT evaluation_id, question_id, semantic_score, factual_correctness_score, answer_score, obtained_marks, classification
  FROM public.answer_evaluation
  ORDER BY evaluation_id DESC LIMIT 10;
  ```
- **Inspect Final Results**:
  ```sql
  SELECT exam_id, candidate_id, first_six_average, last_four_average, final_result
  FROM public.final_evaluation_result;
  ```

---

## Section 12: Error Handling and Limitations

1. **Empty Answers**: Immediate short-circuit assigns $0.0$ score, $0.0$ marks, and `Incorrect` status without wasting GPU/CPU inference cycles.
2. **Missing Reference Facts**: If expected concepts are absent, `answer_evaluator.py` automatically uses the full reference answer for NLI context and flags the row for manual review if ambiguous.
3. **Model Availability**: If sentence transformers or torch are missing, exceptions are logged cleanly and evaluations remain in `Pending` state rather than producing corrupted scores.
4. **Current Limitations**:
   - Long essays exceeding 512 tokens may experience NLI truncation in the cross-encoder attention window.

---

## Section 13: Connection With Other Folders

- **`Question_Selection_Generation`**: Fetches question text and reference answers from `question_exam`. Provides Stage 1 percentage scores to resolve Stage 2 adaptive difficulty.
- **`Question_Generation`**: Supplies reference answers and expected concepts from `bankresume`.
- **`DB_Store`**: Reads candidate and job description records.

---

## Section 14: Example Execution

```python
from Answer_Checking.answer_evaluator import evaluate_pending_record

sample_pending_row = {
    "candidate_answer": "Encapsulation bundles data and methods together and restricts direct access to internal state.",
    "expected_answer": "Encapsulation is an OOP principle that binds data and code together and hides object internals.",
    "expected_facts": ["data hiding", "bundling data and methods", "access modifiers"],
    "difficulty": "Easy",
    "max_marks": 6.0
}

result = evaluate_pending_record(sample_pending_row)
print("Answer Score:", result["answer_score"])
print("Classification:", result["classification"])
print("Obtained Marks:", result["obtained_marks"])
# Output:
# Answer Score: 92.5
# Classification: Correct
# Obtained Marks: 5.55
```

---

## Section 15: Current Implementation Status and Future Improvements

- **Implemented**:
  - Semantic similarity using `all-MiniLM-L6-v2`.
  - Claim extraction and Natural Language Inference using `nli-deberta-v3-small`.
  - Strict 50/50 factor blending, performance classification, and mark scaling.
  - Interactive terminal exam interface (`manual_answer_input.py`).
  - Final weighted 60% Stage 1 + 40% Stage 2 score aggregator.
- **Planned / Future Improvements**:
  - LLM-based conversational follow-up questions for ambiguous candidate answers.
  - Syntax-aware AST evaluation for embedded code snippets.

---

## Section 16: Glossary

- **Semantic Similarity**: Measure of conceptual and topical relatedness between two text strings using vector embeddings.
- **Natural Language Inference (NLI)**: Determining whether a hypothesis is true (entailment), false (contradiction), or undetermined (neutral) given a premise.
- **Cross-Encoder**: A transformer architecture that processes premise and hypothesis simultaneously to calculate fine-grained interaction scores.
- **Stage 1 Average**: Unweighted average of the first 6 core CS questions.
- **Stage 2 Average**: Unweighted average of the 4 adaptive framework questions.

---

## Section 17: References to Source Files

- [answer_evaluator.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/answer_evaluator.py) — 50/50 factor combination and score classification.
- [factual_correctness.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/factual_correctness.py) — DeBERTa NLI prediction and claim-level scoring.
- [semantic_similarity.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/semantic_similarity.py) — Sentence-Transformers embedding and cosine similarity math.
- [claim_extractor.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/claim_extractor.py) — Atomic sentence and conjunction claim splitting.
- [final_result.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/final_result.py) — 60/40 final exam score aggregation.
- [database.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/database.py) — 724-line database persistence engine.
- [manual_answer_input.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/manual_answer_input.py) — Interactive exam session runner.
- [run_evaluation.py](file:///home/vedant-2506/Desktop/Python_ML/Project/Answer_Checking/run_evaluation.py) — Batch CLI evaluation runner.
