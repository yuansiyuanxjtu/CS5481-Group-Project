"""B-to-C orchestration; retrieval, refusal and provider failures stay distinct."""
import time

from .config import Settings
from .grounding import REFUSAL, messages_for, prepare_evidence, validate_generation
from .llm import ChatClient, GenerationError, LLMError


class QAService:
    def __init__(self, retriever, llm, catalog: dict, settings: Settings):
        self.retriever, self.llm, self.catalog, self.settings = retriever, llm, catalog, settings

    def answer_question(self, question: str) -> dict:
        started = time.monotonic()
        output = {"status": "invalid_input", "answer": "", "citations": [], "claims": [],
                  "retrieved": [], "error": None, "model": None, "usage": {}}

        def finish():
            output["elapsed_seconds"] = round(time.monotonic() - started, 3)
            return output

        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            output["error"] = "Enter a nonempty English question (at most 2,000 characters)."
            return finish()
        cfg = self.settings
        try:
            hits = self.retriever.retrieve(question.strip(), cfg.top_k, collection=cfg.collection, arm=cfg.arm)
            output["retrieved"] = prepare_evidence(hits, self.catalog)
        except ValueError:
            output.update(status="retrieval_error", error="Retrieval rejected the query or evidence. Check the 256-token query limit and source metadata.")
            return finish()
        except Exception:
            output.update(status="retrieval_error", error="Retrieval is unavailable. Verify the experiment DB, pinned model cache and collection context.")
            return finish()
        evidence = output["retrieved"]
        if cfg.max_distance is not None:
            evidence = [hit for hit in evidence if hit["distance"] <= cfg.max_distance]
            # Re-number after filtering; IDs always refer to the actual supplied context.
            evidence = [{**hit, "evidence_id": i} for i, hit in enumerate(evidence, 1)]
        output["retrieved"] = evidence
        if not evidence:
            output.update(status="insufficient_evidence", answer=REFUSAL)
            return finish()
        try:
            generation = self.llm.generate(messages_for(question.strip(), evidence))
            output.update(model=generation.get("model", cfg.model), usage=generation.get("usage", {}))
            output.update(validate_generation(generation["content"], evidence))
        except GenerationError as exc:
            output.update(status="invalid_output", error=str(exc))
        except LLMError as exc:
            output.update(status="llm_error", error=str(exc))
        except Exception:
            output.update(status="llm_error", error="Unexpected generation failure. No answer was accepted.")
        return finish()


def create_service(settings=None):
    import hashlib
    import json
    from rag_ingest.temporal import load_temporal_catalog
    from rag_retrieval import Retriever
    cfg = settings or Settings.from_env()
    # Join the exact run snapshot, not a later mutable catalog.
    catalog_path = cfg.experiment_dir / "temporal_catalog.json"
    context = json.loads((cfg.experiment_dir / cfg.arm / "collection_context.json").read_text(encoding="utf-8"))
    if hashlib.sha256(catalog_path.read_bytes()).hexdigest() != context["temporal_catalog_sha256"]:
        raise ValueError("Temporal catalog differs from the experiment snapshot")
    catalog = load_temporal_catalog(catalog_path)
    return QAService(Retriever(cfg.experiment_dir, cfg.cache_dir), ChatClient(cfg), catalog, cfg)
