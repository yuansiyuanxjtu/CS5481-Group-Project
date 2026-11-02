"""Validate explicit provenance; never infer source URLs."""
import csv
import re
from pathlib import Path
from urllib.parse import urlsplit

from .models import Source


COLUMNS = ("document_id", "source_file", "source_url")


def load_manifest(manifest: Path, pdf_dir: Path) -> list[Source]:
    root = pdf_dir.resolve()
    sources = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError(f"Manifest header must be {','.join(COLUMNS)}")
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Manifest line {line}: expected exactly three fields")
            doc_id, filename, url = (row[key].strip() for key in COLUMNS)
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", doc_id):
                raise ValueError(f"Manifest line {line}: invalid document_id")
            if doc_id in seen_ids:
                raise ValueError(f"Duplicate document_id: {doc_id}")
            path = (root / filename).resolve()
            if not filename or Path(filename).is_absolute() or not path.is_relative_to(root):
                raise ValueError(f"Manifest line {line}: source_file must be relative to PDF directory")
            if path.suffix.lower() != ".pdf" or not path.is_file():
                raise ValueError(f"Manifest line {line}: PDF does not exist: {filename}")
            if path in seen_paths:
                raise ValueError(f"PDF listed more than once: {filename}")
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Manifest line {line}: supply the actual HTTP(S) source URL")
            seen_ids.add(doc_id)
            seen_paths.add(path)
            sources.append(Source(doc_id, filename, url, path))
    if not sources:
        raise ValueError("Manifest contains no PDF sources; add real sources before running")
    return sorted(sources, key=lambda source: source.document_id)
