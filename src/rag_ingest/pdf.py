"""Page-by-page PDF extraction. Physical page numbers are one-based."""
from collections.abc import Iterator
import re
import unicodedata

import pymupdf

from .models import Page, Source


def clean_text(text: str) -> str:
    """Normalize compatibility characters and whitespace without guessing content."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        char for char in text
        if not unicodedata.category(char).startswith("C") or char.isspace()
    )
    return re.sub(r"\s+", " ", text).strip()


def load_pdf(source: Source) -> Iterator[Page]:
    """Include empty pages so callers retain original citation page numbers."""
    with pymupdf.open(source.path) as document:
        if document.needs_pass:
            raise ValueError(f"Password-protected PDF: {source.source_file}")
        for number, page in enumerate(document, 1):
            yield Page(
                source.document_id, source.source_file, source.source_url,
                number, clean_text(page.get_text("text", sort=True)),
            )
