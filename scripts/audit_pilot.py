"""Offline, measured pilot data-quality and traceability checks; no evaluation labels.

Reads the already-built corpus and DB. Prints actual smoke hits; saves measurements
and complete hit text to data/catalog. Does not download or change vector records.
"""
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import pymupdf

from rag_ingest.chunking import load_tokenizer
from rag_ingest.cli import TOKENIZER_REVISION
from rag_ingest.embeddings import MiniLMEncoder
from rag_ingest.jsonl import load_chunks
from rag_ingest.manifest import load_manifest
from rag_ingest.pdf import load_pdf
from rag_ingest.vector_store import COLLECTIONS, open_collection, storage_size

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "What responsibilities do bank boards and senior management have for AI governance?",
    "How should financial institutions ensure AI explainability and transparency?",
    "What data quality and data governance controls are needed for AI models?",
    "How can third-party AI providers create concentration and operational risks?",
    "What human oversight and validation should banks apply to generative AI?",
]


def save(name, value):
    (ROOT / "data/catalog" / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    sources = load_manifest(ROOT / "data/sources.csv", ROOT / "data/raw")
    catalog = json.loads((ROOT / "data/catalog/pilot_sources.json").read_text())
    registered = {d["document_id"]: d for d in catalog["documents"]}
    tokenizer = load_tokenizer(TOKENIZER_REVISION, str(ROOT / ".cache/huggingface/hub"), offline=True)
    grouped = load_chunks([ROOT / "data/processed" / f"{s}.jsonl" for s in COLLECTIONS])
    pages_by_key, documents, page_stats, samples = {}, [], [], []
    for source in sources:
        content = source.path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if registered[source.document_id]["sha256"] != digest:
            raise ValueError(f"Checksum mismatch: {source.path}")
        pages = list(load_pdf(source))  # Fail on extraction exceptions; never count as success.
        raw_texts = []
        with pymupdf.open(source.path) as pdf:
            for physical_page, (raw_page, page) in enumerate(zip(pdf, pages), 1):
                text = raw_page.get_text("text", sort=True)
                raw_texts.append(text)
                pages_by_key[(page.document_id, physical_page)] = page
                token_count = len(tokenizer.encode(page.text, add_special_tokens=False, truncation=False, verbose=False))
                page_stats.append({"document_id": source.document_id, "page_number": physical_page,
                                   "raw_characters": len(text), "cleaned_characters": len(page.text),
                                   "tokens": token_count, "empty": not page.text,
                                   "very_little_text": 0 < len(page.text) < 100})
        stats = [r for r in page_stats if r["document_id"] == source.document_id]
        lines = Counter()
        for text in raw_texts:
            # Edge lines only; ignore page-number-only and very short lines.
            nonempty = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
            nonempty = [re.sub(r"^[\d\s-]+|[\d\s-]+$", "", x) for x in nonempty]
            edge = {x for x in nonempty[:2] + nonempty[-2:] if len(x) >= 12}
            lines.update(edge)
        controls = Counter(f"U+{ord(c):04X}" for text in raw_texts for c in text
                           if unicodedata.category(c).startswith("C") and not c.isspace())
        documents.append({
            "document_id": source.document_id, "pages": len(pages), "parsed": True,
            "sha256": digest, "pdf_bytes": len(content),
            "raw_characters": sum(r["raw_characters"] for r in stats),
            "cleaned_characters": sum(r["cleaned_characters"] for r in stats),
            "tokens": sum(r["tokens"] for r in stats),
            "empty_pages": [r["page_number"] for r in stats if r["empty"]],
            "very_little_text_pages": [r["page_number"] for r in stats if r["very_little_text"]],
            "replacement_characters": sum(text.count("\ufffd") for text in raw_texts),
            "raw_nonwhitespace_controls": dict(controls),
            "repeated_edge_lines": [{"text": text, "page_occurrences": n} for text, n in lines.most_common(6) if n >= 3],
            "cleaned_document_sha256": hashlib.sha256("\n".join(p.text for p in pages).encode()).hexdigest(),
        })
    chunk_stats = {}
    for strategy, chunks in grouped.items():
        mid_word_starts = mid_word_ends = non_sentence_ends = 0
        for chunk in chunks:
            page = pages_by_key[(chunk.document_id, chunk.page_number)]
            assert chunk.source_file == page.source_file and chunk.source_url == page.source_url
            assert chunk.text in page.text
            actual = len(tokenizer.encode(chunk.text, add_special_tokens=False, truncation=False))
            assert chunk.token_count == actual
            start = page.text.find(chunk.text)
            end = start + len(chunk.text)
            mid_word_starts += bool(start > 0 and page.text[start - 1].isalnum() and chunk.text[0].isalnum())
            mid_word_ends += bool(end < len(page.text) and page.text[end].isalnum() and chunk.text[-1].isalnum())
            non_sentence_ends += bool(end < len(page.text) and chunk.text[-1] not in '.!?;:"”)]')
        chunk_stats[strategy] = {
            "count": len(chunks), "average_tokens": sum(c.token_count for c in chunks) / len(chunks),
            "average_characters": sum(len(c.text) for c in chunks) / len(chunks),
            "min_tokens": min(c.token_count for c in chunks), "max_tokens": max(c.token_count for c in chunks),
            "mid_word_starts_heuristic": mid_word_starts, "mid_word_ends_heuristic": mid_word_ends,
            "non_sentence_ends_heuristic": non_sentence_ends,
            "per_document": dict(Counter(c.document_id for c in chunks)),
            "citation_metadata_and_page_substring_checks": len(chunks),
        }
        for doc in documents:
            candidates = [c for c in chunks if c.document_id == doc["document_id"]
                          and len(pages_by_key[(c.document_id, c.page_number)].text) >= 1000]
            for label, sample in [("first_substantive", candidates[0]), ("middle", candidates[len(candidates) // 2])]:
                samples.append({"selection": label, **asdict(sample)})
    digests = [d["sha256"] for d in documents]
    text_digests = [d["cleaned_document_sha256"] for d in documents]
    encoder = MiniLMEncoder(str(ROOT / ".cache/huggingface/hub"), offline=True)
    queries = encoder.encode(QUESTIONS, batch_size=5)
    smoke = []
    counts = {}
    by_id = {c.chunk_id: c for chunks in grouped.values() for c in chunks}
    for strategy in COLLECTIONS:
        collection = open_collection(ROOT / "data/chroma", strategy, encoder.spec)
        counts[collection.name] = collection.count()
        assert collection.count() == len(grouped[strategy]), "Existing DB has stale or missing records"
        # Verify every persisted record's text, citation metadata, vector size and norm.
        import numpy as np
        all_records = collection.get(include=["documents", "metadatas", "embeddings"])
        for i, chunk_id in enumerate(all_records["ids"]):
            chunk = by_id[chunk_id]
            assert all_records["documents"][i] == chunk.text
            expected = asdict(chunk)
            del expected["chunk_id"]
            del expected["text"]
            assert all_records["metadatas"][i] == expected
        assert all_records["embeddings"].shape == (len(grouped[strategy]), 384)
        assert np.allclose(np.linalg.norm(all_records["embeddings"], axis=1), 1, atol=1e-5)
        for question, vector in zip(QUESTIONS, queries):
            result = collection.query(query_embeddings=[vector.tolist()], n_results=2,
                                      include=["documents", "metadatas", "distances"])
            hits = []
            for chunk_id, text, metadata, distance in zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]):
                source_page = pages_by_key[(metadata["document_id"], metadata["page_number"])]
                assert text == by_id[chunk_id].text and text in source_page.text
                assert metadata["source_url"] == source_page.source_url
                hit = {"chunk_id": chunk_id, "text": text, "metadata": metadata,
                       "cosine_distance": distance, "local_page_trace_verified": True}
                hits.append(hit)
                print(json.dumps({"question": question, "collection": collection.name, **hit}, ensure_ascii=False))
            smoke.append({"question": question, "collection": collection.name, "hits": hits})
    totals = {key: sum(d[key] for d in documents) for key in ["pages", "pdf_bytes", "raw_characters", "cleaned_characters", "tokens"]}
    report = {"measured_at_utc": datetime.now(timezone.utc).isoformat(), "downloaded_documents": len(documents),
              "parsed_documents": sum(d["parsed"] for d in documents), "totals": totals,
              "empty_pages": sum(len(d["empty_pages"]) for d in documents),
              "very_little_text_pages": sum(len(d["very_little_text_pages"]) for d in documents),
              "very_little_text_definition": "1-99 cleaned characters; empty means 0",
              "duplicate_pdf_files": len(digests) - len(set(digests)),
              "duplicate_cleaned_documents": len(text_digests) - len(set(text_digests)),
              "documents": documents, "chunks": chunk_stats,
              "collections": counts, "database_storage_bytes": storage_size(ROOT / "data/chroma"),
              "smoke_questions": len(QUESTIONS), "smoke_hits_verified": sum(len(s["hits"]) for s in smoke)}
    save("quality_metrics.json", report)
    save("page_metrics.json", page_stats)
    save("representative_chunks.json", samples)
    save("smoke_results.json", smoke)


if __name__ == "__main__":
    main()
