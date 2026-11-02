"""Command-line entry point for Phase 1."""
import argparse
from pathlib import Path

from .chunking import load_tokenizer
from .manifest import load_manifest
from .pipeline import run_pipeline

# Immutable Hugging Face repository revision; update deliberately with validation.
TOKENIZER_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and chunk PDFs with page-level provenance")
    parser.add_argument("--manifest", type=Path, default=Path("data/sources.csv"))
    parser.add_argument("--pdf-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--cache-dir", help="Hugging Face tokenizer cache directory")
    parser.add_argument("--offline", action="store_true", help="Use cached tokenizer files only")
    args = parser.parse_args()
    try:
        load_manifest(args.manifest, args.pdf_dir)  # Fail before any tokenizer download.
        tokenizer = load_tokenizer(TOKENIZER_REVISION, args.cache_dir, args.offline)
        counts = run_pipeline(args.manifest, args.pdf_dir, args.output_dir, tokenizer)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")
    for strategy, count in counts.items():
        print(f"{strategy}: {count} chunks -> {args.output_dir / (strategy + '.jsonl')}")
    if not any(counts.values()):
        print("Warning: no text chunks extracted; scanned PDFs may require OCR (not included).")
