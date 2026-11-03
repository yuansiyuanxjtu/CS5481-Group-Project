"""Phase 2 CLI, separate from the unchanged Phase 1 rag-ingest command."""
import argparse
import json
from pathlib import Path
from time import perf_counter

from chromadb.errors import ChromaError

from .embeddings import MiniLMEncoder
from .jsonl import load_chunks
from .vector_store import ingest_jsonl
from .temporal import load_temporal_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed Phase 1 JSONL and persist it in Chroma")
    parser.add_argument("--input", type=Path, nargs="+", help="Processed JSONL file(s)")
    parser.add_argument("--db-dir", type=Path, default=Path("data/chroma"))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--cache-dir", help="Full MiniLM model cache, reused offline")
    parser.add_argument("--allow-download", action="store_true", help="Permit model downloads; default is offline")
    parser.add_argument("--prepare-model", action="store_true", help="Load/cache the model without touching a DB")
    parser.add_argument("--rebuild", action="store_true", help="Delete and recreate only collections represented by the inputs")
    parser.add_argument("--catalog", type=Path, help="Optional verified temporal catalog")
    parser.add_argument("--dataset-version", help="Optional version tag for a separate experiment DB")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.prepare_model and (args.input or args.rebuild):
        parser.error("--prepare-model cannot be combined with --input or --rebuild")
    if not args.prepare_model and not args.input:
        parser.error("--input is required unless --prepare-model is supplied")
    try:
        if args.input:
            load_chunks(args.input)  # Validate before model downloads or database changes.
        temporal = load_temporal_catalog(args.catalog) if args.catalog else None
        started = perf_counter()
        encoder = MiniLMEncoder(args.cache_dir, offline=not args.allow_download)
        model_seconds = perf_counter() - started
        if args.prepare_model:
            print("Pinned MiniLM model loaded; cache is ready for offline execution.")
            return
        options = {}
        if temporal is not None:
            options["document_metadata"] = temporal
        if args.dataset_version:
            options["context"] = {"dataset_version": args.dataset_version}
        report = ingest_jsonl(args.input, args.db_dir, encoder, args.batch_size, args.rebuild, **options)
        report["model_load_seconds"] = model_seconds
        print(json.dumps(report, indent=2, sort_keys=True))
    except (OSError, ValueError, RuntimeError, ChromaError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
