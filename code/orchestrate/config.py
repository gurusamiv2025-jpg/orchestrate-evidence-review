"""Central configuration: model IDs, pricing, paths, thresholds, knobs.

Everything tunable lives here so the operational story (cost / latency / rate
limits) is auditable in one place. Values are overridable via environment
variables so nothing is hardcoded into application logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# code/  ->  repo root is one level up
CODE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CODE_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
PROMPTS_DIR = CODE_DIR / "prompts"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
# Default IDs; override per-account via env. Each agent is assigned a tier so we
# can trade cost vs accuracy without touching agent code.
MODEL_OPUS = os.environ.get("ANTHROPIC_MODEL_OPUS", "claude-opus-4-8")
MODEL_SONNET = os.environ.get("ANTHROPIC_MODEL_SONNET", "claude-sonnet-4-6")
MODEL_HAIKU = os.environ.get("ANTHROPIC_MODEL_HAIKU", "claude-haiku-4-5-20251001")


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens."""
    input_per_mtok: float
    output_per_mtok: float


# Pricing (USD / 1M tokens), verified June 2026 against published rates.
# Batch API is ~50% cheaper; prompt caching cuts cached-input ~90%. Update here
# when pricing changes — nothing else in the code hardcodes prices.
PRICING: dict[str, ModelPrice] = {
    MODEL_OPUS: ModelPrice(5.0, 25.0),     # Claude Opus 4.8 (standard mode)
    MODEL_SONNET: ModelPrice(3.0, 15.0),   # Claude Sonnet 4.6
    MODEL_HAIKU: ModelPrice(1.0, 5.0),     # Claude Haiku 4.5
}


# ---------------------------------------------------------------------------
# Per-agent model assignment (a "strategy"). Swappable for A/B comparison.
# ---------------------------------------------------------------------------
@dataclass
class Strategy:
    name: str
    claim_understanding_model: str
    image_triage_model: str
    damage_inspection_model: str
    adjudicator_model: str
    # If True, a single vision call does everything (monolithic baseline).
    monolithic: bool = False
    monolithic_model: str = MODEL_OPUS


# Primary strategy: Opus on the hard visual + final-judgment calls, cheaper
# models on text understanding / quality triage.
STRATEGY_ORCHESTRATED_OPUS = Strategy(
    name="orchestrated_opus",
    claim_understanding_model=MODEL_HAIKU,
    image_triage_model=MODEL_SONNET,
    damage_inspection_model=MODEL_OPUS,
    adjudicator_model=MODEL_OPUS,
)

# Cheaper orchestrated variant for the cost/accuracy comparison.
STRATEGY_ORCHESTRATED_SONNET = Strategy(
    name="orchestrated_sonnet",
    claim_understanding_model=MODEL_HAIKU,
    image_triage_model=MODEL_HAIKU,
    damage_inspection_model=MODEL_SONNET,
    adjudicator_model=MODEL_SONNET,
)

# Monolithic single-prompt baseline (one Opus vision call per claim).
STRATEGY_MONOLITHIC_OPUS = Strategy(
    name="monolithic_opus",
    claim_understanding_model=MODEL_OPUS,
    image_triage_model=MODEL_OPUS,
    damage_inspection_model=MODEL_OPUS,
    adjudicator_model=MODEL_OPUS,
    monolithic=True,
    monolithic_model=MODEL_OPUS,
)

STRATEGIES = {
    s.name: s
    for s in (
        STRATEGY_ORCHESTRATED_OPUS,
        STRATEGY_ORCHESTRATED_SONNET,
        STRATEGY_MONOLITHIC_OPUS,
    )
}
DEFAULT_STRATEGY = "orchestrated_opus"


# ---------------------------------------------------------------------------
# Runtime knobs
# ---------------------------------------------------------------------------
@dataclass
class RuntimeConfig:
    max_workers: int = int(os.environ.get("ORCH_MAX_WORKERS", "4"))
    max_image_edge: int = int(os.environ.get("ORCH_MAX_IMAGE_EDGE", "1280"))
    jpeg_quality: int = int(os.environ.get("ORCH_JPEG_QUALITY", "80"))
    cache_dir: Path = field(
        default_factory=lambda: CODE_DIR / os.environ.get("ORCH_CACHE_DIR", ".orch_cache")
    )
    max_retries: int = 5
    base_backoff_s: float = 2.0
    request_timeout_s: float = 120.0
    temperature: float = 0.0  # determinism
    max_tokens: int = 1500


RUNTIME = RuntimeConfig()
