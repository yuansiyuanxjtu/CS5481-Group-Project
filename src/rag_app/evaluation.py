"""Reproducible real runs plus independent human grading. Never invent results."""
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess

from .config import ROOT
from .grounding import PROMPT_VERSION, SYSTEM_PROMPT

SERVICE_ERRORS = {"llm_error", "retrieval_error", "invalid_output", "invalid_input"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_questions(gold, ood):
    rows = []
    for path, answerable in ((gold, True), (ood, False)):
        group = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(group) < (20 if answerable else 5):
            raise ValueError("Formal evaluation requires at least 20 gold and 5 OOD questions")
        for row in group:
            if not isinstance(row.get("id"), str) or not isinstance(row.get("question"), str) or not row["question"].strip():
                raise ValueError("Invalid QA ID/question")
            if not isinstance(row.get("reference_answer"), str) or not row["reference_answer"].strip():
                raise ValueError("Missing reference answer")
            if answerable and not row.get("evidence"):
                raise ValueError("Gold question requires source evidence labels")
            rows.append({**row, "answerable": answerable})
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("QA IDs must be unique")
    return rows


def metrics(records, ratings):
    expected = {r["id"] for r in records}
    if set(ratings) != expected:
        raise ValueError("Ratings must contain every run ID exactly once")
    for row in records:
        rating = ratings[row["id"]]
        if rating["verdict"] not in {"correct", "partial", "incorrect", "pending"}:
            raise ValueError("Invalid verdict")
        if rating["citation_verdict"] not in {"valid", "invalid", "not_applicable", "pending"}:
            raise ValueError("Invalid citation verdict")
        if rating["verdict"] != "pending":
            if not rating["reason"].strip() or not rating["reviewer"].strip() or rating["citation_verdict"] == "pending":
                raise ValueError("Completed ratings require reviewer, reason and citation assessment")
            if row["result"]["status"] in SERVICE_ERRORS | {"not_run"} and rating["verdict"] != "incorrect":
                raise ValueError("Service failures cannot be graded correct or partial")
            if rating["citation_verdict"] == "invalid" and rating["verdict"] == "correct":
                raise ValueError("Unsupported citations cannot receive a correct grade")
            status = row["result"]["status"]
            if row["answerable"] and rating["verdict"] in {"correct", "partial"} and status != "answered":
                raise ValueError("A refusal to an answerable gold question cannot receive credit")
            if not row["answerable"] and rating["verdict"] == "correct" and status != "insufficient_evidence":
                raise ValueError("An OOD success must be an explicit refusal")
            if status == "answered" and rating["citation_verdict"] == "not_applicable":
                raise ValueError("An answered question requires citation assessment")
    gold = [r for r in records if r["answerable"]]
    ood = [r for r in records if not r["answerable"]]
    complete = all(ratings[r["id"]]["verdict"] != "pending" for r in records)
    counts = {v: sum(ratings[r["id"]]["verdict"] == v for r in gold)
              for v in ("correct", "partial", "incorrect", "pending")}
    ood_ran = [r for r in ood if r["result"]["status"] != "not_run"]
    return {"grading_complete": complete, "gold_count": len(gold), "ood_count": len(ood),
            "gold_grades": counts,
            "strict_accuracy": counts["correct"] / len(gold) if complete else None,
            "partial_credit_accuracy": (counts["correct"] + 0.5 * counts["partial"]) / len(gold) if complete else None,
            "ood_explicit_refusal_rate": sum(r["result"]["status"] == "insufficient_evidence" for r in ood) / len(ood)
            if len(ood_ran) == len(ood) else None,
            "service_errors": sum(r["result"]["status"] in SERVICE_ERRORS for r in records),
            "not_run": sum(r["result"]["status"] == "not_run" for r in records),
            "citation_errors": sum(r["citation_verdict"] == "invalid" for r in ratings.values()),
            "score_rule": "Strict correct/N; optional (correct+0.5*partial)/N. All gold questions remain in denominator; failures count incorrect, never refusals."}


def save_new(path, payload):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run_evaluation(service, gold, ood, output, demo=False, resume=None):
    output = Path(output)
    ratings_path = output.with_name(output.stem + "_ratings.csv")
    if output.exists() or ratings_path.exists():
        raise FileExistsError("Choose new run and rating paths; prior records are never overwritten")
    cfg = service.settings
    if not cfg.api_key:
        raise ValueError("Configure LLM_API_KEY locally before a real evaluation")
    rows = load_questions(gold, ood)
    if demo:
        wanted = {"B02", "B05", "B06", "B23", "B24", "OOD01"}
        rows = [row for row in rows if row["id"] in wanted]
        if len(rows) != 6:
            raise ValueError("Demo requires B02/B05/B06/B23/B24/OOD01")
    benchmark = cfg.experiment_dir / "benchmark.json"
    catalog = cfg.experiment_dir / "temporal_catalog.json"
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.SubprocessError):
        commit, dirty = None, None
    run = {"run_at_utc": datetime.now(timezone.utc).isoformat(), "kind": "demo" if demo else "formal",
           "git_commit": commit, "worktree_dirty": dirty,
           "gold_sha256": digest(gold), "ood_sha256": digest(ood),
           "benchmark_sha256": digest(benchmark), "temporal_catalog_sha256": digest(catalog),
           "prompt_version": PROMPT_VERSION, "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
           "app_source_sha256": {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")},
           "provider": cfg.base_url, "requested_model": cfg.model, "temperature": 0,
           "max_output_tokens": cfg.max_tokens, "timeout_seconds": cfg.timeout,
           "thinking": cfg.thinking, "json_mode": cfg.json_mode,
           "top_k": cfg.top_k, "collection": cfg.collection, "arm": cfg.arm,
           "max_distance": cfg.max_distance, "python": platform.python_version(),
           "dependencies": {name: version(name) for name in ("httpx", "streamlit", "chromadb", "sentence-transformers")},
           "records": []}
    retained = {}
    if resume:
        original = json.loads(Path(resume).read_text(encoding="utf-8"))
        for key in ("kind", "gold_sha256", "ood_sha256", "benchmark_sha256", "temporal_catalog_sha256",
                    "prompt_sha256", "provider", "requested_model", "temperature", "max_output_tokens",
                    "thinking", "json_mode", "top_k", "collection", "arm", "max_distance"):
            if original[key] != run[key]:
                raise ValueError(f"Cannot resume after changing {key}; run a separate full evaluation")
        for name in ("config.py", "grounding.py", "llm.py", "service.py"):
            if original["app_source_sha256"][name] != run["app_source_sha256"][name]:
                raise ValueError("Cannot resume after changing generation code")
        old_records = {row["id"]: row for row in original["records"]}
        if set(old_records) != {row["id"] for row in rows}:
            raise ValueError("Resume question IDs differ")
        # Never retry incorrect/partial/refused/invalid-output answers to improve a score.
        retained = {key: row for key, row in old_records.items()
                    if row["result"]["status"] not in {"llm_error", "retrieval_error", "not_run"}}
        run["resume"] = {"source_path": str(resume), "source_sha256": digest(resume),
                         "retained_ids": list(retained), "original_timeout_seconds": original["timeout_seconds"],
                         "note": "Only service failures and unexecuted questions retried; previous attempts preserved at source_path."}
    # Reserve output before spending any tokens; checkpoint each completed request.
    save_new(output, run)
    with ratings_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "verdict", "citation_verdict", "failure_stage", "reason", "reviewer"])
        writer.writeheader()
        writer.writerows({"id": row["id"], "verdict": "pending", "citation_verdict": "pending"} for row in rows)
    stop = False
    for row in rows:
        if row["id"] in retained:
            saved = retained[row["id"]]
            # Preserve the timeout actually used by the original request.
            saved.setdefault("request_timeout_seconds", original["timeout_seconds"])
            run["records"].append(saved)
            output.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f'{row["id"]}: retained {saved["result"]["status"]}', flush=True)
            continue
        result = ({"status": "not_run", "answer": "", "citations": [], "error": "Stopped after an infrastructure failure"}
                  if stop else service.answer_question(row["question"]))
        run["records"].append({**row, "request_timeout_seconds": cfg.timeout, "result": result})
        output.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f'{row["id"]}: {result["status"]}', flush=True)
        # Avoid repeated paid failures; invalid_output is retained but does not stop the batch.
        if result["status"] in {"llm_error", "retrieval_error"}:
            stop = True
    return run
