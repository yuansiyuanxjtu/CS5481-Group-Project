"""Run the same evidence-labeled questions on all eight Phase 2.6 collections."""

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from rag_ingest.benchmark import hardware
from rag_ingest.chunking import EXPERIMENT_STRATEGIES
from rag_retrieval import ARMS, DEFAULT_CACHE, DEFAULT_EXPERIMENT, Retriever
import torch

TOP_K = 5
DEFAULT_GOLD = Path("data/evaluation/qa_gold.jsonl")


def evidence_ranks(hits: list[dict], evidence: list[dict]) -> list[int | None]:
    return [
        next((rank for rank, hit in enumerate(hits, 1)
              if hit["document_id"] == label["document_id"]
              and label["page_start"] <= hit["page_number"] <= label["page_end"]), None)
        for label in evidence
    ]


def load_gold(data: bytes, document_ids: set[str]) -> list[dict]:
    rows = []
    seen = set()
    for line in data.decode("utf-8").splitlines():
        row = json.loads(line)
        if row["id"] in seen or not row["question"].strip() or not row["evidence"]:
            raise ValueError(f"Duplicate ID or missing question/evidence: {row['id']}")
        for label in row["evidence"]:
            start, end = label["page_start"], label["page_end"]
            if label["document_id"] not in document_ids or type(start) is not int or type(end) is not int or not 1 <= start <= end:
                raise ValueError(f"Invalid physical page label: {row['id']}")
        seen.add(row["id"])
        rows.append(row)
    if not rows:
        raise ValueError("No QA rows")
    return rows


def evaluate(experiment_dir: Path, cache_dir: Path, gold_path: Path) -> dict:
    report = json.loads((experiment_dir / "benchmark.json").read_text(encoding="utf-8"))
    snapshot = report["dataset_snapshot"]
    contexts = {}
    for arm in ARMS:
        context = json.loads((experiment_dir / arm / "collection_context.json").read_text(encoding="utf-8"))
        for field in ("dataset_sha256", "dataset_version", "temporal_catalog_sha256"):
            if context[field] != report[field]:
                raise ValueError(f"{arm} {field} differs from the benchmark snapshot")
        contexts[arm] = context
    gold_bytes = gold_path.read_bytes().replace(b"\r\n", b"\n")
    rows = load_gold(gold_bytes, {row["document_id"] for row in snapshot})
    retriever = Retriever(experiment_dir, cache_dir)
    result = {
        "dataset_sha256": report["dataset_sha256"], "dataset_snapshot": snapshot,
        "embedding_spec": report["embedding_spec"], "hardware": hardware(),
        "torch_threads": torch.get_num_threads(),
        "dependencies": {name: version(name) for name in (
            "chromadb", "numpy", "sentence-transformers", "torch", "transformers",
        )},
        "top_k": TOP_K, "qa_sha256": sha256(gold_bytes).hexdigest(), "qa_count": len(rows),
        "agent_verified": [row["id"] for row in rows if row["review_status"] == "agent_verified"],
        "human_review_pending": [row["id"] for row in rows if row["review_status"] == "pending_human_review"],
        "timing": "One untimed warm-up per collection. Sequential wall-clock retrieve calls, including encoding, count, query and result mapping.",
        "configurations": [],
    }
    for arm in ARMS:
        for strategy in EXPERIMENT_STRATEGIES:
            retriever.retrieve(rows[0]["question"], TOP_K, collection=strategy.name, arm=arm)
            queries = []
            for row in rows:
                started = perf_counter()
                hits = retriever.retrieve(row["question"], TOP_K, collection=strategy.name, arm=arm)
                latency_ms = (perf_counter() - started) * 1000
                ranks = evidence_ranks(hits, row["evidence"])
                queries.append({
                    "id": row["id"], "latency_ms": round(latency_ms, 3),
                    "first_hit_rank": min((rank for rank in ranks if rank is not None), default=None),
                    "evidence_ranks": ranks,
                    "top_k": [{key: hit[key] for key in ("chunk_id", "document_id", "page_number", "distance")}
                              for hit in hits],
                })
            first = [q["first_hit_rank"] for q in queries]
            result["configurations"].append({
                "arm": arm, "cleaning_version": contexts[arm]["cleaning_version"],
                "chunking_version": contexts[arm]["chunking_version"],
                "collection": strategy.name, "chunk_size": strategy.size, "overlap": strategy.overlap,
                "records": report["arms"][arm]["strategies"][strategy.name]["records"],
                "hit_rate_at_5": mean(rank is not None for rank in first),
                "hit_rate_at_3": mean(rank is not None and rank <= 3 for rank in first),
                "mrr_at_5": mean(1 / rank if rank is not None else 0 for rank in first),
                "all_evidence_rate_at_5": mean(None not in q["evidence_ranks"] for q in queries),
                "mean_latency_ms": round(mean(q["latency_ms"] for q in queries), 3),
                "queries": queries,
            })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path, default=Path("docs/retrieval_results.json"))
    parser.add_argument("--torch-threads", type=int, default=4)
    args = parser.parse_args()
    if args.torch_threads < 1:
        parser.error("--torch-threads must be positive")
    torch.set_num_threads(args.torch_threads)
    result = evaluate(args.experiment_dir, args.cache_dir, args.gold)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for config in result["configurations"]:
        print(f"{config['arm']:8} {config['collection']:21} "
              f"Hit@5 {config['hit_rate_at_5']:.2%}  MRR@5 {config['mrr_at_5']:.4f}  "
              f"Mean {config['mean_latency_ms']:.3f} ms")


if __name__ == "__main__":
    main()
