from pathlib import Path
from zipfile import ZipFile
import pytest
from Backend.services.zip_utils import UnsafeArchive, extract_resume_zip


def test_rejects_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("../escape.pdf", "bad")
    with pytest.raises(UnsafeArchive):
        extract_resume_zip(archive, tmp_path / "out", 10, 1000)


def test_skips_junk_and_hidden_files(tmp_path: Path):
    archive = tmp_path / "ok.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("__MACOSX/._x.pdf", "junk")
        z.writestr("notes.txt", "skip")
        z.writestr("resume.pdf", "pdf")
    result = extract_resume_zip(archive, tmp_path / "out", 10, 1000)
    assert [p.name for p in result] == ["resume.pdf"]
