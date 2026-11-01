from pathlib import Path
from zipfile import ZipFile, BadZipFile


class UnsafeArchive(ValueError):
    pass


def extract_resume_zip(zip_path: Path, destination: Path, max_files: int, max_uncompressed_bytes: int) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total = 0
    try:
        with ZipFile(zip_path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > max_files:
                raise UnsafeArchive(f"ZIP contains more than {max_files} files")
            for member in members:
                name = Path(member.filename)
                if name.is_absolute() or ".." in name.parts:
                    raise UnsafeArchive(f"Unsafe ZIP path: {member.filename}")
                if any(part.startswith(".") or part == "__MACOSX" for part in name.parts):
                    continue
                if name.suffix.lower() not in {".pdf", ".docx", ".doc"}:
                    continue
                total += member.file_size
                if total > max_uncompressed_bytes:
                    raise UnsafeArchive("ZIP uncompressed size exceeds configured limit")
                target = (destination / name).resolve()
                if destination.resolve() not in target.parents:
                    raise UnsafeArchive(f"Unsafe ZIP path: {member.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                extracted.append(target)
    except BadZipFile as exc:
        raise UnsafeArchive("Invalid ZIP archive") from exc
    return extracted
