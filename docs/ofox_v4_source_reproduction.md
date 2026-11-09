# Reviewed V4 source and offline reproduction

V4 is a separate, operator-bound EXP11 acceptance controller. It uses the existing `joint_pairs8` retriever, frozen planner/generation runtime, QA service and citation validator. The source preserves Azure Foundry routing, JSON-object output, low reasoning effort, a 1,200-token completion limit, zero retries, empty fallback and at most two durable dispatch reservations. Generation requires an accepted fresh plan from the same session. Completion and failure stop the session. Publishing this source does not activate it or grant another paid execution.

## Source scope and behavior

The integration adds `ofox_probe.py`, `ofox_azure_probe.py` and `ofox_v4.py`, with their synthetic regression tests. The V2/V3 modules remain required incident-chain dependencies of the reviewed V4 code; their historical entry points should not be executed. Shared changes in `demo_budget.py` persist and check controller/count policy. `ofox_demo.py` supplies controller-bound routing, pre-dispatch request checks, validated response preservation and decoded credential-echo screening.

The executable fingerprint is `f9f63ee38c54066a9f946c8016ab1a7451dde03bbfffb38107d770dca72d0f63`. Source bytes match the implementation used for the earlier approved V4 acceptance. No historical prompt, experiment input, score, corpus or default application profile changes. Existing stopped registries are not migrated, reset or bundled. Registries created under older source/schema bindings intentionally fail closed rather than becoming reusable.

`app.py` still uses the original demo-service routing. Its ordinary Ofox profile selects the legacy service, not V4. V4 does not add a Streamlit playback loader or become the default product path. A machine without the original private incident state cannot execute this operator-bound controller; do not fabricate that state or remove its checks to make a classroom demo run.

## Dependencies and offline assets

Use Python 3.11+ and the pinned environment instructions in the root README, `requirements-phase2-lock.txt`, `requirements-app-lock.txt` and the application overrides. Integration validation reused Python 3.11.15, PyMuPDF 1.26.6, ChromaDB 1.3.5, sentence-transformers 5.1.2, transformers 4.57.1, Streamlit 1.66.0, httpx 0.28.1 and pytest 8.4.2. This is not a new clean-machine dependency-installation certification.

Prepare the exact `sentence-transformers/all-MiniLM-L6-v2` assets at revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf` once, using the README's explicit preparation procedure when downloads are authorized. Tests use the pinned tokenizer and some real-model checks; missing cache assets should fail rather than cause an online fallback. Model weights, virtual environments and caches are excluded from this PR.

For corpus reproduction, the existing five-file manifest/catalog identifies two HKMA documents, two FSB reports and one BIS/FSI report, totaling 165 physical PDF pages. Independently acquire those exact checksum-matched PDFs only when authorized, then run the documented ingestion/benchmark workflow into new isolated directories. Never alter expected hashes to accept a different file. Source QA labels and frozen metadata remain in the repository, while raw PDFs, generated corpora and Chroma databases stay outside Git. Windows dependency notes remain applicable; the old JSONL newline failure is historical because current benchmark code explicitly writes LF JSONL.

## Offline tests without provider access

All authorization tests use temporary synthetic stores and synthetic keys. No real `.env`, private approval or stopped registry is needed. The following example starts pytest in a minimal environment with dotenv/model downloads disabled, denies DNS/socket activity and blocks real authorization-registry connections/writes. It creates the audit bootstrap in a temporary directory outside the source tree, so it does not change the executable fingerprint. Run it with the already prepared `.venv/bin/python` from the repository root.

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import os, subprocess, sys, tempfile

root = Path.cwd()
with tempfile.TemporaryDirectory(prefix="cs5481-offline-tests-") as temporary:
    guard = Path(temporary)
    (guard / "sitecustomize.py").write_text('''import os, sys
from pathlib import Path
state = str(Path.home() / ".local/state/cs5481")
project = Path.cwd()
def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("Offline tests deny network")
    if event == "sqlite3.connect" and state in str(args[0]):
        raise RuntimeError("Real authorization registries are unavailable in tests")
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = os.fsdecode(args[0])
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writing = ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                   or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if state in name and writing:
            raise RuntimeError("Real registry writes denied")
        if Path(name).absolute() == project / ".env":
            raise RuntimeError("Real project credentials denied")
sys.addaudithook(audit)
''', encoding="utf-8")
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL") if k in os.environ}
    env.update(
        PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        ANONYMIZED_TELEMETRY="False", RAG_TEST_REAL_MODEL="1",
        PYTHONHASHSEED="0", TOKENIZERS_PARALLELISM="false",
        OMP_NUM_THREADS="4", MKL_NUM_THREADS="4",
        PYTHONPATH=os.pathsep.join(map(str, [guard, root / "src", root / "experiments/retrieval_candidates"])),
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests", "experiments"],
        cwd=root, env=env,
    )
    raise SystemExit(result.returncode)
PY
```

The integration candidate passed 176 focused safeguards, 331 tests across `tests experiments`, one real-index acceptance with two mocked HTTP responses, and 130 tests from a fresh extraction of the complete Canvas source archive. These checks overlap; their counts should not be added as distinct coverage. The archive validation reused prepared dependencies/cache. Initial environment installation, current official download availability, cross-platform behavior and native classroom presentation software remain unverified by those checks. Test deprecation warnings were retained in the private validation evidence.

## Recorded single-case acceptance evidence

A previously authorized real EXP11 acceptance used `openai/gpt-6-luna` with the configured `azure_foundry` route. Planning and generation each returned HTTP 200, with two dispatches, no retries or fallback, 10,702 reported tokens and 5.238 seconds of application latency after initialization. The generated answer identified possible changes in market structure, macroeconomic conditions and energy use, preserving the qualification about implications under certain circumstances. Its exact quotation matched the FSB 2024 report at [physical PDF page 6](https://www.fsb.org/uploads/P14112024.pdf#page=6), printed page 2. The session stopped after completion.

This single integration acceptance is separate from the historical 40-question DeepSeek development regression. It does not establish a GPT-6 Luna benchmark accuracy, general reliability, mean latency or the provider's internal backend identity. Automated quotation/provenance checks and AI-assisted source comparison passed; independent group-member human review remains pending. Actual billing was not queried, and the accepted USD 0.50 tolerance was not a guaranteed cap.

The recorded classroom demonstration and draft academic deliverables remain separate Canvas review materials. They are excluded from this source PR while B/C review and real signatures are pending. The complete source ZIP is also a separate Canvas artifact, not a repository binary. Keep real keys, authorization JSON, registries, original provider logs, billing records, caches and personal signatures private. No new session, authorization or provider request is part of publication or offline reproduction.
