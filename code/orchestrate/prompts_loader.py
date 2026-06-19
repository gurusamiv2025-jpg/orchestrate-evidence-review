"""Load prompt templates from prompts/ so prompts are versioned config, not
buried in code."""
from __future__ import annotations

from functools import lru_cache

from . import config


@lru_cache(maxsize=None)
def load(name: str) -> str:
    path = config.PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()
