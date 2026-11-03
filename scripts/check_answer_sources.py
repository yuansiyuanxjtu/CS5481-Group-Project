"""Check gold locators and generated quotations against checksum-pinned physical PDF pages."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import pymupdf

from rag_app.config import ROOT
from rag_app.evaluation import digest, save_new
from rag_ingest.pdf import clean_text
from rag_ingest.temporal import load_temporal_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf-8"))
    catalog_path = ROOT / "data/catalog/temporal_metadata.json"
    if digest(catalog_path) != run["temporal_catalog_sha256"]:
        raise ValueError("Current temporal catalog differs from the evaluated snapshot")
    catalog = load_temporal_catalog(catalog_path)
    with (ROOT / "data/sources.csv").open(newline="", encoding="utf-8") as stream:
        manifest = {row["document_id"]: row for row in csv.DictReader(stream)}
    pages = {}
    for doc_id, row in catalog.items():
        path = ROOT / "data/raw" / manifest[doc_id]["source_file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["document_checksum"]:
            raise ValueError("Raw PDF no longer matches the frozen snapshot")
        with pymupdf.open(path) as pdf:
            pages[doc_id] = [clean_text(page.get_text("text", sort=True)) for page in pdf]
    checks = []
    for record in run["records"]:
        for label in record.get("evidence", []):
            source = pages[label["document_id"]]
            text = " ".join(source[label["page_start"] - 1:label["page_end"]])
            checks.append({"id": record["id"], "kind": "gold_excerpt", "document_id": label["document_id"],
                           "physical_page": label["page_start"], "present": clean_text(label["excerpt"]) in text})
        for citation in record["result"]["citations"]:
            row = catalog[citation["document_id"]]
            source = pages[citation["document_id"]]
            page = citation["page_number"]
            for quote in citation["excerpts"]:
                present = (citation["source_url"] == row["source_pdf_url"] and 1 <= page <= len(source)
                           and clean_text(quote) in source[page - 1])
                checks.append({"id": record["id"], "kind": "answer_quote", "document_id": citation["document_id"],
                               "physical_page": page, "present": present})
    save_new(args.output, {"run_sha256": digest(args.run), "checks": checks,
                           "all_present": all(row["present"] for row in checks),
                           "limitation": "Automated substring/provenance check only; does not establish semantic correctness or human verification."})
    print(f'{len(checks)} source checks; {sum(not c["present"] for c in checks)} failures')
    if not all(row["present"] for row in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
