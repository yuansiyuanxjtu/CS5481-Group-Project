# Member A integration-readiness review

Review date: 3 November 2026 (Asia/Hong_Kong).

**Verdict: ready for the first team handoff on the documented Python 3.11/macOS arm64 environment, after the pending source/docs/tests are included in an approved commit. No commit or push was performed.** No dataset expansion or new application/retrieval feature was added.

## Validation performed

- Original full suite: **81 passed**, including the cached real-model test.
- After critical fixes: **82 passed**, including one new acquisition-integrity test and expanded version-context regression assertions. The final run reported 57 dependency deprecation warnings and no failures.
- Five PDF checksums and all 165 physical pages checked. The original two JSONL outputs were regenerated in memory and matched byte-for-byte.
- All **6,844 stored records across ten collections** checked: two original pilot collections, four baseline experiment collections and four enhanced experiment collections. IDs, texts, citation/temporal metadata, vector dimension and normalization matched inputs.
- Twenty query hits checked using Member B's public access interface. Citation fields and temporal sidecar joins were checked for Member C. Database checks were performed on temporary copies, preserving original stores.
- Original PDFs, JSONL outputs and pilot database files remained byte-identical to the baseline snapshot after review.
- Local package build/install, imports outside the repository, all three CLI help commands and `pip check` passed.
- Git-eligible file review found no files over 10 MiB (largest approximately 34 KiB), PDF/database/model artifacts or matches for the checked AWS/GitHub/OpenAI/private-key credential patterns. Pattern checks do not prove absence of every possible secret format.

## Critical fixes made

1. **Versioned ingestion context:** a nonempty but partial context could bypass requirements for the existing dataset/cleaning/chunking context. Ingestion now requires every persisted non-embedding context key before any targeted collection write. Regression assertions exercise the catalog-fingerprint/partial-context case and verify record counts remain intact.
2. **Pinned acquisition integrity:** newly acquired bytes were not checked against the existing catalog digest before updating its snapshot metadata. Downloaded PDFs now must match a known pinned SHA-256 before parsing/saving. A mocked changed response is rejected without saving a PDF or replacing the pinned digest; no real PDFs were downloaded during review.
3. **Fresh-checkout instructions:** the handoff assumed ignored raw/processed/model/DB assets already existed and used an unshipped local run path. README now gives an ordered bootstrap sequence: install, acquire only the five pinned PDFs, cache the model, generate baseline JSONL/DB, run the benchmark, then test. The handoff example uses the generated `phase26_reproduction` directory.
4. **Git exclusions:** common environment/credential/private-key files and generated SQLite/model/embedding files at custom output locations are now excluded. `git check-ignore` probes confirmed the exclusions and that handoff sources and `.env.example` remain eligible.

## HKMA 2019 status

The sidecar's `superseded` status is supported by the official 2026 HKMA guidance, physical page 1, Purpose section: it expressly identifies the 1 November 2019 principles as superseded. This was rechecked from the acquired official PDF with SHA-256 `2517b00fba23ed6e4c4372e5f84ad789f23df435cae7ee4d8d500872fc9cb109`, matching the recorded evidence checksum. The browsing service could not fetch the official URL during this review; this is verification of the pinned official document, not a claim of a successful live-status lookup. Other document statuses remain `unknown`.

Official evidence: [HKMA 2026 guidance](https://brdr.hkma.gov.hk/eng/doc-ldg/docId/getPdf/20261015-2-EN/20261015-2-EN.pdf). Full schema/evidence handling: [temporal metadata](temporal_metadata.md).

## Reproduce the test result

With the documented model cache prepared:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RAG_TEST_REAL_MODEL=1 .venv/bin/python -m pytest -q
```

A new checkout must first follow the [README bootstrap sequence](../README.md#first-team-checkout-reproduce-the-existing-five-document-pilot). Dependencies/PDF/model acquisition requires external network availability; a cold network installation and other OS/architectures were not rerun in this review. Cached-model execution and installed-package operation were verified locally.

The Phase 2.6 benchmark JSON/Markdown remain the historical measured run4 artifacts. This review changed validation guards and instructions, not those experimental records or timings. Their recorded code hashes describe the measurement version, not the subsequent integration-hardening changes.

## Remaining documented limitations

Fixed token windows can split sentences/words; tables/footnotes are flattened; quality detectors are conservative heuristics. Historical status must remain visible and unknown status must not be treated as current. Writes are not transactional across batches, and raw Chroma writes bypass package checks. No formal retrieval accuracy or answer correctness is claimed. These limits are documented and do not prevent the first engineering handoff.
