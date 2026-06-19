"""Token + cost accounting, aggregated across all model calls.

Every call routed through the LLM client reports its usage here so the
operational analysis (calls, tokens, $ cost, per-agent breakdown) is measured,
not guessed.
"""
from __future__ import annotations

import threading
from collections import defaultdict

from . import config


class UsageTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.calls = 0
        self.cached_calls = 0
        self.images = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.by_agent = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "images": 0})
        self.by_model = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0})

    def record(self, agent: str, model: str, in_tok: int, out_tok: int,
               images: int = 0, cached: bool = False):
        with self._lock:
            self.calls += 1
            if cached:
                self.cached_calls += 1
            self.images += images
            self.input_tokens += in_tok
            self.output_tokens += out_tok
            a = self.by_agent[agent]
            a["calls"] += 1; a["in"] += in_tok; a["out"] += out_tok; a["images"] += images
            m = self.by_model[model]
            m["calls"] += 1; m["in"] += in_tok; m["out"] += out_tok

    def cost_usd(self) -> float:
        total = 0.0
        for model, m in self.by_model.items():
            price = config.PRICING.get(model)
            if not price:
                continue
            total += m["in"] / 1_000_000 * price.input_per_mtok
            total += m["out"] / 1_000_000 * price.output_per_mtok
        return total

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "cached_calls": self.cached_calls,
            "live_calls": self.calls - self.cached_calls,
            "images": self.images,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "est_cost_usd": round(self.cost_usd(), 4),
            "by_agent": {k: dict(v) for k, v in self.by_agent.items()},
            "by_model": {k: dict(v) for k, v in self.by_model.items()},
        }
