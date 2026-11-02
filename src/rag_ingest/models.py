"""Shared data contracts for later retrieval and generation modules."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    document_id: str
    source_file: str
    source_url: str
    path: Path


@dataclass(frozen=True)
class Page:
    document_id: str
    source_file: str
    source_url: str
    page_number: int
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    source_file: str
    source_url: str
    page_number: int
    text: str
    chunk_strategy: str
    token_count: int
