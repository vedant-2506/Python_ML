"""RankResume document ingestion and PostgreSQL storage pipeline."""

from __future__ import annotations

import hashlib
import csv
import json
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
from psycopg2.extras import Json, execute_values

try:
    from skill_extractor import extract_skills as extract_external_skills
except ImportError as error:  # Keep imports usable for schema-only notebook cells.
    extract_external_skills = None
    SKILL_EXTRACTOR_IMPORT_ERROR = error

PROJECT_ROOT = "/home/vedant-2506/Desktop/Python_ML/Project/DB_Store"
DATA_ROOT = Path(PROJECT_ROOT).parent / "Data"
RESUMES_DIR = str(DATA_ROOT / "resumes")
JDS_DIR = str(DATA_ROOT / "jds")

DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "rankresume"
DB_USER = "root"
DB_PASSWORD = "root"
RESUME_EXTENSIONS = {".pdf", ".docx", ".doc"}
JD_EXTENSIONS = RESUME_EXTENSIONS | {".csv", ".json"}
SUPPORTED_EXTENSIONS = RESUME_EXTENSIONS
ESCO_SEARCH_ROOT = Path("/home/vedant-2506/Downloads")
ESCO_REQUIRED_COLUMNS = {
    "conceptType", "conceptUri", "skillType", "reuseLevel", "preferredLabel",
    "altLabels", "hiddenLabels", "status", "modifiedDate", "scopeNote",
}

LOGGER = logging.getLogger("rankresume")
if not LOGGER.handlers:
    DATA_ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(DATA_ROOT / "logs" / "rankresume.log", encoding="utf-8")
    ])

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

CONTROLLED_SKILLS = [
    ("unit testing", "testing", ["unit tests", "software testing"]),
    ("code review", "software_development", ["code reviews"]),
    ("version control", "development_tool", []),
    ("object-oriented programming", "computer_science", ["object oriented programming", "oop"]),
    ("data structures", "computer_science", ["data structure"]),
    ("algorithms", "computer_science", ["algorithm"]),
    ("debugging", "software_development", []),
    ("troubleshooting", "software_development", []),
    ("bug fixing", "software_development", ["fix bugs", "fixing bugs"]),
    ("frontend development", "frontend", ["front-end development", "front end development"]),
    ("backend development", "backend", ["back-end development", "back end development"]),
    ("web development", "web_technology", []),
    ("mobile application development", "software_development", ["mobile app development", "mobile applications", "mobile application"]),
    ("logical reasoning", "soft_skill", []),
    ("collaboration", "soft_skill", ["collaborative", "collaboratively"]),
    ("agile", "methodology", ["agile methodology"]),
    ("scrum", "methodology", []),
]

NORMALIZATION_ALIASES = {
    "communication skills": "communication",
    "verbal communication": "communication",
    "problem-solving skills": "problem solving",
    "problem solving skills": "problem solving",
    "rest apis": "restful api",
    "rest api": "restful api",
    "restful apis": "restful api",
    "object oriented programming": "object-oriented programming",
    "object-oriented programming": "object-oriented programming",
    "oop": "object-oriented programming",
    "agile development": "agile",
    "react": "react.js",
    "reactjs": "react.js",
    "react js": "react.js",
    "agile/scrum": "agile",
    "collaboratively": "collaboration",
}

IGNORED_SKILL_PHRASES = {
    "eagerness to learn", "willingness to learn", "guidance", "similar", "intern", "technical rounds",
    "hr interview", "final interview", "interview", "stipend", "work location",
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for", "from",
    "has", "have", "he", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "this", "to", "was", "were", "will", "with", "you", "your",
}

SECTION_ALIASES = {
    "skills": "skills", "technical skills": "skills", "key skills": "skills",
    "education": "education", "academic qualifications": "education",
    "academic background": "education", "projects": "projects", "project": "projects",
    "academic projects": "projects", "personal projects": "projects", "professional projects": "projects",
    "key projects": "projects", "major projects": "projects",
    "experience": "experience", "work experience": "experience",
    "professional experience": "experience", "internship": "experience",
    "certifications": "certifications", "certificates": "certifications",
    "certificate": "certifications", "certifications achievements": "certifications",
    "achievements": "certifications", "awards": "certifications", "honors": "certifications",
    "extra curricular activities": "certifications", "extracurricular activities": "certifications",
    "extra curricular": "certifications", "accomplishments": "certifications",
    "soft skills": "skills",
}

INVALID_PROJECT_TITLES = {"team size", "tech stack", "duration", "role", "responsibilities", "key responsibilities", "github", "description", "soft skills"}
INVALID_EDUCATION_TERMS = {"university", "college", "institute", "board", "certifications", "achievements", "extra activities"}
DEGREE_PATTERN = re.compile(
    r"(?:\b(?:m|b|phd|mba|mca|bca|bcs|hsc|ssc|diploma)\.?\s*(?:sc|s|com|e|tech|cs|a|phil)?\b|"
    r"\b(?:bachelor|master|doctorate|undergraduate|postgraduate)\b|\b(?:10th|12th)\b)", re.I
)


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


def extract_jd_text(path: Path) -> tuple[str, str | None]:
    """Extract JD content from documents, tabular CSVs, or structured JSON without serializing syntax."""
    extension = path.suffix.lower()
    if extension not in {".csv", ".json"}:
        return extract_text(path), None
    if extension == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            return "", None
        title = next((str(row.get(key, "")).strip() for row in rows for key in row
                      if key.lower().strip() in {"job title", "title", "position", "designation"} and row.get(key)), None)
        content = "\n".join(" | ".join(f"{key}: {value}" for key, value in row.items() if value not in (None, "")) for row in rows)
        return content, title
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    records = value if isinstance(value, list) else [value]
    strings: list[str] = []
    titles: list[str] = []
    def walk(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child_value in item.items():
                walk(child_value, child_key)
        elif isinstance(item, list):
            for child in item:
                walk(child, key)
        elif item is not None and str(item).strip():
            text = str(item).strip()
            if key.lower() in {"job title", "title", "position", "designation"}:
                titles.append(text)
            strings.append(f"{key}: {text}" if key else text)
    walk(records)
    return "\n".join(strings), (titles[0] if titles else None)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip())


def find_esco_skills_csv(search_root: Path = ESCO_SEARCH_ROOT) -> Path:
    configured = Path(__import__("os").environ["ESCO_SKILLS_CSV"]) if __import__("os").environ.get("ESCO_SKILLS_CSV") else None
    candidates = [configured] if configured else sorted(search_root.rglob("skills*.csv"))
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        with candidate.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
            sample = stream.read(8192)
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            header = set(next(csv.reader([sample.splitlines()[0]], dialect)))
        if ESCO_REQUIRED_COLUMNS.issubset(header):
            return candidate
    raise FileNotFoundError("Could not locate an ESCO skills CSV with the required columns")


def _canonical_text(value: str) -> str:
    value = normalize_whitespace(str(value)).replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", value.lower()).strip(" ,;:")


def lowercase_json_values(value: Any) -> Any:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, list):
        return [lowercase_json_values(item) for item in value]
    if isinstance(value, dict):
        return {key: lowercase_json_values(item) for key, item in value.items()}
    return value


def _technology_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for canonical, _, values in TECHNOLOGIES:
        normalized = _canonical_text(canonical)
        for value in [canonical, *values]:
            aliases[_canonical_text(value)] = normalized
    return aliases


ESCO_LABELS: dict[str, str] = {}
CONTROLLED_LABELS: dict[str, str] = {}
DATABASE_VOCABULARY: list[tuple[str, str, list[str]]] = []


def import_esco_skills(connection, csv_path: Path | None = None) -> int:
    csv_path = csv_path or find_esco_skills_csv()
    with csv_path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
        sample = stream.read(8192)
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        stream.seek(0)
        reader = csv.DictReader(stream, dialect=dialect)
        if not reader.fieldnames or not ESCO_REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(f"ESCO CSV has unexpected columns: {reader.fieldnames}")
        source_columns = {
            "concept_uri": "conceptUri", "concept_type": "conceptType", "skill_type": "skillType",
            "reuse_level": "reuseLevel", "preferred_label": "preferredLabel", "alt_labels": "altLabels",
            "hidden_labels": "hiddenLabels", "status": "status", "modified_date": "modifiedDate",
            "scope_note": "scopeNote",
        }
        records_by_uri: dict[str, tuple[Any, ...]] = {}
        with connection.cursor() as cursor:
            for row in reader:
                record = tuple(
                    (row.get(source_columns[column]) or "").strip() or None
                    for column in source_columns
                )
                if record[0]:
                    records_by_uri[record[0]] = record
            cursor.execute('DELETE FROM "ESCO_Skills" WHERE concept_uri IS NULL')
            _upsert_esco_rows(cursor, list(records_by_uri.values()))
            cursor.execute('SELECT COUNT(*) FROM "ESCO_Skills"')
            count = cursor.fetchone()[0]
    connection.commit()
    LOGGER.info("Imported %s ESCO skills from %s", count, csv_path)
    return count


def _upsert_esco_rows(cursor, records: list[tuple[Any, ...]]) -> None:
    execute_values(cursor, '''
        INSERT INTO "ESCO_Skills"
            (concept_uri, concept_type, skill_type, reuse_level, preferred_label,
             alt_labels, hidden_labels, status, modified_date, scope_note)
        VALUES %s
        ON CONFLICT (concept_uri) DO UPDATE SET
            concept_type = EXCLUDED.concept_type, skill_type = EXCLUDED.skill_type,
            reuse_level = EXCLUDED.reuse_level, preferred_label = EXCLUDED.preferred_label,
            alt_labels = EXCLUDED.alt_labels, hidden_labels = EXCLUDED.hidden_labels,
            status = EXCLUDED.status, modified_date = EXCLUDED.modified_date,
            scope_note = EXCLUDED.scope_note
    ''', records)


def load_esco_labels(connection) -> None:
    ESCO_LABELS.clear()
    with connection.cursor() as cursor:
        cursor.execute('SELECT preferred_label, alt_labels FROM "ESCO_Skills" WHERE preferred_label IS NOT NULL')
        for preferred, alternatives in cursor.fetchall():
            canonical = _canonical_text(preferred)
            ESCO_LABELS[canonical] = canonical
            for alternative in (alternatives or "").split("\n"):
                if alternative.strip():
                    ESCO_LABELS[_canonical_text(alternative)] = canonical


def load_controlled_labels(connection) -> None:
    CONTROLLED_LABELS.clear()
    DATABASE_VOCABULARY.clear()
    with connection.cursor() as cursor:
        cursor.execute("SELECT canonical_name, aliases FROM technology_dictionary")
        for canonical, aliases in cursor.fetchall():
            normalized = _canonical_text(canonical)
            DATABASE_VOCABULARY.append((canonical, "controlled", aliases or []))
            CONTROLLED_LABELS[normalized] = normalized
            for alias in aliases or []:
                CONTROLLED_LABELS[_canonical_text(alias)] = normalized


def extracted_skills(text: str) -> list[str]:
    if extract_external_skills is None:
        raise RuntimeError("skill-extractor is not installed in the project virtual environment") from SKILL_EXTRACTOR_IMPORT_ERROR
    return list(extract_external_skills(text))


def normalize_skills(values: Iterable[str]) -> list[str]:
    aliases = _technology_aliases()
    normalized: list[str] = []
    for value in values:
        candidate = _canonical_text(value)
        if not candidate:
            continue
        candidate = aliases.get(candidate, CONTROLLED_LABELS.get(candidate, ESCO_LABELS.get(candidate, candidate)))
        candidate = NORMALIZATION_ALIASES.get(candidate, candidate)
        if candidate in IGNORED_SKILL_PHRASES:
            continue
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _vocabulary() -> list[tuple[str, str, list[str]]]:
    entries = DATABASE_VOCABULARY or [*TECHNOLOGIES, *CONTROLLED_SKILLS]
    return list({(_canonical_text(canonical), category, tuple(_canonical_text(alias) for alias in aliases)): (canonical, category, list(aliases))
                 for canonical, category, aliases in entries}.values())


def discover_skills(text: str) -> list[str]:
    return normalize_skills([*technology_matches(text), *extracted_skills(text)])


def technology_matches(text: str) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    entries = sorted(_vocabulary(), key=lambda item: max([len(item[0]), *(len(alias) for alias in item[2])]), reverse=True)
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
    for index, (canonical, _, aliases) in enumerate(_vocabulary()):
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
    return re.sub(r"\s+", " ", cleaned).strip().lower()


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
        heading = re.sub(r"\s+", " ", heading)
        matched = next((value for key, value in sorted(SECTION_ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True) if heading == key), None)
        if matched:
            current = matched
        else:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _lines(text: str) -> list[str]:
    return [line.strip(" •-*\t") for line in text.splitlines() if line.strip(" •-*\t")]


def _raw_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _score(text: str) -> str:
    match = re.search(r"\b(?:cgpa|gpa|sgpa)\s*[:=-]?\s*\d+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*%", text, re.I)
    return match.group(0).strip() if match else ""


def _is_metadata(line: str) -> bool:
    return bool(re.match(r"^(?:github|team\s*size|tech\s*stack|role|duration|responsibilit(?:y|ies)|description|key\s+responsibilities)\s*[:|]?", line, re.I))


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^(?:[•●▪◦*-]|\(?\d+[.)])\s+", line)) or line.startswith("(cid:")


def _project_title(line: str, next_line: str = "") -> str | None:
    candidate = re.sub(r"^\(?\d+[.)]\s*", "", line).strip(" :-|")
    if "|" in candidate:
        candidate = candidate.split("|", 1)[0].strip(" :-|")
    candidate = re.sub(r"\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{4}\s*(?:--|[-–—]|to)\s*(?:Present|[A-Za-z]+\s*\d{4})$", "", candidate, flags=re.I)
    candidate = re.sub(r"\s+\d{4}\s*[-–—]\s*\d{4}$", "", candidate)
    normalized = re.sub(r"\s+", " ", candidate).strip()
    lower = normalized.lower()
    numbered_title = bool(re.match(r"^\d+[.)].*\b(?:19|20)\d{2}\b", line))
    if not normalized or lower in INVALID_PROJECT_TITLES or _is_metadata(line) or (_is_bullet(line) and not numbered_title):
        return None
    if re.search(r"https?://|github\.com|@", normalized, re.I) or len(normalized) > 100:
        return None
    if re.search(r"[.!?]$", normalized) or len(normalized.split()) > 12:
        return None
    if re.search(r"\d", normalized) and not re.search(r"\b(?:19|20)\d{2}\b", normalized):
        return None
    if ("," in line and technology_matches(line) or re.search(r"\b(?:team\s*size|individual\s+project)\b", line, re.I)
            or len(technology_matches(line)) >= 2):
        return None
    action_start = r"(?:built|developed|designed|implemented|created|worked|applied|contributed|responsible|managed|integrated|used|led|achieved|participated)\b"
    if re.match(action_start, normalized, re.I):
        return None
    has_title_signal = bool(re.match(r"^\d+[.)]", line) or re.search(r"\b(?:19|20)\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", line, re.I))
    next_is_content = bool(next_line)
    title_like = (
        next_is_content and len(normalized.split()) <= 8 and not _is_bullet(line)
        and bool(re.match(r"[A-Z][A-Za-z0-9&'()/:+.-]*(?:\s|$)", candidate))
    )
    if has_title_signal or title_like:
        return normalized
    return None


def _parse_education(text: str) -> list[dict[str, str]]:
    lines = _raw_lines(text)
    records: list[dict[str, str]] = []
    for index, line in enumerate(lines):
        if line.lower().strip(" :") in INVALID_EDUCATION_TERMS or re.search(r"degree\s+specialisation|institution\s*/?\s*board", line, re.I):
            continue
        if not DEGREE_PATTERN.search(line):
            continue
        next_degree = next((position for position in range(index + 1, len(lines)) if DEGREE_PATTERN.search(lines[position])), len(lines))
        block = " ".join(lines[index:next_degree])
        mark = _score(block)
        degree = re.sub(r"\b(?:cgpa|sgpa|gpa)\s*[:=-]?\s*\d+(?:\.\d+)?(?:/\d+)?|\b\d+(?:\.\d+)?\s*%", "", line, flags=re.I)
        degree = re.sub(r"\b(?:19|20)\d{2}\s*[-–—]\s*(?:\d{2,4}|present)\b|\b(?:19|20)\d{2}\b", "", degree, flags=re.I)
        degree = degree.split("|", 1)[0]
        degree = re.sub(r"^[^A-Za-z0-9]+", "", degree)
        degree = re.split(r"\s*[-–—]\s*", degree, maxsplit=1)[0]
        degree = re.split(r"\b(?:savitribai|university|college|institute|board)\b", degree, maxsplit=1, flags=re.I)[0]
        degree = re.split(r"(?:university|college|institute|board)", degree, maxsplit=1, flags=re.I)[0]
        degree = re.sub(r"\b(?:hsc|ssc)\b.*?\s+-\s+.*", lambda match: match.group(0).split(" - ", 1)[0], degree, flags=re.I)
        degree = re.sub(r"\b(?:pursuing|present)\b", "", degree, flags=re.I)
        degree = re.sub(r"\s+", " ", degree).strip(" ,|-:")
        if degree and degree.lower() not in INVALID_EDUCATION_TERMS and not any(existing["degree"].lower() == degree.lower() for existing in records):
            records.append({"degree": degree, "mark": mark})
    return records


def _parse_projects(text: str) -> list[dict[str, str]]:
    lines = _raw_lines(text)
    records: list[dict[str, str]] = []
    current: dict[str, Any] | None = None
    for index, line in enumerate(lines):
        title = _project_title(line, lines[index + 1] if index + 1 < len(lines) else "")
        if title:
            if current:
                current["description"] = re.sub(r"\s+", " ", current["description"]).strip()
                records.append(current)
            current = {"project_title": title, "description": ""}
            continue
        if current is None or re.search(r"https?://|github\.com", line, re.I) or re.search(r"\bteam\s*size\b|\btech\s*stack\b", line, re.I):
            continue
        if re.search(r"\b(?:19|20)\d{2}\b\s*(?:[-–—]|to)\s*\b(?:19|20)?\d{2,4}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b.*\b(?:present|\d{4})\b", line, re.I):
            continue
        content = re.sub(r"^\(?cid:\d+\)?\s*", "", line).strip(" •●▪◦*-\t")
        if re.match(r"^description\s*:", content, re.I):
            content = re.sub(r"^description\s*:\s*", "", content, flags=re.I)
        elif re.match(r"^(?:role|duration|team\s*size|responsibilit(?:y|ies))\s*:", content, re.I):
            continue
        if content:
            current["description"] = f"{current['description']} {content}".strip()
    if current:
        current["description"] = re.sub(r"\s+", " ", current["description"]).strip()
        records.append(current)
    return [record for record in records if record["project_title"].lower() not in INVALID_PROJECT_TITLES]


CERTIFICATE_MARKERS = re.compile(
    r"\b(?:certif\w*|course\s+completion|award|winner|won|champion|championship|"
    r"first\s+prize|second\s+prize|third\s+prize|\d+(?:st|nd|rd|th)\s+(?:rank|place)|competition|hackathon|"
    r"best\s+project|achievement|medal|trophy|state[- ]level|national[- ]level|university[- ]level|honou?r)\b", re.I,
)


def _parse_certificates(text: str, certification_section: str) -> list[str]:
    """Collect explicit credentials and notable achievements without inventing labels."""
    candidates: list[tuple[str, bool]] = []
    section_kind = ""
    for line in _raw_lines(text):
        heading = re.sub(r"[^a-z ]", "", line.lower()).strip()
        heading = re.sub(r"\s+", " ", heading)
        if heading in {"certifications", "certificates", "certificate"}:
            section_kind = "credentials"
            continue
        if heading in {"achievements", "awards", "honors", "extra curricular", "extra curricular activities", "accomplishments"}:
            section_kind = "achievements"
            continue
        if heading in SECTION_ALIASES or heading in {"skills", "education", "projects", "experience", "work experience"}:
            section_kind = ""
            continue
        if section_kind == "credentials" and not re.match(r"^(?:hobbies|interests?)\s*:", line, re.I):
            candidates.append((line, True))
        elif section_kind == "achievements" and CERTIFICATE_MARKERS.search(line):
            candidates.append((line, True))
    candidates.extend((line, False) for line in _raw_lines(text) if CERTIFICATE_MARKERS.search(line))
    values: list[str] = []
    for line, from_section in candidates:
        value = re.sub(r"^(?:certificate|certification|award|achievement)\s*[:|-]\s*", "", line, flags=re.I)
        value = re.sub(r"^[-•●▪◦*]+\s*", "", value).strip(" :-|")
        if value and (from_section or CERTIFICATE_MARKERS.search(line)) and len(value) <= 180 and not re.match(r"^(?:hobbies|interests?)\s*:", value, re.I):
            normalized = _canonical_text(value)
            if normalized and normalized not in values:
                values.append(normalized)
    return values


def parse_resume(raw_text: str) -> dict[str, Any]:
    sections = split_sections(raw_text)
    skills = discover_skills(sections["skills"] or raw_text)
    education = _parse_education(sections["education"])
    projects = _parse_projects(sections["projects"])
    experience = [{"job_role": line.lower(), "skills": discover_skills(line), "duration": ""}
                  for line in _lines(sections["experience"])
                  if not _is_bullet(line) and not _is_metadata(line) and len(line.split()) <= 15]
    certificates = _parse_certificates(raw_text, sections["certifications"])
    LOGGER.info("Resume extraction counts: projects=%s certificates_or_achievements=%s", len(projects), len(certificates))
    return lowercase_json_values({"skill": list(dict.fromkeys(skills)), "education": education, "project": projects, "experience": experience, "certificate": certificates})


def extract_job_title(raw_text: str) -> str | None:
    for line in normalize_whitespace(raw_text).splitlines()[:12]:
        match = re.search(r"(?:job title|position|role|designation)\s*[:\-]\s*(.+)", line, re.I)
        if match:
            return match.group(1).strip()
    for line in normalize_whitespace(raw_text).splitlines()[:5]:
        if 1 < len(line.split()) <= 8 and not re.search(r"@|\d{3}", line):
            return line.strip(" :-")
    return None


JD_INCLUDED_HEADINGS = {
    "responsibilities", "responsibility", "desired candidate profile", "candidate profile",
    "requirements", "required skills", "qualifications", "criteria", "what you will do",
}
JD_EXCLUDED_HEADINGS = {
    "stipend", "salary", "compensation", "work location", "location", "interview process",
    "selection process", "benefits", "about the company", "company overview",
}


def _heading_text(line: str) -> str:
    heading = re.sub(r"[^a-z0-9/& -]", "", line.lower()).strip(" -:")
    return re.sub(r"\s+", " ", heading)


def _looks_like_education_line(line: str) -> bool:
    return bool(re.search(
        r"\b(?:education|degree|bachelor|master|master's|master’s|m\.s|m\.sc|mca|b\.sc|bca|b\.tech|m\.tech|diploma|academic|msc|ai/ml)\b",
        line, re.I,
    ))


def _jd_skill_text(raw_text: str) -> str:
    """Keep skill-bearing JD sections and exclude education and administrative text."""
    selected: list[str] = []
    current = "other"
    saw_included_heading = False
    for line in normalize_whitespace(raw_text).splitlines():
        heading = _heading_text(line)
        if heading in JD_INCLUDED_HEADINGS:
            current = "included"
            saw_included_heading = True
            continue
        if heading in JD_EXCLUDED_HEADINGS:
            current = "excluded"
            continue
        if heading in {"education", "educational qualifications", "academic qualifications"}:
            current = "education"
            continue
        if current in {"excluded", "education"} or _looks_like_education_line(line):
            continue
        if not saw_included_heading or current == "included":
            selected.append(line)
    return "\n".join(selected)


ACADEMIC_MARK_CONTEXT = re.compile(
    r"\b(?:minimum|at\s+least|aggregate|overall|academic|eligib(?:ility|le)|marks?|percentage|"
    r"degree|bachelor|master|qualification|above|and\s+above|or\s+above)\b", re.I,
)
UNRELATED_MARK_CONTEXT = re.compile(
    r"\b(?:performance|improvement|growth|accuracy|market\s+share|optimization|optimisation|result)\b", re.I,
)


def _academic_mark(raw_text: str) -> str:
    for line in normalize_whitespace(raw_text).splitlines():
        for match in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*(%|percent(?:age)?)(?=\s|$|[.,;:])", line, re.I):
            context = line[max(0, match.start() - 90):match.end() + 90]
            academic_context = ACADEMIC_MARK_CONTEXT.search(context)
            explicit_academic = re.search(r"\b(?:academic|eligib(?:ility|le)|minimum|aggregate|overall|marks?|percentage)\b", context, re.I)
            unrelated_context = UNRELATED_MARK_CONTEXT.search(context)
            if academic_context and (not unrelated_context or explicit_academic):
                return f"{match.group(1)}%"
    return ""


def parse_jd(raw_text: str, job_title: str | None) -> dict[str, Any]:
    skills = discover_skills(_jd_skill_text(raw_text))
    education = []
    academic_mark = _academic_mark(raw_text)
    education_pattern = r"((?:bachelor(?:'s)?|master(?:'s)?|b\.?\s*(?:tech|sc)|b\.e|m\.?\s*(?:tech|sc)|degree|diploma)\b[^\n]{0,150})"
    for match in re.finditer(education_pattern, raw_text, re.I):
        degree_text = re.split(r"\||\b(?:company\s+name|location|experience\s*\(\s*years\s*\))\s*:", match.group(1), maxsplit=1, flags=re.I)[0]
        degree_text = re.sub(r"^(?:required\s+)?education\s*:\s*", "", degree_text, flags=re.I).strip(" :,-")
        degree_text = re.sub(
            r"\s*(?:,?\s*(?:minimum(?:\s+of)?|at\s+least|overall|aggregate(?:\s+of)?|minimum\s+percentage(?:\s+of)?|minimum\s+marks(?:\s+of)?)\s*\d{1,3}(?:\.\d+)?\s*(?:%|percent(?:age)?)(?:\s+(?:or|and)\s+above)?).*?$",
            "",
            degree_text,
            flags=re.I,
        ).strip(" :,-")
        if degree_text and not any(item["degree"].lower() == degree_text.lower() for item in education):
            education.append({"degree": degree_text, "percentage/mark": _score(match.group(1)) or academic_mark})
    if academic_mark and not education:
        education.append({"degree": "", "percentage/mark": academic_mark})
    experience = []
    years_pattern = r"\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\+?\s+years?"
    for match in re.finditer(rf"([^.!\n]{{0,100}}\b{years_pattern}[^.!\n]{{0,100}})", raw_text, re.I):
        years = re.search(years_pattern, match.group(1), re.I).group(0)
        experience.append({"skill": discover_skills(match.group(1)), "years": years.lower()})
    certificates = [line.strip().lower() for line in normalize_whitespace(raw_text).splitlines() if re.search(r"certif|certification", line, re.I)]
    LOGGER.info("JD extraction counts: academic_mark=%s education=%s certificates=%s", academic_mark or "none", len(education), len(certificates))
    return lowercase_json_values({"job_title": job_title or "", "expected_skills": skills, "expected_education": education, "expected_experience": experience, "expected_certificate": certificates})


def validate_resume_json(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {"skill", "education", "project", "experience", "certificate"}
    if set(data) != expected:
        errors.append(f"resume keys must be {sorted(expected)}")
    for key in ("skill", "education", "project", "experience", "certificate"):
        if not isinstance(data.get(key), list):
            errors.append(f"resume.{key} must be a list")
    for item in data.get("education", []):
        if set(item) != {"degree", "mark"} or not all(isinstance(item.get(key), str) for key in ("degree", "mark")):
            errors.append("education record has an invalid schema")
        if any(term in item.get("degree", "").lower() for term in INVALID_EDUCATION_TERMS):
            errors.append(f"education degree looks like an institution or heading: {item.get('degree')}")
    for item in data.get("project", []):
        if set(item) != {"project_title", "description"} or not all(isinstance(item.get(key), str) for key in ("project_title", "description")):
            errors.append("project record has an invalid schema")
        title, description = item.get("project_title", ""), item.get("description", "")
        if title.lower() in INVALID_PROJECT_TITLES or len(title) > 100:
            errors.append(f"project title looks invalid: {title}")
        if title.strip().lower() == description.strip().lower() and description.strip():
            errors.append(f"project title duplicates description: {title}")
    return list(dict.fromkeys(errors))


def validate_jd_json(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {"job_title", "expected_skills", "expected_education", "expected_experience", "expected_certificate"}
    if set(data) != expected:
        errors.append(f"JD keys must be {sorted(expected)}")
    for key in ("expected_skills", "expected_education", "expected_experience", "expected_certificate"):
        if not isinstance(data.get(key), list):
            errors.append(f"JD.{key} must be a list")
    for item in data.get("expected_education", []):
        if set(item) != {"degree", "percentage/mark"}:
            errors.append("JD education record has an invalid schema")
    for item in data.get("expected_experience", []):
        if set(item) != {"skill", "years"} or not isinstance(item.get("skill"), list) or not isinstance(item.get("years"), str):
            errors.append("JD experience record has an invalid schema")
    return list(dict.fromkeys(errors))


def export_datasets(connection, output_dir: Path | None = None) -> dict[str, Path]:
    output_dir = output_dir or DATA_ROOT
    output_dir.mkdir(parents=True, exist_ok=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT resume_file_name, candidate_name, email, phone, structured_data FROM candidate ORDER BY candidate_id")
        resumes = [{"resume_file_name": row[0], "candidate_name": row[1], "email": row[2], "phone": row[3], "structured_data": row[4]} for row in cursor.fetchall()]
        cursor.execute("SELECT jd_file_name, job_title, structured_data FROM job_description ORDER BY jd_id")
        jds = [{"jd_file_name": row[0], "job_title": row[1], "structured_data": row[2]} for row in cursor.fetchall()]
    resume_path, jd_path = output_dir / "resumes.json", output_dir / "jds.json"
    resume_path.write_text(json.dumps({"resumes": resumes}, indent=2, ensure_ascii=False), encoding="utf-8")
    jd_path.write_text(json.dumps({"job_descriptions": jds}, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"resumes": resume_path, "jds": jd_path}


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
        cursor.execute('DROP TABLE IF EXISTS technology_alias CASCADE')
        cursor.execute('DROP TABLE IF EXISTS "ESCO_Skills" CASCADE')
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
            CREATE TABLE IF NOT EXISTS technology_alias (
                alias_id BIGSERIAL PRIMARY KEY, tech_id BIGINT NOT NULL REFERENCES technology_dictionary(tech_id) ON DELETE CASCADE,
                alias_name VARCHAR(150) NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS "ESCO_Skills" (
                esco_id BIGSERIAL PRIMARY KEY, concept_uri TEXT UNIQUE, concept_type TEXT, skill_type TEXT,
                reuse_level TEXT, preferred_label TEXT, alt_labels TEXT, hidden_labels TEXT, status TEXT,
                modified_date TIMESTAMP NULL, scope_note TEXT
            );
            CREATE INDEX IF NOT EXISTS esco_skills_preferred_label_idx ON "ESCO_Skills" (preferred_label);
            CREATE INDEX IF NOT EXISTS technology_dictionary_canonical_name_idx ON technology_dictionary (canonical_name);
            CREATE INDEX IF NOT EXISTS technology_alias_alias_name_idx ON technology_alias (alias_name);
        """)
    connection.commit()


def seed_dictionary(connection) -> None:
    with connection.cursor() as cursor:
        for canonical, category, aliases in [*TECHNOLOGIES, *CONTROLLED_SKILLS]:
            cursor.execute("""
                INSERT INTO technology_dictionary (canonical_name, category, aliases)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING tech_id
            """, (canonical, category, Json(aliases)))
            result = cursor.fetchone()
            if result is None:
                cursor.execute("SELECT tech_id FROM technology_dictionary WHERE canonical_name = %s", (canonical,))
                result = cursor.fetchone()
            for alias in [canonical, *aliases]:
                cursor.execute("""
                    INSERT INTO technology_alias (tech_id, alias_name) VALUES (%s, %s)
                    ON CONFLICT (alias_name) DO NOTHING
                """, (result[0], _canonical_text(alias)))
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
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    ) if directory.is_dir() else []


def normalize_filename(filename: str) -> str:
    """Normalize only for duplicate comparison; preserve the original filename in storage."""
    return re.sub(r"\s+", " ", filename).strip().casefold()


def filename_exists(connection, table: str, column: str, filename: str) -> bool:
    if table not in {"candidate", "job_description"} or column not in {"resume_file_name", "jd_file_name"}:
        raise ValueError("Unsupported document table or filename column")
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT 1 FROM {table} WHERE lower(regexp_replace(btrim({column}), %s, %s, 'g')) = %s LIMIT 1",
            (r"\s+", " ", normalize_filename(filename)),
        )
        return cursor.fetchone() is not None


def process_batch(connection, reset: bool = False) -> dict[str, int]:
    create_schema(connection, reset=reset)
    seed_dictionary(connection)
    esco_count = import_esco_skills(connection)
    load_esco_labels(connection)
    resumes_dir, jds_dir = resolve_input_dirs()
    summary = {"resume_found": 0, "resume_success": 0, "resume_skipped": 0, "resume_failed": 0, "resume_unsupported": 0,
               "jd_found": 0, "jd_success": 0, "jd_skipped": 0, "jd_failed": 0, "jd_unsupported": 0,
               "resume_validation_passed": 0, "resume_validation_flagged": 0,
               "jd_validation_passed": 0, "jd_validation_flagged": 0, "esco_records": esco_count}
    load_controlled_labels(connection)
    resume_files = [path for path in files_in(resumes_dir) if path.suffix.lower() in RESUME_EXTENSIONS]
    jd_files = [path for path in files_in(jds_dir) if path.suffix.lower() in JD_EXTENSIONS]
    summary["resume_found"], summary["jd_found"] = len(resume_files), len(jd_files)
    LOGGER.info("Scanning resumes directory: found %s supported files", len(resume_files))
    LOGGER.info("Scanning JDs directory: found %s supported files", len(jd_files))
    for index, path in enumerate(resume_files, 1):
        LOGGER.info("[%s/%s] Checking resume: %s", index, len(resume_files), path.name)
        if filename_exists(connection, "candidate", "resume_file_name", path.name):
            summary["resume_skipped"] += 1
            LOGGER.info("Already exists in database. Skipping: %s", path.name)
            continue
        try:
            LOGGER.info("New resume detected; extracting and processing: %s", path.name)
            with connection.cursor() as cursor:
                digest = sha256_file(path)
                raw = extract_text(path)
                contacts = extract_contacts(raw)
                structured = parse_resume(raw)
                validation_errors = validate_resume_json(structured)
                if validation_errors:
                    summary["resume_validation_flagged"] += 1
                    raise ValueError(f"Resume JSON validation failed: {validation_errors}")
                else:
                    summary["resume_validation_passed"] += 1
                cursor.execute("""
                    INSERT INTO candidate (candidate_name, email, phone, resume_file_name, resume_hash, raw_text, clean_text, structured_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (contacts["name"], contacts["email"], contacts["phone"], path.name, digest, raw, clean_text(raw), Json(structured)))
            connection.commit()
            summary["resume_success"] += 1
            LOGGER.info("Successfully inserted resume: %s", path.name)
        except Exception as error:
            connection.rollback()
            summary["resume_failed"] += 1
            LOGGER.exception("Resume failed: file=%s type=%s stage=processing error=%s", path.name, path.suffix.lower(), error)

    for index, path in enumerate(jd_files, 1):
        LOGGER.info("[%s/%s] Checking JD: %s", index, len(jd_files), path.name)
        if filename_exists(connection, "job_description", "jd_file_name", path.name):
            summary["jd_skipped"] += 1
            LOGGER.info("Already exists in database. Skipping: %s", path.name)
            continue
        try:
            LOGGER.info("New JD detected; extracting and processing: %s", path.name)
            with connection.cursor() as cursor:
                raw, source_title = extract_jd_text(path)
                title = source_title or extract_job_title(raw)
                structured = parse_jd(raw, title)
                validation_errors = validate_jd_json(structured)
                if validation_errors:
                    summary["jd_validation_flagged"] += 1
                    raise ValueError(f"JD JSON validation failed: {validation_errors}")
                else:
                    summary["jd_validation_passed"] += 1
                cursor.execute("""
                    INSERT INTO job_description (job_title, jd_file_name, raw_text, clean_text, structured_data)
                    VALUES (%s, %s, %s, %s, %s)
                """, (title[:150], path.name, raw, clean_text(raw), Json(structured)))
            connection.commit()
            summary["jd_success"] += 1
            LOGGER.info("Successfully inserted JD: %s", path.name)
        except Exception as error:
            connection.rollback()
            summary["jd_failed"] += 1
            LOGGER.exception("JD failed: file=%s type=%s stage=processing error=%s", path.name, path.suffix.lower(), error)
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM candidate")
        summary["candidate_records"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM job_description")
        summary["jd_records"] = cursor.fetchone()[0]
    export_datasets(connection)
    return summary


def reprocess_existing_documents(
    connection,
    resume_names: Iterable[str] = (),
    jd_names: Iterable[str] = (),
) -> dict[str, int]:
    """Controlled migration for explicitly selected existing source files."""
    resumes_dir, jds_dir = resolve_input_dirs()
    selected_resumes = set(resume_names)
    selected_jds = set(jd_names)
    updated = {"resumes": 0, "jds": 0}
    for path in files_in(resumes_dir):
        if path.name not in selected_resumes or path.suffix.lower() not in RESUME_EXTENSIONS:
            continue
        raw = extract_text(path)
        structured = parse_resume(raw)
        errors = validate_resume_json(structured)
        if errors:
            raise ValueError(f"Resume JSON validation failed for {path.name}: {errors}")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE candidate SET raw_text=%s, clean_text=%s, structured_data=%s WHERE resume_file_name=%s",
                (raw, clean_text(raw), Json(structured), path.name),
            )
        updated["resumes"] += 1
    for path in files_in(jds_dir):
        if path.name not in selected_jds or path.suffix.lower() not in JD_EXTENSIONS:
            continue
        raw, source_title = extract_jd_text(path)
        title = source_title or extract_job_title(raw) or ""
        structured = parse_jd(raw, title)
        errors = validate_jd_json(structured)
        if errors:
            raise ValueError(f"JD JSON validation failed for {path.name}: {errors}")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE job_description SET job_title=%s, raw_text=%s, clean_text=%s, structured_data=%s WHERE jd_file_name=%s",
                (title[:150], raw, clean_text(raw), Json(structured), path.name),
            )
        updated["jds"] += 1
    connection.commit()
    export_datasets(connection)
    LOGGER.info("Controlled document reprocessing complete: %s", updated)
    return updated


def print_summary(summary: dict[str, int]) -> None:
    print("=" * 56)
    print("INGESTION SUMMARY")
    print("=" * 56)
    print(f"\nResumes:\n    Files found       : {summary['resume_found']}\n    Already in DB     : {summary['resume_skipped']}\n    Newly inserted    : {summary['resume_success']}\n    Failed            : {summary['resume_failed']}")
    print(f"\nJDs:\n    Files found       : {summary['jd_found']}\n    Already in DB     : {summary['jd_skipped']}\n    Newly inserted    : {summary['jd_success']}\n    Failed            : {summary['jd_failed']}")
    print(f"\nTotal files checked  : {summary['resume_found'] + summary['jd_found']}")
    print(f"Total new records    : {summary['resume_success'] + summary['jd_success']}")
    print(f"Total skipped        : {summary['resume_skipped'] + summary['jd_skipped']}")
    print(f"Total failed         : {summary['resume_failed'] + summary['jd_failed']}")
    print(f"\nDatabase: {DB_NAME}\nCandidate records: {summary['candidate_records']}\nJob Description records: {summary['jd_records']}\n")
    print(f"Resume JSON validation: {summary['resume_validation_passed']} passed, {summary['resume_validation_flagged']} flagged")
    print(f"JD JSON validation: {summary['jd_validation_passed']} passed, {summary['jd_validation_flagged']} flagged")
    print(f"Datasets: {DATA_ROOT / 'resumes.json'} and {DATA_ROOT / 'jds.json'}")
    print(f"ESCO records: {summary['esco_records']}")
    print("=" * 56)


if __name__ == "__main__":
    database_connection = connect_db()
    try:
        print_summary(process_batch(database_connection))
    finally:
        database_connection.close()
