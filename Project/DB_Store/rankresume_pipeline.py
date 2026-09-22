"""RankResume document ingestion and PostgreSQL storage pipeline."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
import psycopg2
from docx import Document
from psycopg2.extras import Json

PROJECT_ROOT = "/home/vedant-2506/Desktop/Python_ML/Project/DB_Store"
RESUMES_DIR = str(Path(PROJECT_ROOT) / "Data" / "resumes")
JDS_DIR = str(Path(PROJECT_ROOT) / "Data" / "jds")

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "rankresume"
DB_USER = "root"
DB_PASSWORD = "root"
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc"}

LOGGER = logging.getLogger("rankresume")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

TECHNOLOGIES = [
    ("C++", "programming_language", ["cpp", "c plus plus"]),
    ("C#", "programming_language", ["csharp"]),
    (".NET", "framework", ["dotnet", "asp.net", "aspnet"]),
    ("Node.js", "runtime", ["node", "nodejs"]),
    ("React.js", "framework", ["react", "reactjs"]),
    ("Next.js", "framework", ["next", "nextjs"]),
    ("CI/CD", "tool", ["cicd", "continuous integration"]),
    ("Java", "programming_language", []),
    ("Python", "programming_language", []),
    ("Machine Learning", "concept", ["ml"]),
    ("Deep Learning", "concept", ["dl"]),
    ("SQL", "database", []),
    ("PL/SQL", "database", ["plsql"]),
    ("Spring Boot", "framework", ["spring"]),
    ("MySQL", "database", []),
    ("PostgreSQL", "database", ["postgres", "postgresql"]),
    ("Git", "tool", []),
    ("GitHub", "tool", []),
    ("AWS", "cloud", []),
    ("Communication", "soft_skill", []),
    ("Leadership", "soft_skill", []),
    ("Teamwork", "soft_skill", ["team work"]),
    ("Problem Solving", "soft_skill", ["problem-solving"]),
    ("Time Management", "soft_skill", []),
    ("Presentation", "soft_skill", []),
    ("JavaScript", "programming_language", ["js"]),
    ("HTML5", "markup", ["html"]),
    ("CSS3", "stylesheet", ["css"]),
    ("Docker", "tool", []),
    ("PyTorch", "framework", []),
    ("NumPy", "library", []),
    ("Pandas", "library", []),
    ("REST API", "concept", ["rest apis", "restful api"]),
]

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
    "has", "have", "he", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "will", "with", "you", "your",
}

SECTION_ALIASES = {
    "skills": "skills", "technical skills": "skills", "key skills": "skills",
    "education": "education", "academic qualifications": "education",
    "academic background": "education", "projects": "projects", "project": "projects",
    "experience": "experience", "work experience": "experience",
    "professional experience": "experience", "internship": "experience",
    "certifications": "certifications", "certificates": "certifications",
    "certificate": "certifications",
}


def _token_pattern(value: str) -> re.Pattern[str]:
    escaped = re.escape(value.strip())
    left = r"(?<![A-Za-z0-9])" if value[0].isalnum() else r""
    right = r"(?![A-Za-z0-9])" if value[-1].isalnum() else r""
    return re.compile(left + escaped + right, re.IGNORECASE)


@dataclass
class DocumentResult:
    path: Path
    raw_text: str
    file_hash: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_pdf(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages).strip()


def extract_docx(path: Path) -> str:
    document = Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(part for part in parts if part and part.strip()).strip()


def extract_doc(path: Path) -> str:
    """Use local antiword/libreoffice only; never upload a DOC externally."""
    antiword = shutil.which("antiword")
    if antiword:
        completed = subprocess.run([antiword, str(path)], check=True, capture_output=True, text=True)
        return completed.stdout.strip()

    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if libreoffice:
        with tempfile.TemporaryDirectory() as temporary_directory:
            subprocess.run(
                [libreoffice, "--headless", "--convert-to", "txt:Text", "--outdir", temporary_directory, str(path)],
                check=True,
                capture_output=True,
                text=True,
            )
            output = Path(temporary_directory) / f"{path.stem}.txt"
            if output.exists():
                return output.read_text(encoding="utf-8", errors="replace").strip()
    raise RuntimeError("No local .doc reader available; install antiword or LibreOffice")


def extract_text(path: Path) -> str:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return extract_pdf(path)
    if extension == ".docx":
        return extract_docx(path)
    if extension == ".doc":
        return extract_doc(path)
    raise ValueError(f"Unsupported extension: {extension}")


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip())


def technology_matches(text: str) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    entries = sorted(TECHNOLOGIES, key=lambda item: max([len(item[0]), *(len(alias) for alias in item[2])]), reverse=True)
    for canonical, _, aliases in entries:
        for candidate in [canonical, *aliases]:
            for match in _token_pattern(candidate).finditer(text):
                matches.append((match.start(), match.end(), canonical))
    selected: list[tuple[int, int, str]] = []
    for item in sorted(matches, key=lambda value: (value[0], -(value[1] - value[0]))):
        if not any(item[0] < existing[1] and existing[0] < item[1] for existing in selected):
            selected.append(item)
    return list(dict.fromkeys(canonical for _, _, canonical in selected))


def clean_text(text: str) -> str:
    """Protect known terms before generic punctuation and stopword handling."""
    normalized = normalize_whitespace(text)
    protected: dict[str, str] = {}
    candidates: list[tuple[str, str]] = []
    for index, (canonical, _, aliases) in enumerate(TECHNOLOGIES):
        marker = f"__rankresume_tech_{index}__"
        protected[marker] = canonical
        candidates.extend((candidate, marker) for candidate in [canonical, *aliases])
    candidates.sort(key=lambda item: len(item[0]), reverse=True)
    combined = re.compile(
        "|".join(
            (r"(?<![A-Za-z0-9])" if candidate[0].isalnum() else "")
            + re.escape(candidate)
            + (r"(?![A-Za-z0-9])" if candidate[-1].isalnum() else "")
            for candidate, _ in candidates
        ),
        re.IGNORECASE,
    )
    replacement_by_lower = {candidate.lower(): marker for candidate, marker in candidates}
    normalized = combined.sub(lambda match: replacement_by_lower[match.group(0).lower()], normalized)
    normalized = normalized.lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    words = [word for word in normalized.split() if word not in STOPWORDS]
    cleaned = " ".join(words)
    for marker, canonical in protected.items():
        cleaned = re.sub(rf"\b{marker}\b", canonical, cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_contacts(raw_text: str) -> dict[str, str | None]:
    email = re.search(r"\b[\w.+-]+@[\w.-]+\.\w{2,}\b", raw_text)
    phone_candidates = re.findall(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", raw_text)
    phone = next((re.sub(r"\s+", " ", value).strip() for value in phone_candidates if len(re.sub(r"\D", "", value)) >= 9), None)
    first_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    name = None
    for line in first_lines[:5]:
        if "@" not in line and not re.search(r"\d", line) and 1 < len(line.split()) <= 5:
            candidate = re.sub(r"[^A-Za-z .'-]", "", line).strip()
            if candidate:
                name = candidate
                break
    return {"name": name, "email": email.group(0) if email else None, "phone": phone}


def split_sections(raw_text: str) -> dict[str, str]:
    sections = {name: [] for name in {"skills", "education", "projects", "experience", "certifications", "other"}}
    current = "other"
    for line in normalize_whitespace(raw_text).splitlines():
        heading = re.sub(r"[^a-z ]", "", line.lower()).strip()
        matched = next((value for key, value in sorted(SECTION_ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True) if heading == key), None)
        if matched:
            current = matched
        else:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _lines(text: str) -> list[str]:
    return [line.strip(" •-*\t") for line in text.splitlines() if line.strip(" •-*\t")]


def _score(text: str) -> str:
    match = re.search(r"\b(?:cgpa|gpa|sgpa)\s*[:=-]?\s*\d+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*%", text, re.I)
    return match.group(0).strip() if match else ""


def parse_resume(raw_text: str) -> dict[str, Any]:
    sections = split_sections(raw_text)
    skills = technology_matches(sections["skills"] or raw_text)
    education = []
    for line in _lines(sections["education"]):
        degree = re.sub(r"\s+", " ", line).strip()
        education.append({"degree": degree, "mark": _score(line)})
    projects = []
    for line in _lines(sections["projects"]):
        title, _, description = line.partition(":")
        projects.append({"project_title": title.strip(), "skill": technology_matches(line), "description": description.strip() or line, "duration": ""})
    experience = []
    for line in _lines(sections["experience"]):
        experience.append({"job_role": line, "skills": technology_matches(line), "duration": ""})
    certificates = []
    for line in _lines(sections["certifications"]):
        certificates.append({"certificate_title": line, "skills": technology_matches(line), "duration": ""})
    return {"skill": list(dict.fromkeys(skills)), "education": education, "project": projects, "experience": experience, "certificate": certificates}


def extract_job_title(raw_text: str) -> str | None:
    for line in normalize_whitespace(raw_text).splitlines()[:12]:
        match = re.search(r"(?:job title|position|role|designation)\s*[:\-]\s*(.+)", line, re.I)
        if match:
            return match.group(1).strip()
    for line in normalize_whitespace(raw_text).splitlines()[:5]:
        if 1 < len(line.split()) <= 8 and not re.search(r"@|\d{3}", line):
            return line.strip(" :-")
    return None


def parse_jd(raw_text: str, job_title: str | None) -> dict[str, Any]:
    skills = list(dict.fromkeys(technology_matches(raw_text)))
    education = []
    for match in re.finditer(r"((?:bachelor|master|b\.?tech|m\.?tech|b\.?sc|m\.?sc|degree)[^.!\n]{0,100})", raw_text, re.I):
        education.append({"degree": match.group(1).strip(), "percentage/mark": _score(match.group(1))})
    experience = []
    for match in re.finditer(r"([^.!\n]{0,100}\b\d+(?:\.\d+)?\+?\s+years?[^.!\n]{0,100})", raw_text, re.I):
        experience.append({"skill": technology_matches(match.group(1)), "years": re.search(r"\d+(?:\.\d+)?\+?\s+years?", match.group(1), re.I).group(0)})
    certificates = [line.strip() for line in normalize_whitespace(raw_text).splitlines() if re.search(r"certif|certification", line, re.I)]
    return {"job_title": job_title or "", "expected_skills": skills, "expected_education": education, "expected_experience": experience, "expected_certificate": certificates, "expected_extra_skills": []}


def connect_db():
    connection = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database();")
        current_database = cursor.fetchone()[0]
    if current_database != DB_NAME or current_database in {"postgres", "template0", "template1"}:
        connection.close()
        raise RuntimeError(f"Refusing database operation against {current_database!r}")
    return connection


def inspect_tables(connection) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
        return [row[0] for row in cursor.fetchall()]


def reset_rankresume_tables(connection) -> None:
    tables = inspect_tables(connection)
    LOGGER.info("Existing public tables before reset: %s", tables)
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS candidate CASCADE")
        cursor.execute("DROP TABLE IF EXISTS job_description CASCADE")
        cursor.execute("DROP TABLE IF EXISTS technology_dictionary CASCADE")
    connection.commit()


def create_schema(connection, reset: bool = False) -> None:
    if reset:
        reset_rankresume_tables(connection)
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidate (
                candidate_id BIGSERIAL PRIMARY KEY, candidate_name VARCHAR(150), email VARCHAR(150), phone VARCHAR(30),
                resume_file_name VARCHAR(255), resume_hash VARCHAR(64) UNIQUE, raw_text TEXT, clean_text TEXT,
                structured_data JSONB, ats_score FLOAT, final_score FLOAT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS job_description (
                jd_id BIGSERIAL PRIMARY KEY, job_title VARCHAR(150), jd_file_name VARCHAR(255), raw_text TEXT,
                clean_text TEXT, structured_data JSONB, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS technology_dictionary (
                tech_id BIGSERIAL PRIMARY KEY, canonical_name VARCHAR(100) NOT NULL, category VARCHAR(50),
                aliases JSONB, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    connection.commit()


def seed_dictionary(connection) -> None:
    with connection.cursor() as cursor:
        for canonical, category, aliases in TECHNOLOGIES:
            cursor.execute("""
                INSERT INTO technology_dictionary (canonical_name, category, aliases)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (canonical, category, Json(aliases)))
    connection.commit()


def resolve_input_dirs() -> tuple[Path, Path]:
    resumes, jds = Path(RESUMES_DIR), Path(JDS_DIR)
    if resumes.is_dir() and jds.is_dir():
        return resumes, jds
    legacy_resumes = Path(PROJECT_ROOT).parent / "Data" / "resumes"
    legacy_jds = Path(PROJECT_ROOT).parent / "Data" / "jds"
    if legacy_resumes.is_dir() and legacy_jds.is_dir():
        LOGGER.warning("Requested DB_Store/Data paths are missing; using existing project Data/ directories explicitly.")
        return legacy_resumes, legacy_jds
    return resumes, jds


def files_in(directory: Path) -> list[Path]:
    return sorted(path for path in directory.iterdir() if path.is_file()) if directory.is_dir() else []


def process_batch(connection, reset: bool = False) -> dict[str, int]:
    create_schema(connection, reset=reset)
    seed_dictionary(connection)
    resumes_dir, jds_dir = resolve_input_dirs()
    summary = {"resume_found": 0, "resume_success": 0, "duplicates": 0, "resume_failed": 0, "resume_unsupported": 0, "jd_found": 0, "jd_success": 0, "jd_failed": 0, "jd_unsupported": 0}
    resume_files = files_in(resumes_dir)
    jd_files = files_in(jds_dir)
    summary["resume_found"], summary["jd_found"] = len(resume_files), len(jd_files)
    known_hashes: set[str] = set()
    with connection.cursor() as cursor:
        cursor.execute("SELECT resume_hash FROM candidate")
        known_hashes.update(row[0] for row in cursor.fetchall())
        cursor.execute("SELECT jd_file_name FROM job_description")
        known_jd_files = {row[0] for row in cursor.fetchall()}
        for path in resume_files:
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                summary["resume_unsupported"] += 1
                LOGGER.warning("Unsupported resume: %s (%s)", path.name, path.suffix.lower())
                continue
            try:
                digest = sha256_file(path)
                if digest in known_hashes:
                    summary["duplicates"] += 1
                    LOGGER.info("Duplicate resume skipped: %s", path.name)
                    continue
                raw = extract_text(path)
                contacts = extract_contacts(raw)
                cursor.execute("""
                    INSERT INTO candidate (candidate_name, email, phone, resume_file_name, resume_hash, raw_text, clean_text, structured_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (contacts["name"], contacts["email"], contacts["phone"], path.name, digest, raw, clean_text(raw), Json(parse_resume(raw))))
                known_hashes.add(digest)
                summary["resume_success"] += 1
            except Exception as error:
                summary["resume_failed"] += 1
                LOGGER.exception("Resume failed: file=%s type=%s stage=processing error=%s", path.name, path.suffix.lower(), error)
        for path in jd_files:
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                summary["jd_unsupported"] += 1
                LOGGER.warning("Unsupported JD: %s (%s)", path.name, path.suffix.lower())
                continue
            if path.name in known_jd_files:
                LOGGER.info("JD already stored; skipped: %s", path.name)
                continue
            try:
                raw = extract_text(path)
                title = extract_job_title(raw)
                cursor.execute("""
                    INSERT INTO job_description (job_title, jd_file_name, raw_text, clean_text, structured_data)
                    VALUES (%s, %s, %s, %s, %s)
                """, (title, path.name, raw, clean_text(raw), Json(parse_jd(raw, title))))
                known_jd_files.add(path.name)
                summary["jd_success"] += 1
            except Exception as error:
                summary["jd_failed"] += 1
                LOGGER.exception("JD failed: file=%s type=%s stage=processing error=%s", path.name, path.suffix.lower(), error)
    connection.commit()
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM candidate")
        summary["candidate_records"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM job_description")
        summary["jd_records"] = cursor.fetchone()[0]
    return summary


def print_summary(summary: dict[str, int]) -> None:
    print("=" * 40)
    print("RankResume DB Store Summary")
    print("=" * 40)
    print(f"\nResume files found: {summary['resume_found']}\nSuccessfully processed: {summary['resume_success']}\nDuplicates skipped: {summary['duplicates']}\nFailed: {summary['resume_failed']}\nUnsupported: {summary['resume_unsupported']}")
    print(f"\nJD files found: {summary['jd_found']}\nSuccessfully processed: {summary['jd_success']}\nFailed: {summary['jd_failed']}\nUnsupported: {summary['jd_unsupported']}")
    print(f"\nDatabase: {DB_NAME}\nCandidate records: {summary['candidate_records']}\nJob Description records: {summary['jd_records']}\n")
    print("=" * 40)
