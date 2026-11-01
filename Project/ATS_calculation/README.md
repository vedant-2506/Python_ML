# ATS_calculation

## Section 1: Folder Name and Overview

- **Folder Name**: `ATS_calculation`
- **Location**: `Project/ATS_calculation`
- **Purpose**: The `ATS_calculation` module is the algorithmic screening engine of **RankResume**. It computes an automated Applicant Tracking System (ATS) match score (ranging strictly from 0 to 100) between candidate resumes and job descriptions (JDs).
- **Problem It Solves**: In high-volume recruitment, manual evaluation of hundreds of heterogeneous resumes against technical job descriptions is time-consuming, prone to human fatigue, and inconsistent. This module provides a deterministic, explainable, and multi-layered scoring pipeline combining normalized rule-based keyword/tenure extraction with optional state-of-the-art Large Language Model (Gemini / Ollama) semantic understanding.
- **Why It Is Necessary**: Raw text similarity algorithms (like pure TF-IDF or naive string matching) miss domain synonyms (e.g., recognizing that "k8s" implies "kubernetes", or that "PostgreSQL" satisfies a relational database requirement). Conversely, relying purely on LLM API calls introduces prohibitive latency, cost, and rate-limit fragility. `ATS_calculation` balances precision, speed, and resilience through a calibrated **60% Rule-Based + 40% LLM Hybrid Blend**.

---

## Section 2: Role in the Overall RankResume Project

Within the RankResume architecture, `ATS_calculation` serves as **Phase 2 (Candidate Screening & Shortlisting)**:

1. **Before This Module Runs**:
   - `DB_Store` ingests raw resume files (`.pdf`, `.docx`, `.doc`) and job descriptions from `Data/resumes/` and `Data/jds/`.
   - `DB_Store` extracts raw text, performs contact parsing, normalizes skills via ESCO taxonomies, and saves structured JSON into PostgreSQL tables `public.candidate` and `public.job_description`.
2. **What This Module Receives**:
   - The structured JSON representations of candidate resumes (`skills`, `experience_years`, `education`, `projects`, `certificates`, `job_title`) and job descriptions (`required_skills`, `required_experience_years`, `required_education`, `achievement_requirements`, `job_title`).
   - A database connection object (`psycopg2.extensions.connection`) and a target `jd_id`.
3. **What Processing It Performs**:
   - Evaluates six deterministic factors: Keyword Strength (35%), Project Similarity (20%), Title Relevance (10%), Experience Tenure (15%), Education Degree/Marks (15%), and Certification/Achievement Coverage (5%).
   - Normalizes applicable factors when job descriptions omit optional fields (e.g., when a JD does not specify a degree or certification).
   - Queries an LLM evaluator (Google Gemini with exponential backoff / retry handling, or local Ollama) to obtain a semantic match score and analytical critique.
   - Computes a blended final ATS score:
     $$\text{Final ATS} = (\text{Rule Score} \times 0.60) + (\text{LLM Score} \times 0.40)$$
     *(or falls back safely to 100% Rule Score if LLM is disabled or throttled).*
4. **What Output It Produces**:
   - An `ATSFactorResult` dataclass instance containing granular sub-factor scores, evidence strings, effective weights, and the blended final score.
   - Persisted evaluation records in table `public.ats_score` and updated scalar score in `public.candidate.ats_score`.
   - Ranked candidate leaderboards via `ranking.py`.
5. **Which Module Uses Its Output Next**:
   - `Question_Selection_Generation` and `pipeline_screening.py` take the top-ranked candidates to initiate the Stage 1 & Stage 2 adaptive technical interview sessions.
6. **Execution Independence**:
   - Scoring functions (`evaluate_candidate_against_jd`, `combine_ats_scores`) can run purely in-memory on raw dictionary inputs without database access.
   - Database operations (`store_candidate_ats_score`, `rank_candidates`) require active PostgreSQL tables populated by `DB_Store`.

---

## Section 3: Complete Folder Structure

```text
ATS_calculation/
├── README.md                      # Comprehensive technical documentation for ATS calculation
├── __init__.py                    # Public API exports for scoring, ranking, and blending
├── ats_calculator.py              # Central scoring coordinator, score blending & factor orchestration
├── ranking.py                     # Competition ranking and leaderboard generation with tie handling
├── rule_based/                    # Deterministic 6-factor evaluation sub-package
│   ├── __init__.py                # Package exports for rule-based calculations
│   ├── rule_based_calculator.py   # Complete 6-factor scoring algorithms and ATSFactorResult dataclass
│   └── text_utils.py              # Text canonicalization, tokenization, stemming, date parsing & alias mapping
└── LLM_based/                     # LLM evaluation sub-package
    ├── __init__.py                # Package exports for LLM scoring functions
    └── llm_scorer.py              # Google Gemini API client, rate-limiting circuit breaker & prompt builder
```

---

## Section 4: File-by-File Explanation

### 1. `ATS_calculation/__init__.py`
- **Purpose**: Defines the top-level package namespace and exposes clean public imports.
- **Why Required**: Allows pipeline components (like `pipeline_screening.py` and `DB_Store/rankresume_pipeline.py`) to import core scoring functions (`evaluate_candidate_against_jd`, `combine_ats_scores`, `rank_candidates`) directly from `ATS_calculation`.
- **Main Exports**: `ATSFactorResult`, `RULE_WEIGHT`, `calculate_keyword_score`, `combine_ats_scores`, `compute_final_ats`, `compute_rule_based_score`, `evaluate_candidate_against_jd`, `extract_numeric_score`, `get_batch_gemini_evaluations`, `get_ollama_evaluation`, `get_ollama_score`, `reset_gemini_failure_state`, `rank_candidates`.

### 2. `ATS_calculation/ats_calculator.py`
- **Purpose**: Serves as the central facade coordinating deterministic rule scoring and LLM scoring.
- **Why Required**: Separates the high-level policy of score blending from the low-level parsing mechanics.
- **Key Constants & Functions**:
  - `RULE_WEIGHT = 0.60`: The global ratio defining the 60% rule / 40% LLM blend.
  - `combine_ats_scores(rule_score, llm_score, rule_weight=0.60) -> float`: Clamps inputs between 0.0 and 100.0, blends available scores, and rounds to two decimal places. If `llm_score` is `None`, returns `round(rule_score, 2)`.
  - `compute_final_ats(jd, resume, model=None, use_llm=True) -> dict`: Evaluates candidate dictionary data against JD, invokes LLM if enabled, and returns a dictionary with full factor breakdowns and scoring mode (`"hybrid"` or `"rule-only"`).

### 3. `ATS_calculation/ranking.py`
- **Purpose**: Generates candidate competition rankings based on saved `ats_score` values in PostgreSQL.
- **Why Required**: Recruiters need an ordered candidate leaderboard where identical scores share equal competition ranks (standard "1224" competition ranking).
- **Key Function**:
  - `rank_candidates(connection, jd_id=None) -> list[dict]`: Queries `candidate` and `ats_score` tables ordered by `c.ats_score DESC, c.candidate_id ASC`. Preserves equal rank for ties and returns a list of dictionaries with `rank`, `candidate_id`, `candidate_name`, and `ats_score`.

### 4. `ATS_calculation/rule_based/__init__.py`
- **Purpose**: Initializes the deterministic evaluation sub-package.
- **Main Exports**: `ATSFactorResult`, `calculate_keyword_score`, `compute_rule_based_score`, `evaluate_candidate_against_jd`.

### 5. `ATS_calculation/rule_based/rule_based_calculator.py`
- **Purpose**: Implements the multi-criteria deterministic evaluation algorithm across six distinct dimensions.
- **Why Required**: Provides objective, explainable, and reproducible scores without external API latency.
- **Key Data Structures**:
  - `WEIGHTS`: Dictionary defining base factor weights: `{"keyword": 0.35, "similarity": 0.20, "title": 0.10, "experience": 0.15, "education": 0.15, "achievement": 0.05}`.
  - `SIMILARITY_BOOST = 1.6`: Calibration multiplier compensating for sparse lexical overlap.
  - `ATSFactorResult`: Dataclass storing individual factor scores, total `rule_based_score`, `weighted_details`, `evidence` strings, `applicable_factors`, and `effective_weights`.
- **Key Functions**:
  - `_keyword_strength()`: Evaluates single skill coverage using direct match, substring containment, implied terms (`IMPLIED_BY`), token coverage, and fuzzy sequence matching (threshold $\ge 0.88$).
  - `_keyword_analysis()`: Iterates over all JD skills, computing percentage match and compiling lists of matched vs. missing skills.
  - `_similarity_score()`: Computes lexical or semantic overlap between JD requirements and candidate project descriptions.
  - `_estimate_title_similarity()`: Compares JD job title against candidate titles.
  - `_calculate_experience_score()`: Compares candidate years to required years using a diminishing-return power curve ($100 \times (\text{candidate} / \text{required})^{0.7}$).
  - `_calculate_education_score()`: Evaluates degree level hierarchy (PhD=5, Master=4, Bachelor=3, Diploma=2, 12th=1) and normalized percentage marks.
  - `_achievement_score()`: Measures required certifications against candidate records.
  - `evaluate_candidate_against_jd()`: Orchestrates all factors, dynamically re-normalizes weights for missing JD criteria, and returns `ATSFactorResult`.

### 6. `ATS_calculation/rule_based/text_utils.py`
- **Purpose**: Provides low-level text normalization, tokenization, stemming, alias canonicalization, and date/tenure parsing.
- **Why Required**: Real-world resumes contain inconsistent casing, punctuation, abbreviations ("k8s", "py"), and varied date formats ("2021 - Present", "3 yrs 6 mos").
- **Key Dictionaries & Functions**:
  - `ALIASES`: Maps technical abbreviations to canonical names (e.g., `"k8s": "kubernetes"`, `"postgres": "postgresql"`, `"oops": "object oriented programming"`).
  - `IMPLIED_BY`: Maps high-level competencies to concrete evidence (e.g., `"version control"` implied by `git`, `github`, `gitlab`).
  - `_normalize_text()`: Strips non-alphanumeric symbols and standardizes spaces.
  - `_canon()`: Applies alias replacements to normalized text.
  - `_stem()`: Strips common suffixes (`ing`, `ed`, `es`, `s`).
  - `_parse_years()`: Parses date ranges, month tallies, and year intervals from text or nested structures.

### 7. `ATS_calculation/LLM_based/__init__.py`
- **Purpose**: Initializes the LLM-based assessment sub-package.
- **Main Exports**: `extract_numeric_score`, `get_batch_gemini_evaluations`, `get_ollama_evaluation`, `get_ollama_score`, `reset_gemini_failure_state`.

### 8. `ATS_calculation/LLM_based/llm_scorer.py`
- **Purpose**: Manages communication with Google Gemini (via `google-genai` SDK) or local Ollama models.
- **Why Required**: Provides contextual understanding of candidates who may describe competencies without using exact keywords, while preventing rate-limit crashes during large batch ingestion.
- **Key Mechanisms**:
  - **Thread-safe Rate Limiting**: `_throttle()` enforces delay between calls based on `GEMINI_RPM` (default: 15 requests per minute).
  - **Circuit Breaker**: If non-retryable errors (400, 401, 403, 404) or prolonged quota exhaustion occur, `_block_gemini()` trips the circuit breaker to prevent application hangs, falling back cleanly to rule-based scores.
  - **Exponential Backoff**: Transient errors (408, 429, 500, 502, 503, 504) trigger retries respecting the server's `Retry-After` header or jittered exponential delays (up to 90 seconds).
  - `get_batch_gemini_evaluations()`: Scores candidates in configurable batches with incremental callbacks (`on_batch`).

---

## Section 5: Detailed Code Execution and Line-by-Line Analysis

### 1. Score Combination in `ats_calculator.py` (Lines 26–42)
```python
def combine_ats_scores(
    rule_score: float, llm_score: Optional[float], rule_weight: float = RULE_WEIGHT
) -> float:
    rule = _clamp(_coerce_float(rule_score))
    if llm_score is None:
        return round(rule, 2)
    llm = _clamp(_coerce_float(llm_score))
    return round(rule * rule_weight + llm * (1 - rule_weight), 2)
```
- **Lines 28–29**: Coerces `rule_score` to float and clamps it between 0.0 and 100.0.
- **Lines 30–31**: If LLM scoring was disabled, throttled, or returned null, the function gracefully degrades to the pure rule-based score.
- **Lines 32–33**: Coerces and clamps `llm_score`, calculates the weighted sum:
  $$\text{Combined} = (\text{rule} \times 0.60) + (\text{llm} \times 0.40)$$
  and returns the score rounded to two decimal places.

### 2. Weight Normalization in `rule_based_calculator.py` (Lines 500–535)
```python
scores = {
    "keyword": keyword, "similarity": similarity, "title": title,
    "experience": experience, "education": education, "achievement": achievement,
}
applicable = {
    key: value is not None and value > 0
    for key, value in scores.items()
}

total_weight = sum(WEIGHTS[k] for k, ok in applicable.items() if ok)
if total_weight <= 0:
    rule_based_score = round(_clamp((keyword or 0.0) + (similarity or 0.0) * 0.5), 2)
else:
    effective = {k: (WEIGHTS[k] / total_weight if ok and total_weight else 0.0) for k, ok in applicable.items()}
    weighted = {k: (scores[k] or 0.0) * effective[k] for k in scores}
    base_score = sum(weighted.values())
    if base_score < 50 and keyword and similarity:
        base_score = min(100.0, base_score + (50 - base_score) * 0.35)
    rule_based_score = round(_clamp(base_score), 2)
```
- **Lines 504–508**: Identifies which criteria are actually present. If a JD doesn't mention required certifications, `achievement` evaluates to `None` and is marked non-applicable.
- **Lines 513–518**: Sums the base weights of applicable factors. Calculates `effective_weights` by renormalizing so their sum equals $1.0$ (100%).
- **Lines 520–523**: If a candidate has strong core skills and similarity, a safety floor prevents optional missing factors from collapsing the score below 50.

### 3. Keyword Scoring in `rule_based_calculator.py` (Lines 55–85)
```python
def _keyword_strength(keyword: str, skills: list[str], skill_set: set[str],
                      resume_text: str, text_tokens: set[str]) -> float:
    if keyword in skill_set:
        return 1.0
    kpad = f" {keyword} "
    for s in skills:
        if kpad in f" {s} ":
            return 0.95
    if kpad in resume_text:
        return 0.9
    for term in IMPLIED_BY.get(keyword, ()):
        term_toks = set(_tokens(term, stem=True))
        if term_toks and term_toks <= text_tokens:
            return 0.7
```
- **Line 57**: Exact match in candidate skill list awards a full strength of $1.0$ (100%).
- **Lines 58–61**: Substring containment (e.g., "python" in "python programming") awards $0.95$.
- **Lines 64–65**: Mention in free text (projects or summary) awards $0.90$.
- **Lines 66–69**: Implied competence (e.g., "git" evidencing "version control") awards $0.70$.
- **Lines 76–78**: SequenceMatcher handles spelling variations (e.g., ratio $\ge 0.88$ awards $0.90$).

### 4. Gemini Request Throttling and Generation in `llm_scorer.py` (Lines 54–65, 217–280)
- **Lines 54–65**: `_throttle()` acquires a thread lock, measures elapsed time since the previous call, and sleeps if required to strictly adhere to `GEMINI_RPM`.
- **Lines 220–260**: `_generate()` constructs API call options with structured JSON output response schema:
  `{"score": <number 0-100>, "reason": "<1-2 sentences>"}`.
- **Lines 265–290**: Traps `google.genai.errors.APIError`. Inspects HTTP error status codes. If HTTP 429 occurs, parses `retry-after` headers and sleeps; if quota is completely exhausted, logs the outage and trips the circuit breaker without crashing the pipeline.

---

## Section 6: Complete Workflow

```text
Job Description JSON & Candidate Resume JSON
                     │
                     ▼
       ┌───────────────────────────┐
       │   ATS Calculator Engine   │
       └─────────────┬─────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌──────────────────┐      ┌──────────────────────────┐
│ 6-Factor Rules   │      │ LLM Scorer (Gemini)      │
│ - Keyword (35%)  │      │ - Rate-limit check       │
│ - Project (20%)  │      │ - Structured Prompt      │
│ - Title (10%)    │      │ - JSON parsing & score   │
│ - Exp (15%)      │      │   extraction             │
│ - Edu (15%)      │      │ - Circuit breaker safety │
│ - Ach (5%)       │      └────────────┬─────────────┘
└────────┬─────────┘                   │
         │ (Rule Score: 0-100)         │ (LLM Score: 0-100 or None)
         └────────────┬────────────────┘
                      ▼
        ┌───────────────────────────┐
        │   Score Blending Engine   │
        │   60% Rule + 40% LLM      │
        │   (or 100% Rule Fallback) │
        └─────────────┬─────────────┘
                      ▼
         Final ATS Match Score (0-100)
                      │
         ┌────────────┴────────────┐
         ▼                         ▼
┌──────────────────┐      ┌──────────────────────────┐
│  Database Store  │      │ Candidate Ranking        │
│  public.ats_score│      │ Competition rank ties    │
│  candidate.score │      │ Top-N Candidate Filter   │
└──────────────────┘      └──────────────────────────┘
```

---

## Section 7: Database Information

The module interacts with PostgreSQL using `psycopg2`.

- **Database Name**: Default `rankresume` (configurable via `RANKRESUME_DB_NAME`).
- **Connection**: Managed via connection objects passed from `DB_Store.rankresume_pipeline.connect_db()`.
- **Tables Read & Written**:

### 1. Table `public.ats_score`
Stores the detailed breakdown of every ATS evaluation run.
| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `SERIAL PRIMARY KEY` | Unique evaluation record ID |
| `candidate_id` | `INTEGER REFERENCES candidate(candidate_id)` | Evaluated candidate |
| `jd_id` | `INTEGER` | Target job description |
| `keyword_score` | `NUMERIC(5,2)` | Skill keyword match (0–100) |
| `similarity_score` | `NUMERIC(5,2)` | Project textual similarity (0–100) |
| `title_score` | `NUMERIC(5,2)` | Job title relevance (0–100) |
| `experience_score` | `NUMERIC(5,2)` | Experience tenure match (0–100) |
| `education_score` | `NUMERIC(5,2)` | Education level & grade score (0–100) |
| `achievement_score`| `NUMERIC(5,2)` | Certificate / achievement score (0–100) |
| `rule_based_score` | `NUMERIC(5,2)` | Combined 6-factor deterministic score |
| `llm_based_score`  | `NUMERIC(5,2)` | Semantic score from Gemini / Ollama |
| `computed_at`      | `TIMESTAMP` | Record timestamp (default `NOW()`) |

### 2. Table `public.candidate`
- **Updated Column**: `ats_score` (`FLOAT`).
- **Query**:
  ```sql
  UPDATE candidate SET ats_score = %s WHERE candidate_id = %s;
  ```

### 3. Table `public.job_description`
- **Read Columns**: `jd_id`, `job_title`, `structured_data`.

### 4. Ranking Query in `ranking.py`
```sql
SELECT c.candidate_id, c.candidate_name, c.ats_score
FROM candidate c
JOIN ats_score a ON a.candidate_id = c.candidate_id
WHERE a.jd_id = %s AND c.ats_score IS NOT NULL
ORDER BY c.ats_score DESC, c.candidate_id ASC;
```

---

## Section 8: Input and Output

### Input Format (Example Candidate JSON)
```json
{
  "candidate_name": "Jane Doe",
  "job_title": "Software Engineer",
  "skills": ["Python", "PostgreSQL", "Docker", "Git"],
  "experience_years": 3.5,
  "education": [
    {"degree": "B.Tech in Computer Science", "percentage": "82.5"}
  ],
  "projects": [
    {
      "title": "E-Commerce Microservice",
      "description": "Developed backend services using Python, FastAPI, and PostgreSQL."
    }
  ],
  "certificates": ["AWS Certified Cloud Practitioner"]
}
```

### Output Format (`compute_final_ats`)
```json
{
  "rule_based_score": 84.50,
  "llm_based_score": 80.00,
  "llm_reason": "Candidate shows strong Python and database expertise matching 4 of 5 core requirements.",
  "final_ats_score": 82.70,
  "scoring_mode": "hybrid",
  "factors": {
    "keyword_score": 90.0,
    "similarity_score": 82.4,
    "title_score": 85.0,
    "experience_score": 100.0,
    "education_score": 80.0,
    "achievement_score": 70.0,
    "rule_based_score": 84.5,
    "effective_weights": {
      "keyword": 0.35,
      "similarity": 0.20,
      "title": 0.10,
      "experience": 0.15,
      "education": 0.15,
      "achievement": 0.05
    },
    "evidence": {
      "keyword": "Matched 4 of 5 required keywords. Missing: kubernetes.",
      "experience": "Candidate ~3.5 yrs vs required 3.0 yrs."
    }
  }
}
```

---

## Section 9: Dependencies and Requirements

- **Python Version**: Python 3.10+ (tested on Python 3.12).
- **Core Libraries**:
  - `psycopg2-binary`: PostgreSQL database adapter.
  - `google-genai`: Official Google Gemini Python SDK.
  - `python-dotenv`: Environment variable loader.
  - `numpy`: Numerical utilities.
- **Optional Libraries**:
  - `sentence-transformers`: For local semantic embeddings if sentence transformers are activated for title/project scoring.
- **Environment Variables**:
  - `GEMINI_API_KEY`: API key for Google Gemini model calls.
  - `GEMINI_MODEL`: Model identifier (default: `models/gemini-3.1-flash-lite`).
  - `GEMINI_RPM`: Requests per minute limit (default: `15`).
  - `GEMINI_TIMEOUT`: Timeout in seconds (default: `120`).
  - `RANKRESUME_REFRESH_LLM_SCORES`: If set to `"1"`, recomputes LLM evaluations instead of reusing existing ones.

---

## Section 10: Setup and Execution Instructions

### 1. Activate Environment and Install Requirements
From the project root:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Ensure `.env` at the project root contains:
```env
RANKRESUME_DB_HOST=localhost
RANKRESUME_DB_PORT=5432
RANKRESUME_DB_NAME=rankresume
RANKRESUME_DB_USER=<DB_USER>
RANKRESUME_DB_PASSWORD=<DB_PASSWORD>
GEMINI_API_KEY=<YOUR_GEMINI_KEY>
```

### 3. Run Standalone Test / Verification
To test rule and LLM scoring on sample data:
```bash
python3 test_llm_scorer.py
```

### 4. Run End-to-End ATS Scoring via Main Pipeline
```bash
python3 run_pipeline.py --jd-id 2 --top-n 5
```

---

## Section 11: How to Test and Verify

- **Unit Verification**:
  Run `test_llm_scorer.py` to confirm that:
  - Numeric score extraction (`extract_numeric_score`) parses integers, floats, slash formats (`"85/100"`), and JSON key-values.
  - Gemini client initializes cleanly or skips gracefully when `GEMINI_API_KEY` is omitted.
- **Database Inspection**:
  Verify score persistence via SQL:
  ```sql
  SELECT candidate_id, jd_id, rule_based_score, llm_based_score, computed_at
  FROM public.ats_score
  ORDER BY id DESC LIMIT 5;
  ```

---

## Section 12: Error Handling and Limitations

1. **Missing JD Criteria**: When a job description does not specify certifications or years of experience, `rule_based_calculator.py` automatically normalizes effective weights across present criteria.
2. **API Quota & Rate Limits (HTTP 429)**: The built-in circuit breaker catches API exceptions, inspects `Retry-After` headers, waits up to 90 seconds, and trips open if failures persist. In all failure cases, the module falls back to 100% rule-based scoring without terminating the pipeline.
3. **Missing Experience/Titles (Freshers)**: Students and fresher resumes without corporate job titles are not penalized with zero scores; title and experience factors adjust dynamically based on candidate data.
4. **Current Limitations**:
   - Complex nested projects in unconventional PDF layouts may have imperfect section boundary detection if the resume text is poorly formatted.

---

## Section 13: Connection With Other Folders

- **`DB_Store`**: Reads candidate and JD records saved by `DB_Store/rankresume_pipeline.py`. Saves computed scores back to `public.ats_score` and `public.candidate`.
- **`Question_Selection_Generation`**: Reads the ranked candidate list produced by `ranking.py` to pick candidates qualifying for adaptive technical exams.
- **`Answer_Checking`**: Does not directly interface with ATS calculations; however, candidates advancing through `ATS_calculation` take exams scored by `Answer_Checking`.

---

## Section 14: Example Execution

```python
from ATS_calculation.ats_calculator import compute_final_ats

sample_jd = {
    "job_title": "Python Developer",
    "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "required_experience_years": 2.0,
    "required_education": [{"degree": "Bachelor of Engineering"}]
}

sample_resume = {
    "job_title": "Backend Engineer",
    "skills": ["Python", "Django", "PostgreSQL", "Git"],
    "experience_years": 2.5,
    "education": [{"degree": "B.E. Computer Science", "percentage": "78"}],
    "projects": [{"title": "API Engine", "description": "Built Python REST APIs with PostgreSQL"}]
}

result = compute_final_ats(sample_jd, sample_resume, use_llm=False)
print(f"Final Score: {result['final_ats_score']} ({result['scoring_mode']})")
# Output: Final Score: 81.25 (rule-only)
```

---

## Section 15: Current Implementation Status and Future Improvements

- **Implemented**:
  - Deterministic 6-factor rule-based scoring with dynamic weight re-normalization.
  - Term canonicalization, stemming, alias expansion, and implied competence mapping.
  - Google Gemini API integration with rate throttling and exponential retry.
  - Resilient circuit breaker mechanism falling back to deterministic scores.
  - Competition ranking preserving identical ranks for score ties.
  - SQL schema and tables for detailed factor auditing.
- **Planned / Future Improvements**:
  - Local cross-encoder embedding integration for completely offline semantic similarity.
  - Fine-grained multi-lingual skill dictionary support.

---

## Section 16: Glossary

- **ATS (Applicant Tracking System)**: Automated software used by recruiters to filter and rank resumes based on job relevance.
- **Rule-Based Scoring**: Deterministic, mathematical evaluation based on explicit keyword, degree, and tenure rules.
- **LLM-Based Scoring**: Evaluative scoring using a Large Language Model prompt that assesses qualitative fit and depth.
- **Hybrid Blend**: A weighted combination ($60\% \text{ Rule} + 40\% \text{ LLM}$) that merges objective keyword verification with subjective language understanding.
- **Circuit Breaker**: A software resilience pattern that stops issuing external API calls when recurring errors or quota limits are detected.
- **Competition Ranking**: A ranking convention where tied candidates receive the same rank and subsequent ranks skip numbers (e.g., ranks 1, 2, 2, 4).

---

## Section 17: References to Source Files

- [ats_calculator.py](file:///home/vedant-2506/Desktop/Python_ML/Project/ATS_calculation/ats_calculator.py) — Score combination, factor evaluation facade.
- [ranking.py](file:///home/vedant-2506/Desktop/Python_ML/Project/ATS_calculation/ranking.py) — Database candidate ranking queries and tie-handling.
- [rule_based/rule_based_calculator.py](file:///home/vedant-2506/Desktop/Python_ML/Project/ATS_calculation/rule_based/rule_based_calculator.py) — 6-factor algorithmic formulas and `ATSFactorResult`.
- [rule_based/text_utils.py](file:///home/vedant-2506/Desktop/Python_ML/Project/ATS_calculation/rule_based/text_utils.py) — Normalization, regexes, tokenization, and date parsers.
- [LLM_based/llm_scorer.py](file:///home/vedant-2506/Desktop/Python_ML/Project/ATS_calculation/LLM_based/llm_scorer.py) — Gemini API integration, prompt generation, throttling, and circuit breaker.
