"""Validate Phase 1 output completely before loading a model or changing a DB."""
from dataclasses import fields
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .chunking import EXPERIMENT_STRATEGIES
from .models import Chunk


def load_chunks(paths: list[Path]) -> dict[str, list[Chunk]]:
    if not paths:
        raise ValueError("Supply at least one processed JSONL file")
    sizes = {s.name: s.size for s in EXPERIMENT_STRATEGIES}
    grouped: dict[str, list[Chunk]] = {}
    seen: set[str] = set()
    required = {f.name for f in fields(Chunk)}
    for path in paths:
        count = 0
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                label = f"{path}:{line_number}"
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict) or set(row) != required:
                        raise ValueError(f"Expected exactly these fields: {sorted(required)}")
                    for key in required - {"page_number", "token_count"}:
                        if not isinstance(row[key], str) or not row[key].strip():
                            raise ValueError(f"{key} must be a nonempty string")
                    for key in ("page_number", "token_count"):
                        if type(row[key]) is not int or row[key] <= 0:
                            raise ValueError(f"{key} must be a positive integer")
                    strategy = row["chunk_strategy"]
                    if strategy not in sizes or row["token_count"] > sizes[strategy]:
                        raise ValueError("Unknown chunk strategy or token_count exceeds its budget")
                    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", row["document_id"]):
                        raise ValueError("Invalid document_id")
                    prefix = f'{row["document_id"]}_p{row["page_number"]}_c'
                    if not re.fullmatch(re.escape(prefix) + r"[1-9][0-9]*_" + re.escape(strategy), row["chunk_id"]):
                        raise ValueError("chunk_id does not match Phase 1 metadata")
                    url = urlsplit(row["source_url"])
                    if url.scheme not in {"http", "https"} or not url.netloc:
                        raise ValueError("source_url must be an actual HTTP(S) provenance URL")
                    if row["chunk_id"] in seen:
                        raise ValueError(f'Duplicate chunk_id: {row["chunk_id"]}')
                    seen.add(row["chunk_id"])
                    grouped.setdefault(strategy, []).append(Chunk(**row))
                    count += 1
                except (ValueError, TypeError) as error:
                    raise ValueError(f"{label}: {error}") from error
        if count == 0:
            raise ValueError(f"{path}: empty JSONL input; no collections changed")
    return grouped
