"""Run real QA/OOD generation, then summarize independent human ratings."""
import argparse
import csv
import json
from pathlib import Path

from rag_app.config import ROOT, Settings
from rag_app.evaluation import metrics, run_evaluation, save_new
from rag_app.service import create_service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--gold", type=Path, default=ROOT / "data/evaluation/qa_gold.jsonl")
    run.add_argument("--ood", type=Path, default=ROOT / "data/evaluation/ood_questions.jsonl")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--demo", action="store_true")
    run.add_argument("--resume", type=Path, help="Retain completed records; retry only service failures and not_run")
    summary = commands.add_parser("summarize")
    summary.add_argument("--run", type=Path, required=True)
    summary.add_argument("--ratings", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        settings = Settings.from_env()
        if not settings.api_key:
            parser.error("Set LLM_API_KEY in the local .env before running a real evaluation")
        run_evaluation(create_service(settings), args.gold, args.ood, args.output, args.demo, args.resume)
    else:
        run_data = json.loads(args.run.read_text(encoding="utf-8"))
        if run_data["kind"] != "formal":
            parser.error("Demo runs cannot be reported as formal answer accuracy")
        with args.ratings.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if len({row["id"] for row in rows}) != len(rows):
            parser.error("Duplicate rating IDs")
        result = metrics(run_data["records"], {r["id"]: r for r in rows})
        save_new(args.output, {"run": str(args.run), **result})
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
