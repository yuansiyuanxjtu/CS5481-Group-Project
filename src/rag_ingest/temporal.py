"""Evidence-backed document metadata, separate from the unchanged CSV/Chunk schema."""
from datetime import date
import json
from pathlib import Path
from urllib.parse import urlsplit
import re

FIELDS = {"document_id", "title", "issuing_organization", "publication_date", "jurisdiction",
          "original_source_url", "source_pdf_url", "document_checksum", "regulatory_status",
          "status_verified_at"}


def load_temporal_catalog(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Temporal catalog root must be an object")
    documents = payload.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("Temporal catalog must contain a nonempty documents list")
    result = {}
    for row in documents:
        if not isinstance(row, dict) or not FIELDS <= row.keys():
            raise ValueError("Temporal catalog is missing required document fields")
        for key in FIELDS - {"status_verified_at"}:
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"Temporal {key} must be a nonempty string")
        date.fromisoformat(row["publication_date"])
        if row["document_id"] in result:
            raise ValueError("Duplicate temporal document_id")
        if not re.fullmatch(r"[a-f0-9]{64}", row["document_checksum"]):
            raise ValueError("document_checksum must be a lowercase SHA-256 digest")
        for key in ("original_source_url", "source_pdf_url"):
            parsed = urlsplit(row[key])
            if parsed.scheme not in {"https", "http"} or not parsed.netloc:
                raise ValueError(f"Invalid temporal {key}")
        status = row["regulatory_status"]
        if status not in {"unknown", "current", "superseded", "withdrawn", "non_binding"}:
            raise ValueError("Unsupported regulatory_status")
        if status != "unknown":
            if not row["status_verified_at"] or not row.get("status_evidence"):
                raise ValueError("Known status requires official evidence and status_verified_at")
            date.fromisoformat(row["status_verified_at"])
            evidence = row["status_evidence"]
            if not isinstance(evidence, dict) or not evidence.get("url") or not evidence.get("locator"):
                raise ValueError("Status evidence needs an official URL and locator")
            issuer_hosts = {urlsplit(row[k]).hostname for k in ("original_source_url", "source_pdf_url")}
            if urlsplit(evidence["url"]).hostname not in issuer_hosts:
                raise ValueError("Status evidence must be hosted by the document's official issuer")
        elif row["status_verified_at"] is not None:
            raise ValueError("Unknown status must use null status_verified_at")
        result[row["document_id"]] = row
    return result


def storage_metadata(row: dict) -> dict:
    """Scalar-only Chroma metadata; full evidence stays in the sidecar catalog."""
    return {key: (row[key] if row[key] is not None else "") for key in FIELDS}
