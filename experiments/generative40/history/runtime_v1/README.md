# Original full40 execution fingerprints (v1)

These are byte-for-byte copies from PR head `a7f7084b657ccf341fabf333291e432ffb0b04e6`, made before the canonical-root authorization fix:

- `controller80.py.txt`: original controller source, stored as reference text, not a runnable entry point.
- `run_authorized_full40.py.txt`: original launcher source, also reference text.
- `runtime_manifest.json`: original frozen runtime manifest.
- `authorization.example.json`: original **unapproved** example and original launcher/manifest fingerprints. It is not real consent and must never be used to authorize execution.

The original manifest SHA-256 is `c23200a1ce27c442a21cbe676d10dc87bb230e54ef306bfa3ec057111b0601b5`, as recorded in `docs/experiments/generative40/freeze_provenance.json`. To audit its eleven file entries, use `controller80.py.txt` here for `controller80.py` and the unchanged files in `../../runtime/` for the other ten entries. The launcher text hash matches this archived example's launcher fingerprint. An offline regression test checks this mapping.

No historical scores, raw-result fingerprints, input evidence, prompts, or candidate retrieval locks were rewritten. The patched current runtime is version `canonical-root-bound-v2` in `../../runtime/`; its new manifest and current launcher require a separately supplied, root-bound approval. The historical manifest does not identify a run made by the patched controller. These files preserve provenance, not permission to rerun the old gate.
