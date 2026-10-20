
from pathlib import Path

ROOT = Path(__file__).resolve().parent

replacements = {
    "Question_Selection_Generation/db_helper.py": [
        ("FROM bankresume", "FROM question_bank"),
    ],
    "Question_Selection_Generation/question_selector.py": [
        ("FROM bankresume", "FROM question_bank"),
    ],
    "Question_Selection_Generation/exam_workflow.py": [
        ("JOIN bankresume", "JOIN question_bank"),
    ],
    "Question_Generation/question_generator.py": [
        ("INSERT INTO bankresume", "INSERT INTO question_bank"),
        ("FROM bankresume", "FROM question_bank"),
    ],
    "Question_Generation/question_validator.py": [
        ("FROM bankresume", "FROM question_bank"),
        ("public.bankresume", "public.question_bank"),
    ],
}

for filename, pairs in replacements.items():
    path = ROOT / filename
    content = path.read_text(encoding="utf-8")
    updated = content

    for old, new in pairs:
        updated = updated.replace(old, new)

    if updated != content:
        path.write_text(updated, encoding="utf-8")
        print(f"UPDATED: {filename}")
    else:
        print(f"NO CHANGE: {filename}")

print("Finished updating SQL table references.")
