"""Experimental document-content queries and same-page sentence continuation."""
from collections import Counter
from functools import cached_property
import re

from relation_retrieval import ARM, COLLECTION, DEFAULT_CACHE, DEFAULT_EXPERIMENT, REFERENTIAL, RelationRetriever

BASELINE = "passage_relation5"
MODES = (BASELINE, "content5", "neighbor1", "neighbor2", "content_neighbor1", "content_neighbor2")
ISSUER = re.compile(r"\b(?:hkma|hong kong monetary authority|fsb|financial stability board|bis|bank for international settlements|financial stability institute|fsi\s+insights(?:\s+no\.?\s*63)?|no\.?\s*63)\b(?:['’]s)?", re.I)
DOCUMENT = re.compile(r"\b(?:report|guidance|letter|paper|circular|principles)\b", re.I)
DATE = re.compile(r"\b(?:19|20)\d{2}\b")
POSITION = re.compile(r"_p(\d+)_c(\d+)_fixed_")


def content_query(question):
    text = ISSUER.sub(" ", question)
    text = DATE.sub(" ", text)
    text = DOCUMENT.sub(" ", text)
    text = re.sub(r"\b(?:according to|under|of the|in the)\b", " ", text, flags=re.I)
    return " ".join(text.split()).strip(" ,?:")


class BoundaryRetriever(RelationRetriever):
    def __init__(self, experiment_dir=DEFAULT_EXPERIMENT, cache_dir=DEFAULT_CACHE, mode=BASELINE):
        super().__init__(experiment_dir, cache_dir, BASELINE)
        if mode not in MODES:
            raise ValueError(f"Unknown boundary experiment mode: {mode}")
        self.mode = mode
        self.use_content_query = False

    def ranked_passages(self, doc_id, query, rerank):
        rewritten = content_query(query) if self.use_content_query else query
        return super().ranked_passages(doc_id, rewritten or query, rerank)

    @cached_property
    def indexed_text(self):
        records, *_ = self.corpus
        return dict(zip(records["ids"], records["documents"], strict=True))

    @cached_property
    def next_on_page(self):
        positions = {}
        for chunk in self.indexed_text:
            match = POSITION.search(chunk)
            if match:
                positions[(self.source_by_chunk[chunk], int(match[1]), int(match[2]))] = chunk
        return {chunk: positions[(doc, page, number + 1)]
                for (doc, page, number), chunk in positions.items()
                if (doc, page, number + 1) in positions}

    def complete_sentences(self, question, base, seed_limit):
        chosen = list(base)
        protected_sources = set(self.routed_queries(question))
        if REFERENTIAL.search(question):
            protected_sources.update(self.source_by_chunk[chunk] for chunk in base[:2])
        protected_chunks = set(base[:seed_limit])
        for seed in base[:seed_limit]:
            text = self.indexed_text[seed].rstrip()
            neighbor = self.next_on_page.get(seed)
            if text.endswith((".", "!", "?", ";", ":")) or neighbor is None or neighbor in chosen:
                continue
            counts = Counter(self.source_by_chunk[chunk] for chunk in chosen)
            victim = next((chunk for chunk in reversed(chosen)
                           if chunk not in protected_chunks
                           and (self.source_by_chunk[chunk] not in protected_sources
                                or counts[self.source_by_chunk[chunk]] > 1)), None)
            if victim is None:
                continue
            chosen.remove(victim)
            chosen.insert(chosen.index(seed) + 1, neighbor)
            protected_chunks.add(neighbor)
        return chosen

    def candidates(self, question, modes):
        if any(mode not in MODES for mode in modes):
            raise ValueError("Unknown experiment mode")
        self.use_content_query = False
        baseline, vector = super().candidates(question, [BASELINE])
        choices = {BASELINE: baseline[BASELINE]}
        if any(mode.startswith("content") for mode in modes):
            self.use_content_query = True
            try:
                content, _ = super().candidates(question, [BASELINE])
                choices["content5"] = content[BASELINE]
            finally:
                self.use_content_query = False
        result = {}
        for mode in modes:
            source = choices["content5"] if mode.startswith("content") else choices[BASELINE]
            limit = 2 if mode.endswith("neighbor2") or mode == "neighbor2" else 1
            result[mode] = self.complete_sentences(question, source, limit) if "neighbor" in mode else source
        return result, vector
