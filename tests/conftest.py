"""Synthetic PDF fixtures are test data, never corpus sources."""
from pathlib import Path

import pymupdf
import pytest

from rag_ingest.chunking import load_tokenizer
from rag_ingest.cli import TOKENIZER_REVISION


@pytest.fixture(scope="session")
def tokenizer():
    return load_tokenizer(TOKENIZER_REVISION, str(Path(__file__).resolve().parents[1] / ".cache/huggingface/hub"), offline=True)


@pytest.fixture
def corpus(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, content in (("alpha.pdf", "Banking risk governance."), ("beta.pdf", "Financial policy controls.")):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((72, 72), content)
            doc.new_page()  # Empty physical page 2 must not renumber page 3.
            doc.new_page().insert_text((72, 72), "AI model oversight.")
            doc.save(raw / name)
    manifest = tmp_path / "sources.csv"
    manifest.write_text(
        "document_id,source_file,source_url\n"
        "doc002,beta.pdf,https://example.invalid/beta.pdf\n"
        "doc001,alpha.pdf,https://example.invalid/alpha.pdf\n", encoding="utf-8"
    )
    return manifest, raw
