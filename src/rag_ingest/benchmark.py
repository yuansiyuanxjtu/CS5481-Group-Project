"""Reproducible offline data-engineering benchmark; no retrieval evaluation."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter

import numpy as np

from .chunking import EXPERIMENT_STRATEGIES, chunk_page, load_tokenizer
from .cli import TOKENIZER_REVISION
from .embeddings import MiniLMEncoder
from .manifest import load_manifest
from .pdf import load_pdf
from .quality import CLEANING_VERSION, analyze_chunks, analyze_pages, enhance_pdf
from .temporal import load_temporal_catalog, storage_metadata
from .vector_store import ALL_COLLECTIONS, ingest_jsonl, open_collection, storage_size


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def hardware() -> dict:
    info = {"platform": platform.platform(), "machine": platform.machine(), "processor": platform.processor(),
            "python": sys.version, "logical_cpus": __import__('os').cpu_count()}
    if sys.platform == "darwin":
        for name in ("hw.model", "hw.memsize", "machdep.cpu.brand_string"):
            result = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True)
            info[name] = result.stdout.strip() if result.returncode == 0 else "unavailable"
    return info


def verify_records(collection, rows, temporal) -> str:
    stored = collection.get(include=["documents", "metadatas", "embeddings"])
    expected = {row["chunk_id"]: row for row in rows}
    if set(stored["ids"]) != set(expected):
        raise ValueError("Collection ID set differs from input")
    packed = []
    for index, key in enumerate(stored["ids"]):
        row = expected[key]
        metadata = {k: v for k, v in row.items() if k not in {"text", "chunk_id"}}
        metadata.update(storage_metadata(temporal[row["document_id"]]))
        if stored["documents"][index] != row["text"] or stored["metadatas"][index] != metadata:
            raise ValueError("Stored text or metadata differs from input")
        vector = stored["embeddings"][index]
        if len(vector) != 384 or not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector), 1, atol=1e-5):
            raise ValueError("Invalid persisted embedding")
        packed.append((key, row["text"], metadata, vector.tolist()))
    return hashlib.sha256(json.dumps(sorted(packed), sort_keys=True).encode()).hexdigest()


def run_benchmark(manifest: Path, pdf_dir: Path, baseline_dir: Path, catalog: Path,
                  output_dir: Path, cache_dir: str, batch_size: int = 32) -> dict:
    if output_dir.exists():
        raise ValueError("Benchmark output already exists; choose a new directory to preserve previous runs")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    sources = load_manifest(manifest, pdf_dir)
    temporal = load_temporal_catalog(catalog)
    if set(temporal) != {s.document_id for s in sources}:
        raise ValueError("Manifest and temporal catalog must describe the identical dataset")
    snapshot = []
    for source in sources:
        checksum = digest(source.path)
        if checksum != temporal[source.document_id]["document_checksum"]:
            raise ValueError(f"Source checksum does not match temporal catalog: {source.document_id}")
        snapshot.append({"document_id": source.document_id, "source_file": source.source_file,
                         "source_url": source.source_url, "sha256": checksum})
    dataset_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    tokenizer = load_tokenizer(TOKENIZER_REVISION, cache_dir, offline=True)
    load_started = perf_counter()
    encoder = MiniLMEncoder(cache_dir, offline=True)
    model_load = perf_counter() - load_started
    output_dir.mkdir(parents=True)
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "hardware": hardware(),
              "dependencies": {d.metadata["Name"]: d.version for d in distributions()},
              "dataset_snapshot": snapshot, "dataset_sha256": dataset_hash,
              "dataset_version": "pilot5_" + dataset_hash[:12], "temporal_catalog_sha256": digest(catalog),
              "manifest_sha256": digest(manifest), "embedding_spec": encoder.spec.metadata(),
              "model_load_seconds": model_load, "batch_size": batch_size,
              "strategies": [asdict(s) for s in EXPERIMENT_STRATEGIES], "arms": {},
              "source_code_sha256": {p.name: digest(p) for p in Path(__file__).parent.glob('*.py')}}
    archived = output_dir / "original_baseline"
    archived.mkdir()
    for name in ("fixed_150", "fixed_220_overlap_30"):
        shutil.copy2(baseline_dir / f"{name}.jsonl", archived)
    save(output_dir / "temporal_catalog.json", json.loads(catalog.read_text()))
    for arm in ("baseline", "enhanced"):
        folder = output_dir / arm
        folder.mkdir()
        pages, document_audits = [], []
        started = perf_counter()
        per_document = []
        for source in sources:
            if arm == "baseline":
                extracted = list(load_pdf(source))
            else:
                extracted, audit = enhance_pdf(source)
                document_audits.append(audit)
            pages.extend(extracted)
            per_document.append({"document_id": source.document_id, **analyze_pages(extracted)})
        processing_seconds = perf_counter() - started
        page_map = {(p.document_id, p.page_number): p for p in pages}
        save(folder / "cleaning_audit.json", document_audits)
        save(folder / "pages.json", [asdict(p) for p in pages])
        arm_report = {"pdf_processing_seconds": processing_seconds, "pages": analyze_pages(pages),
                      "per_document": per_document, "strategies": {}}
        context = {"dataset_version": report["dataset_version"], "dataset_sha256": dataset_hash,
                   "cleaning_version": "baseline_v1" if arm == "baseline" else CLEANING_VERSION,
                   "chunking_version": "original_token_windows_v1", "temporal_catalog_sha256": digest(catalog)}
        save(folder / "collection_context.json", context)
        for strategy in EXPERIMENT_STRATEGIES:
            started = perf_counter()
            rows = [asdict(c) for page in pages for c in chunk_page(page, tokenizer, strategy)]
            chunk_seconds = perf_counter() - started
            path = folder / f"{strategy.name}.jsonl"
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
            if arm == "baseline" and strategy.name in {"fixed_150", "fixed_220_overlap_30"}:
                if digest(path) != digest(archived / path.name):
                    raise ValueError("Recomputed baseline is not byte-identical to the preserved baseline")
            stats = analyze_chunks(rows, tokenizer, page_map, strategy.size)
            if stats["invalid_chunks"]:
                raise ValueError("Invalid chunk detected; inspect benchmark artifacts")
            first = ingest_jsonl([path], folder / "chroma", encoder, batch_size,
                                 document_metadata=temporal, context=context)
            collection = open_collection(folder / "chroma", strategy.name, encoder.spec, context=context)
            before_repeat = verify_records(collection, rows, temporal)
            second = ingest_jsonl([path], folder / "chroma", encoder, batch_size,
                                  document_metadata=temporal, context=context)
            after_repeat = verify_records(collection, rows, temporal)
            if before_repeat != after_repeat:
                raise ValueError("Repeated ingestion changed the stored snapshot")
            arm_report["strategies"][strategy.name] = {
                "quality": stats, "chunking_seconds": chunk_seconds, "jsonl_sha256": digest(path),
                "first_ingestion": first, "repeat_ingestion": second,
                "records": collection.count(), "record_snapshot_sha256": after_repeat,
                "repeat_snapshot_identical": True,
            }
        arm_report["database_storage_bytes"] = storage_size(folder / "chroma")
        report["arms"][arm] = arm_report
        save(output_dir / "benchmark.json", report)
        print(f"{arm}: {len(pages)} physical pages; all four collections checked", flush=True)
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    save(output_dir / "benchmark.json", report)
    lines = ["# Phase 2.6 benchmark", "", f"Dataset: `{report['dataset_version']}`; five unchanged PDFs.", "",
             "Single CPU run, fixed strategy order, no warm-up exclusion or statistical repetitions. First ingestion is an empty DB per arm; repeated ingestion re-encodes identical chunks. This measures data engineering, not retrieval quality.", "",
             "| Arm | Strategy | Chunks | Mean tokens | Page-label chunks | Invalid | Encode s | Insert s | Repeat identical |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    summaries = []
    for arm, data in report["arms"].items():
        for strategy, result in data["strategies"].items():
            q = result["quality"]
            lines.append(f"| {arm} | {strategy} | {q['count']} | {q['average_tokens']:.2f} | {q['page_number_only_chunks']} | {q['invalid_chunks']} | {result['first_ingestion']['embedding_seconds']:.3f} | {result['first_ingestion']['insertion_seconds']:.3f} | yes |")
        summaries += ["", f"{arm}: PDF processing {data['pdf_processing_seconds']:.3f}s; {data['pages']['characters']:,} cleaned characters; DB {data['database_storage_bytes']:,} bytes.", ""]
    lines += summaries
    lines += ["Full distributions, environment/dependency details, raw-file checksums, code/config fingerprints, contexts and first/repeat timings are in `benchmark.json`. Cleaning audit logs preserve before/after page text and removed lines. The original two JSONL outputs are archived and verified byte-identical to recomputed baseline outputs. Original PDFs and the pilot DB were not written.", "",
              "Collection sizes are logical file bytes for all four collections per arm, after repeat ingestion; SQLite journal/index allocation can vary. Extraction coverage means physical pages visited with successful extraction, not verified completeness of charts or OCR. Short/malformed/duplicate flags are diagnostics, distinct from structural invalidity. Sentence/word boundary counts are punctuation/substring heuristics, not linguistic accuracy measures."]
    (output_dir / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Offline, isolated Phase 2.6 benchmark")
    parser.add_argument("--manifest", type=Path, default=Path("data/sources.csv"))
    parser.add_argument("--pdf-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--baseline-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog/temporal_metadata.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", default=".cache/huggingface/hub")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    try:
        run_benchmark(args.manifest, args.pdf_dir, args.baseline_dir, args.catalog,
                      args.output_dir, args.cache_dir, args.batch_size)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
