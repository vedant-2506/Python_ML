$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$service = Get-Service -Name "postgresql-x64-18" -ErrorAction Stop
if ($service.Status -ne "Running") {
    throw "PostgreSQL service postgresql-x64-18 is not running."
}

$psql = Join-Path ${env:ProgramFiles} "PostgreSQL\18\bin\psql.exe"
if (-not (Test-Path $psql)) {
    $psqlCommand = Get-Command psql -ErrorAction SilentlyContinue
    if ($psqlCommand) {
        $psql = $psqlCommand.Source
    } else {
        throw "PostgreSQL psql.exe was not found. Install PostgreSQL or add its bin directory to PATH."
    }
}
Write-Host "Using PostgreSQL client: $psql"
& $psql --version
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL client version check failed."
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project virtual environment was not found. Create it and install requirements.txt first."
}

Push-Location $projectRoot
try {
    $configureEnvironment = @'
from pathlib import Path
import secrets
from dotenv import dotenv_values, set_key

target = Path("Backend/.env")
if target.exists():
    print("Preserving existing Backend/.env.")
else:
    source = dotenv_values(".env")
    values = {
        "ENV": "dev",
        "DB_HOST": source.get("RANKRESUME_DB_HOST") or source.get("DB_HOST"),
        "DB_PORT": source.get("RANKRESUME_DB_PORT") or source.get("DB_PORT") or "5432",
        "DB_NAME": source.get("RANKRESUME_DB_NAME") or source.get("DB_NAME"),
        "DB_USER": source.get("RANKRESUME_DB_USER") or source.get("DB_USER"),
        "DB_PASSWORD": source.get("RANKRESUME_DB_PASSWORD") or source.get("DB_PASSWORD"),
        "JWT_SECRET": source.get("JWT_SECRET"),
        "FRONTEND_ORIGIN": source.get("FRONTEND_ORIGIN") or "http://localhost:5500",
        "FRONTEND_BASE_URL": source.get("FRONTEND_BASE_URL") or "http://localhost:5500",
        "GEMINI_API_KEY": source.get("GEMINI_API_KEY") or "",
        "GROQ_API_KEY": source.get("GROQ_API_KEY") or "",
        "GROQ_MODEL": source.get("GROQ_MODEL") or "llama-3.3-70b-versatile",
    }
    if any(not values[key] for key in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")):
        raise SystemExit("Backend/.env was not created: set DB settings in the existing project .env first.")
    if values["DB_NAME"] != "rankresume":
        raise SystemExit("Backend/.env was not created: expected DB_NAME=rankresume.")
    if not values["JWT_SECRET"] or values["JWT_SECRET"] in {"change-me", "replace-with-a-long-random-secret"}:
        values["JWT_SECRET"] = secrets.token_urlsafe(48)
    for key, value in values.items():
        set_key(str(target), key, str(value), quote_mode="auto")
    print("Created Backend/.env from existing local settings; secret values were not displayed.")
'@
    $configureEnvironment | & $python -
    if ($LASTEXITCODE -ne 0) {
        throw "Backend environment configuration failed."
    }

    & $python -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency consistency check failed."
    }

    $applyMigrations = @'
from pathlib import Path
import psycopg2
from Backend.core.config import get_settings

settings = get_settings()
if settings.db_name != "rankresume":
    raise SystemExit("Refusing to migrate a database other than rankresume.")
connection = psycopg2.connect(
    host=settings.db_host,
    port=settings.db_port,
    dbname=settings.db_name,
    user=settings.db_user,
    password=settings.db_password,
    connect_timeout=5,
)
try:
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != "rankresume":
                raise RuntimeError("Connected database guard failed.")
            for name in ("Backend/sql/001_backend_tables.sql", "Backend/sql/002_shortlisting.sql"):
                cursor.execute(Path(name).read_text(encoding="utf-8"))
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            required = {"company", "job_candidate", "job_shortlist", "exam_invitation"}
            missing = required - tables
            if missing:
                raise RuntimeError("Migration verification failed: " + ", ".join(sorted(missing)))
finally:
    connection.close()
print("Applied and verified only the additive backend migrations.")
'@
    $applyMigrations | & $python -
    if ($LASTEXITCODE -ne 0) {
        throw "Safe database migration failed."
    }

    & $python -m compileall -q Backend Answer_Checking ATS_calculation DB_Store Question_Generation Question_Selection_Generation
    if ($LASTEXITCODE -ne 0) {
        throw "Python compilation failed."
    }

    Write-Host "Windows setup checks completed. No PostgreSQL roles, existing rows, or question-bank data were modified."
} finally {
    Pop-Location
}
