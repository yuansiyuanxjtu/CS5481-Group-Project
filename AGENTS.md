# CS5481 development rules

- Implement Member A's ingestion, chunking, embeddings, and storage work only. Current scope includes Phases 1, 2, and the five-document Phase 2.5 pilot; do not proceed to Phase 3.
- Do not add retrieval/evaluation, LLM generation, or frontend modules.
- Do not commit or push without explicit approval.
- Use Python 3.11+, PyMuPDF, the pinned MiniLM fast tokenizer, typed data contracts, and pytest. Avoid unnecessary frameworks.
- Preserve actual source URLs, source filenames, stable document IDs, and one-based physical PDF page numbers. Never combine pages in one chunk.
- Never fabricate corpus documents or provenance. Synthetic data belongs only in tests.
- Download corpus documents only when explicitly requested, and honor the five-document pilot cap. Keep PDFs, generated JSONL, model caches, and environments out of Git.
- Keep output deterministic: stable ordering, tokenizer revision, strategy names, IDs, and UTF-8 JSONL. Changes to cleaning or chunking require regenerating outputs.
- Phase 2 uses pinned MiniLM, 384-dimensional normalized embeddings and persistent Chroma cosine collections. Check collection configuration before writing; never mix embedding models or strategies.
- Default to offline model loading. Rebuild only explicitly requested collections; do not remove unrelated collections. Keep database files out of Git.
- Count tokens without special tokens and verify the exported text meets its token budget. Keep both chunking strategies separate.
- Run `.venv/bin/python -m pytest -q` after changes; see README for one-time tokenizer cache preparation.
