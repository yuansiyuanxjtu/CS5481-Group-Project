"""Token windows mapped back to original cleaned text using fast-tokenizer offsets."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .models import Chunk, Page

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True)
class Strategy:
    name: str
    size: int
    overlap: int

    def __post_init__(self) -> None:
        if self.size <= 0 or not 0 <= self.overlap < self.size:
            raise ValueError("Require size > 0 and 0 <= overlap < size")


STRATEGIES = (Strategy("fixed_150", 150, 0), Strategy("fixed_220_overlap_30", 220, 30))
EXTRA_STRATEGIES = (Strategy("fixed_150_overlap_30", 150, 30), Strategy("fixed_220", 220, 0))
EXPERIMENT_STRATEGIES = (STRATEGIES[0], EXTRA_STRATEGIES[0], EXTRA_STRATEGIES[1], STRATEGIES[1])


def load_tokenizer(revision: str, cache_dir: str | None = None, offline: bool = False) -> Any:
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME, revision=revision, use_fast=True,
        cache_dir=cache_dir, local_files_only=offline,
    )
    if not tokenizer.is_fast:
        raise ValueError("A fast tokenizer with character offsets is required")
    return tokenizer


def chunk_page(page: Page, tokenizer: Any, strategy: Strategy) -> Iterator[Chunk]:
    encoded = tokenizer(page.text, add_special_tokens=False, return_offsets_mapping=True,
                        truncation=False, verbose=False)
    offsets = encoded["offset_mapping"]
    start, index = 0, 1
    while start < len(offsets):
        end = min(start + strategy.size, len(offsets))
        # Cutting within a WordPiece word can change its re-tokenization. Check the
        # exact exported text so the stored token_count always meets the budget.
        while end > start:
            text = page.text[offsets[start][0]:offsets[end - 1][1]]
            count = len(tokenizer.encode(text, add_special_tokens=False, truncation=False))
            if count <= strategy.size:
                break
            end -= 1
        if end <= start or end - start <= strategy.overlap and end < len(offsets):
            raise ValueError("Tokenizer offsets cannot produce a progressing token window")
        yield Chunk(
            f"{page.document_id}_p{page.page_number}_c{index}_{strategy.name}",
            page.document_id, page.source_file, page.source_url, page.page_number,
            text, strategy.name, count,
        )
        if end == len(offsets):
            break
        start = end - strategy.overlap
        index += 1
