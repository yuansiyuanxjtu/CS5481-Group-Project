"""Stream pages into deterministic JSONL, staging files before replacement."""
from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from contextlib import ExitStack

from .chunking import STRATEGIES, chunk_page
from .manifest import load_manifest
from .pdf import load_pdf


def run_pipeline(manifest: Path, pdf_dir: Path, output_dir: Path, tokenizer: Any) -> dict[str, int]:
    sources = load_manifest(manifest, pdf_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = {strategy.name: 0 for strategy in STRATEGIES}
    # A parsing failure leaves existing outputs intact. Each final replacement is
    # atomic; replacing the two outputs is not a filesystem-wide transaction.
    with TemporaryDirectory(prefix=".ingest-", dir=output_dir) as temporary:
        staging = Path(temporary)
        with ExitStack() as stack:
            streams = {
                s.name: stack.enter_context((staging / f"{s.name}.jsonl").open("w", encoding="utf-8", newline="\n"))
                for s in STRATEGIES
            }
            for source in sources:
                for page in load_pdf(source):
                    for strategy in STRATEGIES:
                        for chunk in chunk_page(page, tokenizer, strategy):
                            streams[strategy.name].write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
                            counts[strategy.name] += 1
        for strategy in STRATEGIES:
            filename = f"{strategy.name}.jsonl"
            (staging / filename).replace(output_dir / filename)
    return counts
