"""Phase 2.6 conservative cleaning, metadata and isolated benchmark contracts."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from rag_ingest.chunking import EXPERIMENT_STRATEGIES, STRATEGIES, chunk_page
from rag_ingest.models import Page
from rag_ingest.pipeline import run_pipeline
from rag_ingest.quality import (BIS_FOOTERS, analyze_chunks, conservative_page,
                                enhance_pdf, is_page_label, repeated_margins)
from rag_ingest.temporal import load_temporal_catalog, storage_metadata
from rag_ingest.vector_store import ingest_jsonl, open_collection
from rag_ingest.embeddings import EmbeddingSpec


class SmallEncoder:
    spec = EmbeddingSpec(model_name="test/phase26", model_revision="fixture", encoder="test-only")

    def encode(self, texts, batch_size):
        out = np.zeros((len(texts), 384), dtype=np.float32)
        for i, text in enumerate(texts):
            out[i, int(hashlib.sha256(text.encode()).hexdigest(), 16) % 384] = 1
        return out


def geometry(text, position="bottom"):
    return {"text": text, "position": position, "bbox": [0, 800, 50, 810]}


@pytest.mark.parametrize("label", ["iv", "- 2 -", "1", "xxxix", "VIII"])
def test_page_label_detection(label):
    assert is_page_label(label)


@pytest.mark.parametrize("text", ["civil", "mixing", "1. Scope", "Article IV", "2.5%", "", "AI"])
def test_legitimate_text_is_not_page_label(text):
    assert not is_page_label(text)


def test_conservative_removal_preserves_regulatory_words_numbers_and_short_sections():
    body = "Banks must not disclose personal data. Article 1 requires a 2.5% buffer.\nScope: banks."
    raw = body + "\n1\n"
    cleaned, changes = conservative_page(raw, [geometry("1")])
    assert cleaned == body.replace("\n", " ")
    assert changes == [{"text": "1", "rules": ["margin_page_label"]}]
    short, changes = conservative_page("Scope: banks.", [])
    assert short == "Scope: banks." and changes == []
    blank, changes = conservative_page("iv\n", [geometry("iv")])
    assert blank == "" and len(changes) == 1
    year, changes = conservative_page("2026", [geometry("2026")], maximum_page_label=8)
    assert year == "2026" and changes == []


def test_header_detection_does_not_authorize_deletion():
    pages = [[geometry("Important legal notice", "top")] for _ in range(4)]
    assert repeated_margins(pages) == [{"position": "top", "text": "Important legal notice", "pages": 4}]
    text, changes = conservative_page("Important legal notice\nBanks must comply.", pages[0])
    assert text.startswith("Important legal notice") and not changes


def test_reviewed_footer_removal_and_ambiguous_body_protection():
    title, noise = sorted(BIS_FOOTERS, key=len, reverse=True)
    margin = [geometry("2"), geometry(title), geometry(noise)]
    text, changes = conservative_page(f"Banks must comply.\n2{noise}  {title}", margin, approved_footers=BIS_FOOTERS)
    assert text == "Banks must comply." and len(changes) == 1
    body = f"Article 2 discusses {title}"
    text, changes = conservative_page(body, margin, approved_footers=BIS_FOOTERS)
    assert text == body and not changes
    text, changes = conservative_page(f"{title}\n{title}", margin, approved_footers=BIS_FOOTERS)
    assert text == f"{title} {title}" and not changes


def temporal_rows(corpus):
    manifest, raw = corpus
    result = []
    for doc_id, filename in [("doc001", "alpha.pdf"), ("doc002", "beta.pdf")]:
        url = "https://example.invalid/" + filename
        result.append({"document_id": doc_id, "title": "Synthetic fixture", "issuing_organization": "Test issuer",
                       "publication_date": "2020-01-01", "jurisdiction": "Test only",
                       "original_source_url": url, "source_pdf_url": url,
                       "document_checksum": hashlib.sha256((raw / filename).read_bytes()).hexdigest(),
                       "regulatory_status": "unknown", "status_verified_at": None})
    return result


def test_temporal_unknown_and_evidence_requirements(corpus, tmp_path):
    rows = temporal_rows(corpus)
    path = tmp_path / "temporal.json"
    path.write_text(json.dumps({"documents": rows}))
    parsed = load_temporal_catalog(path)
    assert parsed["doc001"]["regulatory_status"] == "unknown"
    assert storage_metadata(parsed["doc001"])["status_verified_at"] == ""
    rows[0].update(regulatory_status="superseded", status_verified_at="2026-11-03")
    path.write_text(json.dumps({"documents": rows}))
    with pytest.raises(ValueError, match="evidence"):
        load_temporal_catalog(path)
    rows[0]["status_evidence"] = {"url": "https://example.invalid/new.pdf", "locator": "page 1"}
    path.write_text(json.dumps({"documents": rows}))
    assert load_temporal_catalog(path)["doc001"]["regulatory_status"] == "superseded"
    rows[0]["status_evidence"]["url"] = "https://other.invalid/claim"
    path.write_text(json.dumps({"documents": rows}))
    with pytest.raises(ValueError, match="official issuer"):
        load_temporal_catalog(path)


@pytest.mark.parametrize("strategy", EXPERIMENT_STRATEGIES)
def test_all_four_strategies_deterministic_cited_and_model_safe(strategy, tokenizer):
    page = Page("doc001", "fixture.pdf", "https://example.invalid/a", 7, "Bank risk control. " * 250)
    chunks = list(chunk_page(page, tokenizer, strategy))
    assert chunks == list(chunk_page(page, tokenizer, strategy))
    assert all(c.page_number == 7 and c.source_url == page.source_url for c in chunks)
    assert all(c.text in page.text and c.token_count <= strategy.size for c in chunks)
    assert all(len(tokenizer.encode(c.text, add_special_tokens=True)) <= 256 for c in chunks)
    ids = [tokenizer.encode(c.text, add_special_tokens=False) for c in chunks]
    if strategy.overlap:
        assert all(a[-strategy.overlap:] == b[:strategy.overlap] for a, b in zip(ids, ids[1:]))
    assert len(STRATEGIES) == 2  # Legacy defaults stay unchanged.


def test_quality_diagnostics_missing_metadata_duplicates_and_page_integrity(tokenizer):
    page = Page("doc001", "a.pdf", "https://example.invalid/a", 1, "iv")
    row = asdict(next(chunk_page(page, tokenizer, STRATEGIES[0])))
    stats = analyze_chunks([row, row, {"text": "bad"}], tokenizer, {("doc001", 1): page}, 150)
    assert stats["page_number_only_chunks"] == 2
    assert stats["exact_duplicate_texts"] == 1
    assert stats["duplicate_chunk_ids"] == 1
    assert stats["missing_citation_or_required_fields"] == 1
    assert stats["invalid_chunks"] == 2
    bad = dict(row, page_number=2)
    assert analyze_chunks([bad], tokenizer, {("doc001", 1): page}, 150)["citation_integrity_failures"] == 1
    year_page = replace(page, text="Published in 2026")
    year = dict(row, text="2026", token_count=len(tokenizer.encode("2026", add_special_tokens=False)))
    result = analyze_chunks([year], tokenizer, {("doc001", 1): year_page}, 150)
    assert result["page_label_candidates"] == 1 and result["page_number_only_chunks"] == 0
    assert conservative_page("Published in 2026", [])[0] == "Published in 2026"


def test_isolated_benchmark_repeated_records_and_baseline_compatibility(corpus, tokenizer, tmp_path, monkeypatch):
    from rag_ingest import benchmark
    baseline = tmp_path / "baseline"
    run_pipeline(*corpus, baseline, tokenizer)
    original_hashes = {p.name: benchmark.digest(p) for p in baseline.glob("*.jsonl")}
    catalog = tmp_path / "temporal.json"
    catalog.write_text(json.dumps({"documents": temporal_rows(corpus)}))
    monkeypatch.setattr(benchmark, "load_tokenizer", lambda *a, **k: tokenizer)
    monkeypatch.setattr(benchmark, "MiniLMEncoder", lambda *a, **k: SmallEncoder())
    output = tmp_path / "run"
    report = benchmark.run_benchmark(*corpus, baseline, catalog, output, "unused", batch_size=2)
    assert len(report["arms"]) == 2
    assert {p.name: benchmark.digest(p) for p in baseline.glob("*.jsonl")} == original_hashes
    for arm in report["arms"].values():
        assert len(arm["strategies"]) == 4
        assert all(r["repeat_snapshot_identical"] and r["quality"]["invalid_chunks"] == 0
                   for r in arm["strategies"].values())
    context = json.loads((output / "enhanced/collection_context.json").read_text())
    collection = open_collection(output / "enhanced/chroma", "fixed_150", SmallEncoder.spec, context=context)
    stored = collection.get(limit=1)["metadatas"][0]
    assert stored["document_checksum"] and stored["title"] == "Synthetic fixture"
    assert stored["regulatory_status"] == "unknown"
    with pytest.raises(ValueError, match="already exists"):
        benchmark.run_benchmark(*corpus, baseline, catalog, output, "unused")
    with pytest.raises(ValueError, match="requires"):
        ingest_jsonl([output / "enhanced/fixed_150.jsonl"], output / "enhanced/chroma", SmallEncoder())
    temporal = load_temporal_catalog(catalog)
    # A catalog auto-adds a fingerprint: this partial, nonempty context must not
    # bypass the existing collection's cleaning/dataset-version requirements.
    with pytest.raises(ValueError, match="complete original context"):
        ingest_jsonl([output / "enhanced/fixed_150.jsonl"], output / "enhanced/chroma", SmallEncoder(),
                     document_metadata=temporal, context={"dataset_version": context["dataset_version"]})
    assert collection.count() == report["arms"]["enhanced"]["strategies"]["fixed_150"]["records"]
    temporal["doc001"]["title"] = "Changed fixture title"
    with pytest.raises(ValueError, match="Incompatible"):
        ingest_jsonl([output / "enhanced/fixed_150.jsonl"], output / "enhanced/chroma", SmallEncoder(),
                     document_metadata=temporal, context=context)
