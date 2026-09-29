$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
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
Write-Host "Enter the existing PostgreSQL administrator password when prompted."

& $psql -h localhost -p 5432 -U postgres -d postgres -W -v ON_ERROR_STOP=1 -c @"
DO `$`$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'root') THEN
        CREATE ROLE root LOGIN PASSWORD 'root';
    ELSE
        ALTER ROLE root LOGIN PASSWORD 'root';
    END IF;
END
`$`$;
SELECT 'CREATE DATABASE rankresume OWNER root'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rankresume')
`\gexec
"@

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Project virtual environment was not found. Create it and install requirements.txt first."
}

Push-Location $projectRoot
try {
    & $python "DB_Store\rankresume_pipeline.py"
} finally {
    Pop-Location
}