"""Conservative, auditable page cleanup and lightweight data quality diagnostics.

Detection is broader than deletion. No short body section is dropped. Original
PDFs and baseline outputs are never modified by these functions.
"""
from collections import Counter
from dataclasses import asdict, replace
import re
import unicodedata

import pymupdf

from .models import Chunk, Page, Source
from .pdf import clean_text

CLEANING_VERSION = "conservative_margins_v1"
# Manually reviewed BIS bottom-margin strings. Automatic recurrence alone does
# not authorize deleting headings, legal notices, footnotes, or other prose.
BIS_FOOTERS = {
    "Regulating AI in the financial sector: recent developments and main challenges",
    "and possible developments and possible developments",
}


def is_page_label(text: str) -> bool:
    text = text.strip().strip("-–— ").lower()
    if re.fullmatch(r"[1-9][0-9]{0,3}", text):
        return True
    return bool(text and re.fullmatch(r"m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})", text))


def margin_lines(page) -> list[dict]:
    result = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = clean_text("".join(span["text"] for span in line["spans"]))
            x0, y0, x1, y1 = line["bbox"]
            center = (y0 + y1) / 2
            if text and (center < .06 * page.rect.height or center > .94 * page.rect.height):
                result.append({"text": text, "bbox": list(line["bbox"]),
                               "position": "top" if center < page.rect.height / 2 else "bottom"})
    return result


def repeated_margins(pages: list[list[dict]]) -> list[dict]:
    counts = Counter((line["position"], line["text"]) for page in pages
                     for line in { (r["position"], r["text"]): r for r in page }.values()
                     if not is_page_label(line["text"]))
    return [{"position": side, "text": text, "pages": count}
            for (side, text), count in sorted(counts.items()) if count >= 3]


def conservative_page(raw: str, geometry: list[dict], *, approved_footers: set[str] | None = None,
                      maximum_page_label: int = 999) -> tuple[str, list[dict]]:
    approved_footers = approved_footers or set()
    allowed = []
    for item in geometry:
        text = item["text"]
        if is_page_label(text):
            number = text.strip().strip("-–— ")
            if number.isdigit() and int(number) > maximum_page_label:
                continue  # Do not treat publication years/article codes as page labels.
            allowed.append((text, "margin_page_label"))
        elif item["position"] == "bottom" and text in approved_footers:
            allowed.append((text, "reviewed_footer"))
    kept, removed = [], []
    # Sorted extraction can concatenate a footer, page label and hidden fragment.
    # Delete a whole extracted line only if it consists entirely of approved
    # geometry-confirmed margin components. Mixed body/margin lines remain.
    for line in raw.splitlines():
        compact = re.sub(r"\s+", "", line)
        remaining = compact
        used = []
        for text, rule in sorted(allowed, key=lambda x: len(x[0]), reverse=True):
            atom = re.sub(r"\s+", "", text)
            if atom and atom in remaining:
                remaining = remaining.replace(atom, "", 1)
                used.append(rule)
        # A body occurrence identical to a margin string is ambiguous; retain it.
        occurrences = sum(re.sub(r"\s+", "", part) == compact for part in raw.splitlines())
        if compact and not remaining and used and occurrences == 1:
            removed.append({"text": clean_text(line), "rules": sorted(set(used))})
        else:
            kept.append(line)
    return clean_text("\n".join(kept)), removed


def enhance_pdf(source: Source) -> tuple[list[Page], dict]:
    pages, margins, changes = [], [], []
    approved = BIS_FOOTERS if source.document_id == "bis_20241212_ai_regulation" else set()
    with pymupdf.open(source.path) as pdf:
        if pdf.needs_pass:
            raise ValueError("Password-protected PDF")
        for number, page in enumerate(pdf, 1):
            raw = page.get_text("text", sort=True)
            geometry = margin_lines(page)
            margins.append(geometry)
            text, removals = conservative_page(raw, geometry, approved_footers=approved,
                                              maximum_page_label=len(pdf))
            pages.append(Page(source.document_id, source.source_file, source.source_url, number, text))
            if removals:
                changes.append({"page_number": number, "before": clean_text(raw), "after": text,
                                "removed_lines": removals})
    return pages, {"document_id": source.document_id, "repeated_margins": repeated_margins(margins), "changes": changes}


def analyze_pages(pages: list[Page]) -> dict:
    nonempty = [p.text for p in pages if p.text]
    return {"pages": len(pages), "characters": sum(len(p.text) for p in pages),
            "empty_pages": sum(not p.text for p in pages),
            "nearly_empty_pages": sum(0 < len(p.text) < 100 for p in pages),
            "page_label_only_pages": sum(is_page_label(p.text) for p in pages),
            "exact_duplicate_nonempty_pages": len(nonempty) - len(set(nonempty))}


def analyze_chunks(rows: list[dict], tokenizer, pages: dict[tuple[str, int], Page], size: int) -> dict:
    counts = Counter()
    lengths = []
    seen_ids, seen_text = set(), set()
    for row in rows:
        invalid = False
        required = ["chunk_id", "document_id", "source_file", "source_url", "page_number", "text", "chunk_strategy", "token_count"]
        if any(key not in row or row[key] in (None, "") for key in required):
            counts["missing_citation_or_required_fields"] += 1
            counts["invalid_chunks"] += 1
            continue
        text = row["text"]
        actual = len(tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False))
        lengths.append(actual)
        if actual > size or actual != row["token_count"] or actual == 0:
            counts["invalid_token_counts"] += 1
            invalid = True
        # MiniLM reserves two special tokens; verify the effective limit explicitly.
        if len(tokenizer.encode(text, add_special_tokens=True, truncation=False, verbose=False)) > 256:
            counts["model_limit_violations"] += 1
            invalid = True
        page = pages.get((row["document_id"], row["page_number"]))
        if (page is None or text not in page.text or row["source_url"] != page.source_url
                or row["source_file"] != page.source_file):
            counts["citation_integrity_failures"] += 1
            invalid = True
        if row["chunk_id"] in seen_ids:
            counts["duplicate_chunk_ids"] += 1
            invalid = True
        seen_ids.add(row["chunk_id"])
        counts["exact_duplicate_texts"] += text in seen_text
        seen_text.add(text)
        counts["page_label_candidates"] += is_page_label(text)
        # A bare year such as 2026 can be a valid footnote remainder. Only call
        # a chunk page-number-only when the whole source page is label-only.
        counts["page_number_only_chunks"] += bool(is_page_label(text) and page is not None and page.text.strip() == text.strip())
        counts["suspiciously_short_chunks"] += actual < 10
        counts["malformed_text_chunks"] += bool("\ufffd" in text or any(unicodedata.category(c).startswith("C") for c in text))
        if page is not None and text in page.text:
            start = page.text.find(text)
            end = start + len(text)
            counts["mid_word_starts"] += bool(start and text[0].isalnum() and page.text[start - 1].isalnum())
            counts["mid_word_ends"] += bool(end < len(page.text) and text[-1].isalnum() and page.text[end].isalnum())
            counts["non_sentence_ends"] += bool(end < len(page.text) and text[-1] not in '.!?;:"”)]')
        counts["invalid_chunks"] += invalid
    import numpy as np
    distribution = {f"p{p}": float(np.percentile(lengths, p)) if lengths else 0 for p in [0, 25, 50, 75, 95, 100]}
    keys = ["missing_citation_or_required_fields", "invalid_chunks", "invalid_token_counts", "model_limit_violations",
            "citation_integrity_failures", "duplicate_chunk_ids", "exact_duplicate_texts", "page_number_only_chunks",
            "page_label_candidates", "suspiciously_short_chunks", "malformed_text_chunks", "mid_word_starts", "mid_word_ends", "non_sentence_ends"]
    return {"count": len(rows), **{key: counts[key] for key in keys}, "token_distribution": distribution,
            "average_tokens": sum(lengths) / len(lengths) if lengths else 0}
