"""Explicit, bounded download of the five preselected official pilot PDFs.

No crawling, retries, authentication, or access-control bypass. Existing files are
verified and reused. Run manually; this is not part of the ingestion pipeline.
"""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf
import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/catalog/pilot_sources.json"
ALLOWED_HOSTS = {"brdr.hkma.gov.hk", "www.fsb.org", "www.bis.org"}


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    documents = catalog["documents"]
    if len(documents) != 5 or len({d["document_id"] for d in documents}) != 5:
        raise ValueError("This pilot is limited to exactly five distinct registered documents")
    raw = ROOT / "data/raw"
    raw.mkdir(exist_ok=True, parents=True)
    seen = set()
    for row in documents:
        path = raw / row["source_file"]
        if path.name != row["source_file"] or path.suffix != ".pdf":
            raise ValueError("Pilot filenames must be simple PDF basenames")
        url = row["direct_pdf_url"]
        if urlsplit(url).hostname not in ALLOWED_HOSTS:
            raise ValueError("Not a registered official source")
        try:
            if path.exists():
                content = path.read_bytes()
                if not row.get("sha256") or hashlib.sha256(content).hexdigest() != row["sha256"]:
                    raise ValueError("Existing PDF is unregistered or differs from the catalog; inspect it manually")
                print(f'{row["document_id"]}: verified existing file; no network request', flush=True)
            else:
                with requests.get(url, timeout=60, stream=True) as response:
                    response.raise_for_status()
                    if urlsplit(response.url).hostname not in ALLOWED_HOSTS:
                        raise ValueError("Redirect left the official source hosts")
                    blocks, total = [], 0
                    for block in response.iter_content(65536):
                        total += len(block)
                        if total > 25 * 1024 * 1024:
                            raise ValueError("PDF exceeds this pilot's 25 MiB safety limit")
                        blocks.append(block)
                    content = b"".join(blocks)
                    row.update(http_status=response.status_code, resolved_pdf_url=response.url,
                               content_type=response.headers.get("Content-Type"),
                               downloaded_at_utc=datetime.now(timezone.utc).isoformat())
            if not content.startswith(b"%PDF-"):
                raise ValueError("Response is not a PDF (HTML/access denial will not be saved)")
            digest = hashlib.sha256(content).hexdigest()
            if row.get("sha256") and digest != row["sha256"]:
                raise ValueError("Downloaded PDF checksum differs from the pinned catalog; refusing to replace the dataset snapshot")
            if digest in seen:
                raise ValueError("Duplicate PDF checksum")
            with pymupdf.open(stream=content, filetype="pdf") as doc:
                if doc.needs_pass or len(doc) == 0:
                    raise ValueError("Encrypted or empty PDF")
                pages = len(doc)
                # Force extraction on every page; parser errors are failures.
                for page in doc:
                    page.get_text("text", sort=True)
            seen.add(digest)
            if not path.exists():
                path.write_bytes(content)
            row.update(status="downloaded_and_pdf_validated", sha256=digest,
                       byte_size=len(content), pdf_pages=pages)
            print(f'{row["document_id"]}: {pages} pages, {len(content)} bytes, SHA-256 {digest}', flush=True)
        except (requests.RequestException, ValueError, RuntimeError) as error:
            row.update(status="failed", error=str(error))
            CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            raise
        CATALOG.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = ROOT / "data/sources.csv"
    with manifest.open(newline="", encoding="utf-8") as stream:
        existing = list(csv.DictReader(stream))
    expected = [{"document_id": d["document_id"], "source_file": d["source_file"],
                 "source_url": d["direct_pdf_url"]} for d in documents]
    if existing and existing != expected:
        raise ValueError("Manifest contains other records; refusing to replace them")
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["document_id", "source_file", "source_url"])
        writer.writeheader()
        writer.writerows(expected)


if __name__ == "__main__":
    main()
