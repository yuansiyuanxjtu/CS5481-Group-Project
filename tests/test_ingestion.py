import json

import pytest

from rag_ingest.chunking import STRATEGIES, Strategy, chunk_page
from rag_ingest.manifest import load_manifest
from rag_ingest.models import Page
from rag_ingest.pdf import clean_text, load_pdf
from rag_ingest.pipeline import run_pipeline


def test_pdf_extraction_and_empty_pages(corpus):
    sources = load_manifest(*corpus)
    pages = list(load_pdf(sources[0]))
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert pages[0].text == "Banking risk governance."
    assert pages[1].text == ""
    assert pages[2].text == "AI model oversight."
    assert pages[2].source_file == "alpha.pdf"
    assert pages[2].source_url == "https://example.invalid/alpha.pdf"
    assert pages[2].document_id == "doc001"


@pytest.mark.parametrize("text,expected", [
    ("  A\r\nB\t C\u00a0D  ", "A B C D"),
    ("ﬁnance\x00\u200b rules", "finance rules"),
    ("Policy-2026, Section 3.1", "Policy-2026, Section 3.1"),
    ("\n\t ", ""),
])
def test_cleaning(text, expected):
    assert clean_text(text) == expected
    assert clean_text(clean_text(text)) == expected


def page(text):
    return Page("doc001", "alpha.pdf", "https://example.invalid/alpha.pdf", 3, text)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_sizes_overlap_metadata_and_ids(tokenizer, strategy):
    original = page(" ".join(["bank", "risk", "policy", "model", "control"] * 130))
    chunks = list(chunk_page(original, tokenizer, strategy))
    original_ids = tokenizer.encode(original.text, add_special_tokens=False)
    reconstructed = []
    prior = None
    for index, chunk in enumerate(chunks, 1):
        ids = tokenizer.encode(chunk.text, add_special_tokens=False)
        assert chunk.token_count == len(ids) <= strategy.size
        if index < len(chunks):
            assert len(ids) == strategy.size
        if prior is not None and strategy.overlap:
            assert prior[-strategy.overlap:] == ids[:strategy.overlap]
        reconstructed.extend(ids[strategy.overlap:] if prior is not None else ids)
        prior = ids
        assert chunk.chunk_id == f"doc001_p3_c{index}_{strategy.name}"
        assert (chunk.document_id, chunk.source_file, chunk.source_url, chunk.page_number) == (
            original.document_id, original.source_file, original.source_url, 3)
        assert chunk.chunk_strategy == strategy.name
    assert reconstructed == original_ids
    assert chunks == list(chunk_page(original, tokenizer, strategy))
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_empty_and_short_pages(tokenizer):
    for strategy in STRATEGIES:
        assert list(chunk_page(page(""), tokenizer, strategy)) == []
        chunks = list(chunk_page(page("Bank risk."), tokenizer, strategy))
        assert len(chunks) == 1
        assert chunks[0].text == "Bank risk."


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_wordpiece_boundaries_preserve_substrings_and_budget(tokenizer, strategy):
    text = " ".join(["unpredictability counterintuitiveness compliance-oriented"] * 150)
    chunks = list(chunk_page(page(text), tokenizer, strategy))
    assert len(chunks) > 2
    assert all(c.text in text and 0 < c.token_count <= strategy.size for c in chunks)
    assert all(c.token_count == len(tokenizer.encode(c.text, add_special_tokens=False)) for c in chunks)


def test_jsonl_multi_pdf_repeatability_and_page_boundaries(corpus, tokenizer, tmp_path):
    out = tmp_path / "processed"
    counts = run_pipeline(*corpus, out, tokenizer)
    first = {p.name: p.read_bytes() for p in out.glob("*.jsonl")}
    assert counts == {s.name: 4 for s in STRATEGIES}
    all_ids = []
    for strategy in STRATEGIES:
        chunks = [json.loads(line) for line in (out / f"{strategy.name}.jsonl").read_text().splitlines()]
        assert [(c["document_id"], c["page_number"]) for c in chunks] == [
            ("doc001", 1), ("doc001", 3), ("doc002", 1), ("doc002", 3)]
        assert all(set(c) == {"chunk_id", "document_id", "source_file", "source_url", "page_number", "text", "chunk_strategy", "token_count"} for c in chunks)
        all_ids.extend(c["chunk_id"] for c in chunks)
    assert len(set(all_ids)) == len(all_ids)
    run_pipeline(*corpus, out, tokenizer)
    assert first == {p.name: p.read_bytes() for p in out.glob("*.jsonl")}


@pytest.mark.parametrize("body", [
    "", "doc001,alpha.pdf,\n", "../doc,alpha.pdf,https://example.invalid/a\n",
    "doc001,../escape.pdf,https://example.invalid/a\n",
    "doc001,missing.pdf,https://example.invalid/a\n",
    "doc001,alpha.pdf,https://example.invalid/a\ndoc001,beta.pdf,https://example.invalid/b\n",
    "doc001,alpha.pdf,https://example.invalid/a\ndoc002,alpha.pdf,https://example.invalid/b\n",
    "doc001,alpha.pdf\n", "doc001,alpha.pdf,https://example.invalid/a,extra\n",
])
def test_invalid_manifest(corpus, body):
    manifest, raw = corpus
    manifest.write_text("document_id,source_file,source_url\n" + body)
    with pytest.raises(ValueError):
        load_manifest(manifest, raw)


def test_parsing_failure_preserves_outputs(corpus, tokenizer, tmp_path):
    manifest, raw = corpus
    out = tmp_path / "processed"
    run_pipeline(manifest, raw, out, tokenizer)
    before = {p.name: p.read_bytes() for p in out.glob("*.jsonl")}
    (raw / "beta.pdf").write_bytes(b"not a pdf")
    with pytest.raises(Exception):
        run_pipeline(manifest, raw, out, tokenizer)
    assert before == {p.name: p.read_bytes() for p in out.glob("*.jsonl")}
    assert not list(out.glob(".ingest-*"))


@pytest.mark.parametrize("size,overlap", [(0, 0), (150, 150), (150, -1)])
def test_invalid_strategy(size, overlap):
    with pytest.raises(ValueError):
        Strategy("bad", size, overlap)


def test_cli_offline_and_empty_manifest(corpus, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    manifest, raw = corpus
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "cli-output"
    command = [sys.executable, "-m", "rag_ingest", "--manifest", str(manifest),
               "--pdf-dir", str(raw), "--output-dir", str(output),
               "--cache-dir", str(root / ".cache/huggingface/hub"), "--offline"]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "fixed_150: 4 chunks" in result.stdout
    assert "fixed_220_overlap_30: 4 chunks" in result.stdout
    assert len(list(output.glob("*.jsonl"))) == 2
    manifest.write_text("document_id,source_file,source_url\n")
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 1
    assert "Manifest contains no PDF sources" in result.stderr
