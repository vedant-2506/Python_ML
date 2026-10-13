# Answer_Checking

This module adds a lightweight answer-evaluation workflow for RankResume. It stores submitted candidate answers in PostgreSQL, evaluates them with a two-factor NLP score, and saves the results in a separate `answer_evaluation` table without changing the existing `question_exam` table.

## 1. Overview

The workflow has two separate steps:

1. Submit a candidate answer manually from the terminal.
2. Run evaluation to score the saved answer against the expected answer and metadata.

This module intentionally keeps the work focused on:

- Semantic Similarity (50%)
- Factual Correctness (50%)

It does not add a separate Information Coverage factor.

## 2. Folder structure

```text
Answer_Checking/
├── __init__.py
├── config.py
├── database.py
├── manual_answer_input.py
├── claim_extractor.py
├── semantic_similarity.py
├── factual_correctness.py
├── answer_evaluator.py
├── run_evaluation.py
├── requirements.txt
├── README.md
├── sql/
│   └── create_answer_evaluation.sql
└── tests/
    ├── __init__.py
    ├── test_database.py
    ├── test_manual_answer_input.py
    ├── test_semantic_similarity.py
    ├── test_factual_correctness.py
    └── test_answer_evaluator.py
```

## 3. Purpose of each file

- `config.py`: reads database and model configuration from environment variables.
- `database.py`: handles PostgreSQL connections, validation, answer insertion, and updates.
- `manual_answer_input.py`: asks the user for JD ID and candidate ID, then collects answers to the six Stage 1 questions in order.
- `claim_extractor.py`: splits candidate writing into smaller claim-like units.
- `semantic_similarity.py`: embeds expected and candidate answers and computes similarity.
- `factual_correctness.py`: compares claims to verified facts using an NLI-style comparison.
- `answer_evaluator.py`: calculates final scores, classification, and marks.
- `run_evaluation.py`: evaluates pending records and prints an execution summary.
- `sql/create_answer_evaluation.sql`: creates the evaluation table without dropping data.
- `tests/`: unit tests for the module.

## 4. Required libraries

Install the dependencies using:

```bash
python -m pip install -r Answer_Checking/requirements.txt
```

This project expects the following packages:

- `psycopg2-binary`
- `numpy`
- `sentence-transformers` (`>=3.0,<6.0`)
- `transformers` (`>=4.40,<5.0`)
- `torch` (`>=2.2,<2.14`)
- `pytest`

The Torch upper bound avoids a CPU-only accelerator initialization failure
observed with Torch 2.14.1 and Transformers 5.19.0. The bounded versions are
listed in both project and module requirements files.

## 5. Database configuration

This module connects to the existing RankResume PostgreSQL database. The default values are:

- host: `localhost`
- port: `5432`
- database: `rankresume`
- user: `postgres`
- password: from `RANKRESUME_DB_PASSWORD`

Environment variables used by the module:

```bash
export RANKRESUME_DB_HOST=localhost
export RANKRESUME_DB_PORT=5432
export RANKRESUME_DB_NAME=rankresume
export RANKRESUME_DB_USER=postgres
export RANKRESUME_DB_PASSWORD='your-local-password'
```

The project does not create a new database.

## 6. Existing input table: question_exam

The live schema stores question data in `public.question_exam`. The relevant fields in the database include:

- `jd_id`
- `question_id`
- `question`
- `reference_answer`
- `expected_concepts`
- `difficulty`
- `skill`
- `created_at`

The module maps `question_exam.reference_answer` to the evaluation's `expected_answer` field because that is the real column in the current database.

The module does not add `candidate_answer` to `question_exam` and does not modify any rows there.

## 7. New table: answer_evaluation

The new table stores both the saved question context and the computed evaluation result.

Example structure:

```sql
CREATE TABLE IF NOT EXISTS public.answer_evaluation (
    evaluation_id BIGSERIAL PRIMARY KEY,
    candidate_id INTEGER,
    jd_id BIGINT NOT NULL,
    question_id BIGINT NOT NULL,
    expected_answer TEXT,
    candidate_answer TEXT,
    difficulty VARCHAR(50),
    max_marks NUMERIC(10, 2),
    expected_facts JSONB,
    semantic_score NUMERIC(5, 2),
    factual_correctness_score NUMERIC(5, 2),
    answer_score NUMERIC(5, 2),
    classification VARCHAR(30),
    obtained_marks NUMERIC(10, 2),
    evaluation_status VARCHAR(30) NOT NULL DEFAULT 'Pending',
    evaluation_notes TEXT,
    evaluated_at TIMESTAMPTZ DEFAULT NOW()
);
```

The schema script adds `candidate_id` to an existing table without replacing
evaluation rows. It drops any previous `attempt_id` or `legacy_attempt_id`
column; historical attempt identifiers are not retained. The schema script
also removes the obsolete `first_six_average` column if present.

Status values include:

- `Pending`
- `Completed`
- `Review Required`
- `Failed`

## 8. Candidate answer storage

A candidate answer is stored in `answer_evaluation`, not in `question_exam`.

When the user submits candidate answers, the module:

- stores a positive integer `candidate_id` (for example, 1, 2, or 3) with all
  six answers,
- validates that `jd_id` and `question_id` belong to an existing `question_exam` row,
- retrieves the expected answer and metadata,
- saves the candidate answer,
- leaves `question_exam` untouched,
- stores `evaluation_status = 'Pending'`.

## 9. Running manual submission

From the project root, run:

```bash
python -m Answer_Checking.manual_answer_input
```

The terminal asks for:

- JD ID
- Candidate ID
- Each of the six Stage 1 questions in database order, followed by its answer

Answers may be multiline. Type `done` on a separate line after each answer, then
type `finish` after the sixth answer to complete the submission.

Each answer is saved into `answer_evaluation` with status `Pending`.

## 10. Evaluating saved answers

From the project root, run:

```bash
python -m Answer_Checking.run_evaluation
```

The script reads pending rows, evaluates them, and writes the result back to the same evaluation row.

You can also evaluate one specific row:

```bash
python -m Answer_Checking.run_evaluation --evaluation-id 12
```

Or limit the batch size:

```bash
python -m Answer_Checking.run_evaluation --limit 5
```

Only rows with status `Pending` can be evaluated or updated. Evaluation writes
are conditional on the row still being `Pending`, so a concurrent or manually
reviewed result is not replaced.

### Safely retrying transformer-fallback rows

After installing the corrected dependencies, first inspect the candidate rows:

```sql
SELECT evaluation_id, jd_id, question_id, candidate_answer,
       evaluation_status, evaluation_notes
FROM public.answer_evaluation
WHERE evaluation_status = 'Review Required'
  AND evaluation_notes LIKE '%Fallback heuristic used; transformer model unavailable.%'
ORDER BY evaluation_id;
```

Confirm the three evaluation IDs and candidate answers are the intended rows
and have not been manually reviewed. Requeue only those confirmed IDs, retaining
the candidate answers:

```sql
BEGIN;

UPDATE public.answer_evaluation
SET evaluation_status = 'Pending',
    evaluation_notes = 'Requeued for transformer-backed evaluation.'
WHERE evaluation_id IN (<confirmed_id_1>, <confirmed_id_2>, <confirmed_id_3>)
  AND evaluation_status = 'Review Required'
  AND evaluation_notes = 'Unverified claims received conservative entailment-margin scores; manual review is recommended.; Fallback heuristic used; transformer model unavailable.';

-- Inspect the returned IDs. If exactly the three confirmed rows were updated, run COMMIT.
-- If the returned rows do not match, run ROLLBACK instead.
```

Then evaluate each confirmed ID (one command per ID):

```bash
python -m Answer_Checking.run_evaluation --evaluation-id <confirmed_id>
```

The update is guarded by both the prior status and prior notes, and the evaluator
will only persist results while the row remains `Pending`. If the preview shows
different notes, do not broaden the update predicate; inspect the row and decide
whether it is safe to retry. A row manually marked `Completed` will not match or
be overwritten.

## 11. Semantic Similarity

Semantic similarity uses transformer sentence embeddings.

Suggested model:

```text
sentence-transformers/all-MiniLM-L6-v2
```

The NLI model defaults to `cross-encoder/nli-deberta-v3-small`. Both names can
be overridden with `ANSWER_CHECKING_SEMANTIC_MODEL` and
`ANSWER_CHECKING_NLI_MODEL`. Transformer initialization or inference errors are
logged with their exception traceback and raised; the evaluator does not
silently substitute lexical heuristics.

The process is:

1. Normalize both texts.
2. Create embeddings for the expected and candidate answers.
3. Compute cosine similarity.
4. Convert it into a score using a calibration function.

Formula:

```text
similarity = dot(E, C) / (norm(E) * norm(C))
semantic_score = 100 * g(similarity)
```

Where:

- `E` = expected answer embedding
- `C` = candidate answer embedding
- `g()` = calibration mapping from similarity to 0..1

Important:

- Raw cosine similarity is not automatically treated as a validated grading score.
- The mapping is configurable.
- If no real calibration data is available, the module uses a clearly labelled provisional mapping.

## 12. Factual Correctness

This module extracts claims from the candidate answer and compares each claim against verified facts.

### Claim extraction

A claim is a meaningful statement such as a sentence or a clause that carries a fact.

Example:

```text
Overfitting happens when a model memorizes training data.
```

This can be separated into claims such as:

- Overfitting happens when a model memorizes training data.
- A model that memorizes training data may fail to generalize to unseen data.

The extractor keeps technical and negative conditions intact so it does not distort meaning.

### NLI-style comparison

For each claim and relevant fact the system evaluates:

```text
premise = validated fact
hypothesis = candidate claim
```

The model yields:

- `pE` = entailment probability
- `pC` = contradiction probability
- `pN` = neutral probability

with:

```text
pE + pC + pN = 1
```

For the configured DeBERTa model, the model card maps output indices
`0=contradiction`, `1=entailment`, and `2=neutral`. The evaluator reads the
model's own label mapping and applies softmax to its CrossEncoder logits.

Claim status is assigned as:

- Supported
- Contradicted
- Unverified

Supported and contradicted claims receive scores of 100 and 0 respectively.
Unverified claims receive a conservative score based on the entailment-minus-contradiction probability margin, and the answer remains marked `Review Required`. Missing reference facts still require review without producing a factual score.

### Claim weights

The default provisional weighting is:

- Essential fact = 3
- Important fact = 2
- Supporting fact = 1

If the metadata does not provide importance, the module uses a default weight rather than guessing that the answer is fully correct.

## 13. Final score and classification

The final score uses exactly two factors:

```text
answer_score = 0.50 * semantic_score + 0.50 * factual_correctness_score
```

Classification rules:

```text
IF answer_score >= 70:
    classification = "Correct"
ELSE IF answer_score >= 40:
    classification = "Partially Correct"
ELSE:
    classification = "Incorrect"
```

### Stage 1 aggregation

The per-answer score above remains unchanged. The first-six average is
calculated on demand when `run_evaluation` processes answers. It is available
only when the latest evaluation for each of six distinct Stage 1 questions in
the same `(candidate_id, jd_id)` is either `Completed` or `Review Required` with a
finite score from 0 to 100. Review Required scores are included in a provisional
candidate average; their review status is preserved, and that
average is not evidence that their scores have been manually approved. Pending
or Failed latest evaluations prevent an average.
Duplicate submissions contribute at most one score per question; the latest
evaluation ID is authoritative.
An explicitly submitted empty answer contributes its evaluated zero, while an
unanswered question contributes nothing. A null candidate-answer value is not
treated as an explicit empty submission and prevents aggregation for that
candidate.

The average is printed by the evaluation command, not stored in
`answer_evaluation`. No `question_exam` schema changes are made.

### Future final score

The separate Stage 2 evaluation module and its table are intentionally not
created here. Once that schema is available, the intended final score is:

```text
A6 = SUM(first six answer scores) / 6
A4 = SUM(last four answer scores) / 4
final_score = 0.60 * A6 + 0.40 * A4
```

The final score remains on a 0–100 scale. A future summary may store the
candidate ID, JD ID, both averages, final score, and completion status;
that summary is deferred until the Stage 2 schema is defined.

## 14. Marks calculation

```text
IF classification == "Incorrect":
    obtained_marks = 0
ELSE:
    obtained_marks = (answer_score / 100) * max_marks
```

Question maximum marks are assigned from the question difficulty, case-insensitively:

| Difficulty | Maximum marks |
|------------|---------------|
| Easy       | 6             |
| Medium     | 12            |
| Hard       | 18            |

The difficulty-derived maximum is applied during submission and evaluation, including to older pending records with a previous maximum stored. Unknown or missing difficulty retains an existing `max_marks`; if none is stored, the legacy default of 10 is used.

## 15. Empty answer handling

If the candidate answer is empty, whitespace-only, or `NULL`:

```text
semantic_score = 0
factual_correctness_score = 0
answer_score = 0
classification = "Incorrect"
obtained_marks = 0
```

The evaluation row is still saved with `Completed` status.
For aggregation, an explicitly stored empty string is a submitted answer;
a null candidate-answer value is not included as a zero.

## 16. Example input and output

Example manual input:

```text
Enter JD ID: 1
Enter Candidate ID: 7
Question 1: What is overfitting?
Enter Candidate Answer:
(Type done on a separate line when this answer is complete)
Overfitting occurs when a model memorizes training data.
done
...
Type finish to complete submission: finish
```

Example saved evaluation result:

```text
evaluation_id = 12
jd_id = 1
question_id = 5
classification = "Partially Correct"
semantic_score = 76.4
factual_correctness_score = 62.5
answer_score = 69.45
obtained_marks = 6.94
evaluation_status = "Completed"
```

## 17. Inspecting database results

You can inspect the table directly with SQL:

```sql
SELECT *
FROM public.answer_evaluation
ORDER BY evaluation_id DESC;
```

Filter by question:

```sql
SELECT *
FROM public.answer_evaluation
WHERE question_id = 5
ORDER BY evaluation_id DESC;
```

Filter by status:

```sql
SELECT *
FROM public.answer_evaluation
WHERE evaluation_status = 'Pending';
```

## 18. Running tests

From the project root:

```bash
python -m pytest Answer_Checking/tests
```

The unit tests avoid repeated model downloads by mocking external NLP calls.

## 19. Missing metadata and review status

Some metadata may not exist in the current project schema. In the current RankResume setup:

- `question_exam` stores `difficulty` and `reference_answer`
- `expected_concepts` can be used as a provisional fact source
- `max_marks` is not available in the project question schema, so it is assigned from `difficulty` when an answer is submitted

When metadata is missing, the module marks the result as `Review Required` rather than silently using a fabricated number.

## 20. Limitations

This module is designed for the two requested scoring factors only.

It is not a full proof engine for algorithm correctness. For questions that ask a candidate to write code or pseudocode:

- semantic similarity may be high even when the logic is wrong,
- NLI compares wording and facts, not execution correctness,
- uncertain algorithmic logic should be flagged for review.

Do not execute arbitrary candidate text as code. The scoring system remains limited to semantic similarity and factual correctness.

## 21. Troubleshooting

Common issues:

- `question_exam` row not found: check `jd_id` and `question_id` values.
- PostgreSQL connection failure: check `RANKRESUME_DB_*` environment variables.
- Missing model packages: install `Answer_Checking/requirements.txt`.
- `Review Required`: usually caused by missing metadata or insufficiently reliable factual verification.

## 22. Example summary output

```text
========================================
       ANSWER EVALUATION SUMMARY
========================================

Total Pending Answers: 5
Successfully Evaluated: 4
Review Required: 1
Failed Evaluations: 0
========================================
```
