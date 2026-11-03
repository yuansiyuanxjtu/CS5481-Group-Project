# Temporal and citation metadata

The original CSV stays `document_id,source_file,source_url`; the original eight-field Chunk JSONL stays unchanged. `data/catalog/temporal_metadata.json` is a separate validated catalog, loaded with `rag_ingest.temporal.load_temporal_catalog(path)`.

Required document fields:

| Field | Meaning |
| --- | --- |
| document_id | Stable manifest join key |
| title | Verified publication title |
| issuing_organization | Official publisher |
| publication_date | Verified ISO date, not an inferred status |
| jurisdiction | Hong Kong or International for this pilot; International is not a claim of binding law |
| original_source_url | Official landing page |
| source_pdf_url | Direct official PDF, matched to chunk source_url |
| document_checksum | SHA-256 of the acquired raw PDF bytes |
| regulatory_status | `unknown`, `current`, `superseded`, `withdrawn`, or `non_binding` |
| status_verified_at | ISO date for an evidence-backed status; null for unknown |

Known status requires `status_evidence` with an official issuer-hosted URL and locator. Optional evidence-document checksum/ID and `superseded_by` are retained in the sidecar. Schema validation verifies structure and issuer-host consistency; it does not independently establish the truth of a status assertion. Human verification against official evidence is required. Publication dates alone never determine status.

For this snapshot, only `hkma_20191101_ai_principles` is marked `superseded`. The evidence is the official [2026 guidance](https://brdr.hkma.gov.hk/eng/doc-ldg/docId/getPdf/20261015-2-EN/20261015-2-EN.pdf), physical page 1, Purpose section, which explicitly identifies the 2019 principles as superseded. Its locally acquired checksum is recorded with the evidence. This text was reviewed on 3 November 2026. The newer guidance and both FSB reports and BIS paper are marked `unknown` for regulatory status: no claim that they are current or binding is inferred from their dates. Their document types remain described in the pilot catalog.

The benchmark verifies all five raw-file checksums against this catalog before processing. It embeds all ten fields into experiment Chroma record metadata, alongside source_file, source_url, physical page_number, chunk_strategy and token_count. Chroma requires scalar values: unknown `status_verified_at` is stored as the empty string, while the sidecar uses JSON null. Full nested evidence remains in the sidecar. Member C should cite the actual document, page and date, and disclose historical status where relevant.

`ingest_jsonl(..., document_metadata=catalog, context=...)` is an optional extension to the existing API. `rag-store --catalog data/catalog/temporal_metadata.json --dataset-version <version>` exposes it on the CLI. The benchmark supplies stronger snapshot/cleaning/chunking context automatically. Collections fingerprint temporal metadata and reject a changed catalog or omitted required context on subsequent ingestion. The original pilot collections remain unchanged and do not gain metadata retroactively.

For the existing baseline DB, Members B/C can join the catalog by document_id. For experiment collections, read metadata directly and join the sidecar for evidence. `unknown` must not be treated as current. Status is a point-in-time verified assertion, not continuous monitoring, and no legal-applicability filter or retrieval algorithm is implemented here.
