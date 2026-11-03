"""Local environment configuration. No credentials in logs or result artifacts."""
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = "https://llm.cs.cityu.edu.hk/v1"
    model: str = "CS5351/DeepSeek-V4-Flash"
    timeout: float = 30
    max_tokens: int = 1200
    thinking: str = ""
    json_mode: bool = True
    top_k: int = 5
    collection: str = "fixed_150"
    arm: str = "enhanced"
    experiment_dir: Path = ROOT / "data/experiments/phase26_reproduction"
    cache_dir: Path = ROOT / ".cache/huggingface/hub"
    max_distance: float | None = None

    def __post_init__(self):
        url = urlsplit(self.base_url)
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (url.scheme != "https" and not (local and url.scheme == "http")) or not url.hostname:
            raise ValueError("LLM_BASE_URL must use HTTPS (HTTP allowed only on localhost)")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("LLM_BASE_URL must not contain credentials, query or fragment")
        if not self.model.strip() or not math.isfinite(self.timeout) or not 1 <= self.timeout <= 120:
            raise ValueError("Set a model and a finite timeout between 1 and 120 seconds")
        if not 128 <= self.max_tokens <= 4096 or not 1 <= self.top_k <= 10:
            raise ValueError("Output budget must be 128..4096 tokens; top_k must be 1..10")
        if self.thinking not in {"", "disabled", "enabled"}:
            raise ValueError("LLM_THINKING must be blank, disabled or enabled")
        if self.max_distance is not None and (not math.isfinite(self.max_distance) or not 0 <= self.max_distance <= 2):
            raise ValueError("RAG_MAX_DISTANCE must be a finite cosine distance in 0..2")

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)

        def path(name, default):
            value = Path(os.environ.get(name, default))
            return value if value.is_absolute() else ROOT / value

        cutoff = os.environ.get("RAG_MAX_DISTANCE", "").strip()
        json_mode = os.environ.get("LLM_JSON_MODE", "true").lower()
        if json_mode not in {"true", "false"}:
            raise ValueError("LLM_JSON_MODE must be true or false")
        return cls(
            api_key=os.environ.get("LLM_API_KEY", "").strip(),
            base_url=os.environ.get("LLM_BASE_URL", cls.base_url).rstrip("/"),
            model=os.environ.get("LLM_MODEL", cls.model),
            timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "30")),
            max_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "1200")),
            thinking=os.environ.get("LLM_THINKING", ""),
            json_mode=json_mode == "true",
            top_k=int(os.environ.get("RAG_TOP_K", "5")),
            collection=os.environ.get("RAG_COLLECTION", "fixed_150"),
            arm=os.environ.get("RAG_ARM", "enhanced"),
            experiment_dir=path("RAG_EXPERIMENT_DIR", "data/experiments/phase26_reproduction"),
            cache_dir=path("RAG_MODEL_CACHE", ".cache/huggingface/hub"),
            max_distance=float(cutoff) if cutoff else None,
        )
