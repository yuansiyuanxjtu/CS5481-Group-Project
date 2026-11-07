"""Opt-in Streamlit integration of the reviewed joint_pairs8 workflow."""
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
import sys

from rag_ingest.temporal import load_temporal_catalog

from . import service
from .llm import ChatClient

ROOT = Path(__file__).resolve().parents[2]
JOINT = ROOT / "experiments/joint_pairs8"
RUNTIME = ROOT / "experiments/generative40/runtime"
METHOD = RUNTIME / "method"


def _load_experiment():
    for folder in (JOINT, METHOD):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    modules = {}
    for name, folder in (("candidate_entry", JOINT), ("planned_generation", METHOD),
                         ("selection_adapter", METHOD), ("coverage_contract", METHOD)):
        module = import_module(name)
        if Path(module.__file__).resolve().parent != folder:
            raise ValueError(f"Unexpected source for the demo module {name}")
        modules[name] = module
    return modules["candidate_entry"], modules["planned_generation"]


class TwoStageDemoClient:
    def __init__(self, chat, planner):
        self.chat = chat
        self.planner = planner

    def generate(self, messages):
        usage = Counter()

        def record(event):
            if event["event"] in {"selection_raw_response", "generation_raw_response"}:
                reported = event["generation"].get("usage")
                if not isinstance(reported, dict):
                    return
                for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                            "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                    value = reported.get(key)
                    if type(value) is int and value >= 0:
                        usage[key] += value

        # The experiment client tracks question IDs and call counts. Keep that
        # state local to one submission, even when Streamlit caches this service.
        client = self.planner(self.chat, self.chat, record)
        result = client.generate(messages)
        return {**result, "usage": dict(usage)}


def create_demo_service(settings, profile, *, transport=None):
    if profile == "baseline":
        return service.create_service(settings)
    if profile != "joint_pairs8":
        raise ValueError("Set RAG_DEMO_PROFILE to baseline or joint_pairs8")

    protocol = json.loads((JOINT / "generation_protocol.json").read_bytes())
    if (settings.base_url, settings.model) != (protocol["provider"], protocol["requested_model"]):
        raise ValueError("The joint_pairs8 profile requires the reviewed DeepSeek endpoint and model")
    manifest = json.loads((RUNTIME / "runtime_manifest.json").read_bytes())
    for item in manifest["files"]:
        name = item["path"]
        if name.startswith("method/") or name == "generation_prompt.txt":
            if sha256((RUNTIME / name).read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError(f"Frozen generation file differs: {name}")
    if sha256((RUNTIME / "generation_prompt.txt").read_bytes()).hexdigest() != protocol["prompt_sha256"]:
        raise ValueError("Generation prompt differs from the reviewed joint_pairs8 protocol")

    cfg = replace(settings, timeout=protocol["timeout_seconds"], max_tokens=protocol["max_output_tokens"],
                  json_mode=protocol["json_mode"], thinking=protocol["thinking"],
                  top_k=8, collection="fixed_150_overlap_30", arm="enhanced", max_distance=None)
    catalog_path = cfg.experiment_dir / "temporal_catalog.json"
    catalog_bytes = catalog_path.read_bytes()
    context_path = cfg.experiment_dir / cfg.arm / "collection_context.json"
    context = json.loads(context_path.read_bytes())
    if sha256(catalog_bytes).hexdigest() != context["temporal_catalog_sha256"]:
        raise ValueError("Temporal catalog differs from the index snapshot")
    if sha256(catalog_bytes.replace(b"\r\n", b"\n")).hexdigest() != protocol["temporal_catalog_sha256_lf"]:
        raise ValueError("Temporal catalog differs from the reviewed joint_pairs8 protocol")
    candidate, planned = _load_experiment()
    retriever = candidate.JointCandidateRetriever(cfg.experiment_dir, cfg.cache_dir)
    client = TwoStageDemoClient(ChatClient(cfg, transport=transport), planned.PlannedGenerationClient)
    return service.QAService(retriever, client, load_temporal_catalog(catalog_path), cfg)
