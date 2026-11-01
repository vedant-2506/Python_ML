# DB_Store

## Section 1: Folder Name and Overview

- **Folder Name**: `DB_Store`
- **Location**: `Project/DB_Store`
- **Purpose**: `DB_Store` is the foundational data-ingestion, document-parsing, skill-taxonomy, and persistence engine of **RankResume**. It reads raw candidate resumes and job descriptions from multiple document formats (`.pdf`, `.docx`, `.doc`), converts them into normalized clean text and validated structured JSON, and stores them in PostgreSQL. It also orchestrates end-to-end ATS score computation across all ingested candidates.
- **Problem It Solves**: Resumes and job descriptions come in unstructured, highly inconsistent layouts—ranging from complex multi-column PDFs to rich-text Word documents. Standardizing these into strict schemas while extracting contact metadata, educational degrees, work history, projects, certifications, and technical skills is essential for reliable algorithmic comparison.
- **Why It Is Necessary**: Machine learning models and deterministic screening algorithms cannot operate directly on raw binary files. `DB_Store` establishes an audit-ready, repeatable, and relational database foundation in PostgreSQL, backed by European Skills, Competences, Qualifications and Occupations (ESCO) standardized skill taxonomies and custom technology dictionaries.

---

## Section 2: Role in the Overall RankResume Project

Within RankResume, `DB_Store` is **Phase 1 (Data Ingestion & Persistent Foundation)**:

1. **Before This Module Runs**:
   - Recruiters or hiring managers place raw resume files into `Data/resumes/` and job description documents into `Data/jds/`.
   - Optionally, an ESCO skills taxonomy dataset is placed in the workspace (or downloaded via `import_esco_skills`).
2. **What This Module Receives**:
   - Binary document files (`.pdf`, `.docx`, `.doc`).
   - ESCO skills CSV taxonomy (`skills_en.csv`).
   - PostgreSQL database credentials from environment variables.
3. **What Processing It Performs**:
   - SHA-256 content hashing to ensure idempotent ingestion and avoid duplicate candidates.
   - Text extraction via `pdfminer.six` (for PDFs) and `docx2txt` / `python-docx` (for Word documents).
   - Regex-based contact parsing (name, email, phone number).
   - Section segmentation (Education, Experience, Projects, Skills, Certifications).
   - Technology dictionary and ESCO skills normalization.
   - JSON validation ensuring required keys and proper structure.
   - Ingestion into `public.candidate` and `public.job_description` tables.
   - Calls `ATS_calculation` to score all candidates against target job descriptions and populates `public.ats_score`.
   - Exports consolidated snapshot datasets to `Data/resumes.json` and `Data/jds.json`.
4. **What Output It Produces**:
   - Fully populated relational tables: `candidate`, `job_description`, `technology_dictionary`, `technology_alias`, `"ESCO_Skills"`, and `ats_score`.
   - JSON dataset exports used by the frontend mock server or analysis notebooks.
5. **Which Module Uses Its Output Next**:
   - `ATS_calculation`: Uses structured JSON data and database records to compute and rank candidates.
   - `Question_Selection_Generation`: Reads `job_description.structured_data` (`expected_skills`) to classify Core vs. Changeable skills and select question bank questions.
   - `Answer_Checking`: References candidate records and job descriptions during technical exam sessions.
6. **Execution Independence**:
   - The ingestion pipeline can be run as a standalone batch job (`python3 -m DB_Store.rankresume_pipeline`) or through the main project orchestrator (`run_pipeline.py`).

---

## Section 3: Complete Folder Structure

```text
DB_Store/
├── README.md                 # Comprehensive technical documentation for DB_Store
├── DB_Store_info.md          # Legacy technical overview and field mapping notes
├── __init__.py               # Package marker
├── database_setup.sql        # Complete PostgreSQL database schema and reference data dump
├── rankresume_pipeline.ipynb # Interactive Jupyter Notebook for ingestion testing & visualization
└── rankresume_pipeline.py    # Main 1,393-line ingestion, parsing, dictionary & scoring pipeline
```

---

## Section 4: File-by-File Explanation

### 1. `DB_Store/__init__.py`
- **Purpose**: Package initialization marker.
- **Why Required**: Allows Python to recognize `DB_Store` as an importable module across the repository.

### 2. `DB_Store/database_setup.sql`
- **Purpose**: Provides a full database schema creation and data loading script generated from the live `rankresume` PostgreSQL database.
- **Why Required**: Allows developers to instantiate an identical, clean database instance with predefined ESCO skill rows and technology dictionaries without re-running long extraction jobs. Candidate and job description rows are excluded to protect candidate privacy.
- **Main Tables Created**: `candidate`, `job_description`, `ats_score`, `technology_dictionary`, `technology_alias`, `"ESCO_Skills"`.

### 3. `DB_Store/DB_Store_info.md`
- **Purpose**: Technical supplementary reference detailing the extraction pipeline, text cleanup heuristics, and JSON schemas for resumes and JDs.
- **Why Required**: Preserved as architectural documentation detailing earlier design decisions and JSON validation constraints.

### 4. `DB_Store/rankresume_pipeline.ipynb`
- **Purpose**: Interactive Jupyter Notebook mirroring the execution of `rankresume_pipeline.py`.
- **Why Required**: Enables researchers and faculty mentors to visually trace document extraction, inspect parsed JSON outputs, experiment with regex patterns, and visualize ATS score distributions.

### 5. `DB_Store/rankresume_pipeline.py`
- **Purpose**: The complete core script (1,393 lines) that implements file extraction, parsing, dictionary management, schema creation, database insertion, and candidate ATS batch scoring.
- **Main Classes & Functions**:
  - `DocumentResult`: Dataclass capturing file path, raw text, clean text, metadata, and error status.
  - `sha256_file(path)`: Calculates SHA-256 file hashes to detect duplicate files.
  - `extract_pdf()`, `extract_docx()`, `extract_doc()`, `extract_text()`: Format-specific text extractors.
  - `extract_contacts()`: Regex parser for candidate name, email, and telephone.
  - `split_sections()`: Heuristic section splitter recognizing 20+ common resume headings.
  - `parse_resume()`, `parse_jd()`: Transforms raw text into validated structured JSON dictionaries.
  - `validate_resume_json()`, `validate_jd_json()`: Enforces required keys, types, and schema validity.
  - `connect_db()`: Safe PostgreSQL connection manager verifying database name.
  - `create_schema(connection, reset=False)`: Creates all required tables and indexes.
  - `import_esco_skills()`: Ingests thousands of standardized European skills from CSV into `"ESCO_Skills"`.
  - `store_candidate_ats_score()`: Evaluates candidate against JD, stores factors in `ats_score`, and updates `candidate.ats_score`.
  - `score_all_candidates()`: Iterates over all candidates, batches Gemini LLM evaluations, and persists blended scores.
  - `process_batch(connection, reset=False)`: Scans directories, extracts new files, validates data, inserts records, and exports JSON datasets.

---

## Section 5: Detailed Code Execution and Line-by-Line Analysis

`rankresume_pipeline.py` is divided into logical subsystems:

### 1. Document Extraction and Hash Deduplication (Lines 198–290)
- **Lines 204–210 (`sha256_file`)**: Computes SHA-256 digest in 64 KB chunks to uniquely identify file content regardless of file name.
- **Lines 212–246 (`extract_pdf`, `extract_docx`, `extract_doc`)**:
  - Uses `pdfminer.high_level.extract_text` to extract text from PDFs.
  - Uses `docx2txt` or `docx.Document` to iterate over paragraphs and tables in Word documents.
  - Uses `antiword` or fallback binary string decoding for legacy `.doc` files.
- **Lines 248–257 (`extract_text`)**: Dispatches file extraction based on suffix (`.pdf`, `.docx`, `.doc`).

### 2. ESCO Skills and Technology Dictionaries (Lines 290–470)
- **Lines 350–395 (`import_esco_skills`, `_upsert_esco_rows`)**: Reads `skills_en.csv`, streaming records in 1,000-row chunks using `execute_values` into `"ESCO_Skills"`.
- **Lines 398–420 (`load_esco_labels`, `load_controlled_labels`)**: Loads preferred and alternative skill labels into memory for rapid substring matching during text parsing.
- **Lines 445–468 (`_vocabulary`, `discover_skills`, `technology_matches`)**: Scans input text against loaded dictionaries and returns canonical skill names.

### 3. Resume and JD Parsing Logic (Lines 470–870)
- **Lines 499–513 (`extract_contacts`)**:
  - Email: `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`.
  - Phone: International and Indian mobile formats (`(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}`).
  - Name: Extracted from the first non-empty lines before contact blocks or headings.
- **Lines 514–540 (`split_sections`)**: Matches major headings (e.g., `EDUCATION`, `EXPERIENCE`, `PROJECTS`, `SKILLS`, `CERTIFICATIONS`).
- **Lines 583–608 (`_parse_education`)**: Parses degree names, institutions, graduation years, and percentages/GPAs.
- **Lines 609–644 (`_parse_projects`)**: Extracts project titles and bulleted technical descriptions.
- **Lines 677–692 (`_extract_experience_years_from_text`)**: Computes cumulative work duration from date ranges (`2019 - 2023`).
- **Lines 734–765 (`parse_resume`)**: Combines extracted components into a validated JSON object with keys: `candidate_name`, `email`, `phone`, `job_title`, `experience_years`, `skills`, `education`, `projects`, `certificates`.
- **Lines 845–872 (`parse_jd`)**: Parses job descriptions, extracting `job_title`, `required_skills`, `required_experience_years`, `required_education`, and `achievement_requirements`.

### 4. Database Schema Creation (Lines 969–1015)
- Executes DDL creating `candidate`, `job_description`, `ats_score`, `technology_dictionary`, `technology_alias`, and `"ESCO_Skills"` with associated indexes.

### 5. Ingestion Batch Execution in `process_batch()` (Lines 1233–1315)
- Scans `Data/resumes/` and `Data/jds/`.
- Checks if each document already exists using `filename_exists()`.
- Calculates SHA-256 digest with `sha256_file()`.
- Extracts raw text and cleans whitespace.
- Parses contact data, sections, education, experience, and skills into structured JSON.
- Validates the resulting JSON schema using `validate_resume_json()` and `validate_jd_json()`.
- Performs parameterized SQL inserts into `public.candidate` and `public.job_description`.
- Commits transactions or rolls back safely upon extraction errors.
- Runs `score_all_candidates()` to calculate ATS match scores across all candidates.
- Calls `export_datasets()` to write `Data/resumes.json` and `Data/jds.json`.

---

## Section 6: Complete Workflow

```text
Data/resumes/ (*.pdf, *.docx, *.doc)       Data/jds/ (*.pdf, *.docx, *.doc)
                 │                                        │
                 ▼                                        ▼
      ┌─────────────────────┐                  ┌─────────────────────┐
      │ SHA-256 Hash Check  │                  │ File Name / Raw Text│
      │ Duplicate Avoidance │                  │ Extraction          │
      └──────────┬──────────┘                  └──────────┬──────────┘
                 │                                        │
                 ▼                                        ▼
      ┌─────────────────────┐                  ┌─────────────────────┐
      │ Document Extraction │                  │ Job Title & Skill   │
      │ pdfminer / docx2txt │                  │ Extraction          │
      └──────────┬──────────┘                  └──────────┬──────────┘
                 │                                        │
                 ▼                                        ▼
      ┌─────────────────────┐                  ┌─────────────────────┐
      │ Contact & Section   │                  │ Structured JD JSON  │
      │ Heuristic Parsing   │                  │ Generation          │
      └──────────┬──────────┘                  └──────────┬──────────┘
                 │                                        │
                 ▼                                        ▼
      ┌─────────────────────┐                  ┌─────────────────────┐
      │ ESCO & Dictionary   │                  │ Schema Validation   │
      │ Skill Normalization │                  │ (validate_jd_json)  │
      └──────────┬──────────┘                  └──────────┬──────────┘
                 │                                        │
                 ▼                                        ▼
      ┌──────────────────────────────────────────────────────────────┐
      │                  PostgreSQL Database Store                   │
      │  Tables: public.candidate & public.job_description (JSONB)   │
      └──────────────────────────────┬───────────────────────────────┘
                                     │
                                     ▼
      ┌──────────────────────────────────────────────────────────────┐
      │  Score All Candidates (score_all_candidates)                 │
      │  - Deterministic 6-Factor ATS calculation                    │
      │  - Batch LLM evaluations (Google Gemini)                     │
      │  - Persists factors to public.ats_score                      │
      │  - Updates candidate.ats_score                               │
      └──────────────────────────────┬───────────────────────────────┘
                                     │
                                     ▼
      ┌──────────────────────────────────────────────────────────────┐
      │  Dataset Export: Data/resumes.json & Data/jds.json           │
      └──────────────────────────────────────────────────────────────┘
```

---

## Section 7: Database Information

- **Technology**: PostgreSQL 14+
- **Database Name**: Default `rankresume`
- **Tables Created and Managed**:

### 1. Table `public.candidate`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `candidate_id` | `BIGSERIAL` | `PRIMARY KEY` | Unique candidate identifier |
| `candidate_name`| `VARCHAR(150)` | | Extracted candidate name |
| `email` | `VARCHAR(150)` | | Extracted candidate email |
| `phone` | `VARCHAR(30)` | | Extracted telephone number |
| `resume_file_name`| `VARCHAR(255)`| | Source document file name |
| `resume_hash` | `VARCHAR(64)` | `UNIQUE` | SHA-256 hash of file content |
| `raw_text` | `TEXT` | | Unmodified extracted text |
| `clean_text` | `TEXT` | | Whitespace-normalized text |
| `structured_data`| `JSONB` | | Parsed resume JSON |
| `ats_score` | `FLOAT` | | Blended final ATS score |
| `created_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | Ingestion timestamp |

### 2. Table `public.job_description`
| Column | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `jd_id` | `BIGSERIAL` | `PRIMARY KEY` | Unique JD identifier |
| `job_title` | `VARCHAR(150)` | | Job title |
| `jd_file_name` | `VARCHAR(255)` | | Source JD file name |
| `raw_text` | `TEXT` | | Raw extracted JD text |
| `clean_text` | `TEXT` | | Cleaned text |
| `structured_data`| `JSONB` | | Parsed JD requirements JSON |
| `created_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | Ingestion timestamp |

### 3. Table `public.technology_dictionary` & `public.technology_alias`
- Maps tech canonical names (e.g., `postgresql`) to categories (`database`) and aliases (`postgres`, `psql`).

### 4. Table `public."ESCO_Skills"`
- Stores standardized skills, URIs, and alternate labels imported from ESCO.

---

## Section 8: Input and Output

### Input
- Files in `Data/resumes/`: `.pdf`, `.docx`, `.doc`.
- Files in `Data/jds/`: `.pdf`, `.docx`, `.doc`.

### Structured Output: Candidate `structured_data` (JSONB)
```json
{
  "name": "Jane Doe",
  "email": "jane.doe@example.com",
  "phone": "+1-555-0199",
  "job_title": "Software Engineer",
  "experience_years": 3.0,
  "skills": ["python", "postgresql", "docker", "fastapi"],
  "education": [
    {
      "degree": "Bachelor of Technology",
      "field": "Computer Science",
      "institution": "State University",
      "percentage": "82.5",
      "graduation_year": "2021"
    }
  ],
  "projects": [
    {
      "project_title": "Distributed Task Queue",
      "description": "Implemented task runner using Redis and Python."
    }
  ],
  "certificates": ["AWS Cloud Practitioner"]
}
```

### Generated Files
- `Data/resumes.json`: Consolidated JSON export of all parsed candidates.
- `Data/jds.json`: Consolidated JSON export of all parsed job descriptions.

---

## Section 9: Dependencies and Requirements

- **Python Version**: Python 3.10+
- **Document Processing**:
  - `pdfminer.six`: Robust PDF text extraction.
  - `docx2txt` / `python-docx`: DOCX parsing.
- **Database & Data**:
  - `psycopg2-binary`: PostgreSQL connection adapter.
  - `numpy`, `pandas`: Data manipulations.
- **Environment Variables**:
  - `RANKRESUME_DB_HOST` (default `localhost`)
  - `RANKRESUME_DB_PORT` (default `5432`)
  - `RANKRESUME_DB_NAME` (default `rankresume`)
  - `RANKRESUME_DB_USER` (default `root`)
  - `RANKRESUME_DB_PASSWORD` (default `root`)
  - `RANKRESUME_JD_ID`: Target JD ID to score against (default: `2`).

---

## Section 10: Setup and Execution Instructions

### 1. Database Creation
In PostgreSQL, create the `rankresume` database:
```sql
CREATE DATABASE rankresume;
```

### 2. Populate Reference Schema & ESCO Data
Execute `database_setup.sql`:
```bash
psql -h localhost -U <DB_USER> -d rankresume -f DB_Store/database_setup.sql
```

### 3. Run Batch Ingestion Pipeline
To ingest all resumes and JDs from `Data/` and compute initial ATS scores:
```bash
python3 -m DB_Store.rankresume_pipeline
```

---

## Section 11: How to Test and Verify

- **Check Ingestion Counts**:
  ```sql
  SELECT COUNT(*) FROM public.candidate;
  SELECT COUNT(*) FROM public.job_description;
  ```
- **Inspect Structured Data**:
  ```sql
  SELECT candidate_name, email, structured_data->'skills' AS skills
  FROM public.candidate
  LIMIT 5;
  ```
- **Check ATS Scoring**:
  ```sql
  SELECT candidate_id, jd_id, rule_based_score, llm_based_score
  FROM public.ats_score
  ORDER BY id DESC LIMIT 5;
  ```

---

## Section 12: Error Handling and Limitations

1. **Corrupt Files**: If a file cannot be extracted, `DocumentResult.error` captures the traceback; the error is logged to `Data/logs/rankresume.log` and the pipeline continues with the remaining files.
2. **Duplicate Detection**: Uses SHA-256 hash checks (`resume_hash UNIQUE`). Re-running ingestion automatically skips already-processed files without duplicates.
3. **Database Guardrails**: `connect_db()` verifies `SELECT current_database()` and refuses to operate against system databases (`postgres`, `template0`).
4. **Current Limitations**:
   - Scanned image PDFs without OCR text layers cannot be extracted by `pdfminer.six`. (Resumes must contain selectable text).

---

## Section 13: Connection With Other Folders

- **`ATS_calculation`**: Invoked by `score_all_candidates()` via `evaluate_candidate_against_jd`, `combine_ats_scores`, and `get_batch_gemini_evaluations`.
- **`Question_Selection_Generation`**: Consumes `job_description.structured_data` to classify skills for interview question selection.
- **`Answer_Checking`**: Consumes candidate identifiers and job description IDs to track exam attempts.

---

## Section 14: Example Execution

```bash
$ python3 -m DB_Store.rankresume_pipeline
[INFO] Scanning resumes directory: found 85 supported files
[INFO] Scanning JDs directory: found 12 supported files
[INFO] [1/85] Checking resume: John_Doe_Python_Developer.pdf
[INFO] New resume detected; extracting and processing: John_Doe_Python_Developer.pdf
[INFO] Successfully inserted resume: John_Doe_Python_Developer.pdf
...
[INFO] Scoring candidates against JD ID 2...
[INFO] ATS score calculated in hybrid mode for Candidate 1: 82.50
[INFO] Exported datasets to Data/resumes.json and Data/jds.json
==================================================
INGESTION SUMMARY:
  Resumes Processed: 85 (Success: 85, Skipped: 0, Failed: 0)
  JDs Processed: 12 (Success: 12, Skipped: 0, Failed: 0)
==================================================
```

---

## Section 15: Current Implementation Status and Future Improvements

- **Implemented**:
  - Multi-format text extraction (`.pdf`, `.docx`, `.doc`).
  - SHA-256 document deduplication.
  - Section segmentation and contact entity extraction.
  - ESCO taxonomy import and custom technology dictionaries.
  - PostgreSQL schema and JSONB structured data persistence.
  - Batch ATS calculation and JSON dataset export.
- **Planned / Future Improvements**:
  - OCR integration (e.g., Tesseract) for scanned image resumes.
  - Webhook or cloud bucket (AWS S3) listeners for real-time document upload.

---

## Section 16: Glossary

- **ESCO**: European Skills, Competences, Qualifications and Occupations taxonomy providing standard terminology for job skills.
- **JSONB**: PostgreSQL binary JSON data type supporting indexing and rich query operators.
- **SHA-256**: Cryptographic 256-bit hash used to verify document uniqueness.
- **Deduplication**: Process of preventing identical files from creating duplicate candidate records.

---

## Section 17: References to Source Files

- [rankresume_pipeline.py](file:///home/vedant-2506/Desktop/Python_ML/Project/DB_Store/rankresume_pipeline.py) — Complete ingestion, parsing, database operations, and scoring.
- [database_setup.sql](file:///home/vedant-2506/Desktop/Python_ML/Project/DB_Store/database_setup.sql) — DDL statements, indexes, and reference dataset exports.
- [DB_Store_info.md](file:///home/vedant-2506/Desktop/Python_ML/Project/DB_Store/DB_Store_info.md) — Technical field mapping and architectural specifications.
