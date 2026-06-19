"""Anthropic client wrapper: structured output, caching, retries, usage, dry-run.

Design choices that matter for the judge:
  * Structured output via forced tool-use  -> the model must return JSON that
    matches a schema; no brittle free-text parsing.
  * temperature 0 + content-hash cache     -> deterministic & reproducible.
    (Newer models, e.g. Opus 4.8, DEPRECATE `temperature`; we auto-detect that
    and omit it for those models, learning per-model so we only pay the probe
    once.)
  * exponential backoff on 429/5xx/overload -> rate-limit resilient.
  * dry-run / mock provider                 -> the full pipeline runs and is
    testable with NO api key (returns schema-valid stubs), so plumbing, schema
    conformance and column order can be verified offline.
"""
from __future__ import annotations

import os
import random
import time

from . import config
from .cache import DiskCache
from .usage import UsageTracker


class LLMClient:
    def __init__(self, usage: UsageTracker, cache: DiskCache | None = None,
                 dry_run: bool | None = None):
        self.usage = usage
        self.cache = cache or DiskCache(config.RUNTIME.cache_dir)
        # dry-run if explicitly requested OR no api key present
        self.dry_run = dry_run if dry_run is not None else not os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        # models that reject the `temperature` param (learned at runtime)
        self._no_temp_models: set[str] = set()
        if not self.dry_run:
            try:
                import anthropic  # lazy import
                self._client = anthropic.Anthropic(timeout=config.RUNTIME.request_timeout_s)
            except Exception as e:  # pragma: no cover
                raise RuntimeError(
                    "anthropic SDK not available / failed to init. "
                    "pip install -r requirements.txt, or run with --dry-run."
                ) from e

    # ------------------------------------------------------------------
    def call_structured(self, *, agent: str, model: str, system: str,
                        content_blocks: list, tool_name: str, tool_schema: dict,
                        mock_default: dict, n_images: int = 0,
                        max_tokens: int | None = None) -> dict:
        """Make one structured call. Returns the tool-input dict (validated JSON)."""
        tool = {
            "name": tool_name,
            "description": f"Return the structured result for the {agent} step.",
            "input_schema": tool_schema,
        }
        messages = [{"role": "user", "content": content_blocks}]
        cache_payload = {
            "model": model, "system": system, "messages": _ser(messages),
            "tool": tool, "temp": config.RUNTIME.temperature,
        }
        key = DiskCache.make_key(cache_payload)
        cached = self.cache.get(key)
        if cached is not None:
            self.usage.record(agent, model, cached.get("_in", 0), cached.get("_out", 0),
                              images=0, cached=True)
            return {k: v for k, v in cached.items() if not k.startswith("_")}

        if self.dry_run:
            result = dict(mock_default)
            # tiny token estimate so dry-run usage numbers are non-zero/plausible
            in_tok = _estimate_tokens(system, messages) + n_images * 1300
            out_tok = _estimate_tokens("", [{"content": str(result)}])
            self.usage.record(agent, model, in_tok, out_tok, images=n_images, cached=False)
            self.cache.set(key, {**result, "_in": in_tok, "_out": out_tok})
            return result

        result, in_tok, out_tok = self._call_with_retries(
            model=model, system=system, messages=messages, tool=tool,
            tool_name=tool_name, max_tokens=max_tokens or config.RUNTIME.max_tokens,
        )
        self.usage.record(agent, model, in_tok, out_tok, images=n_images, cached=False)
        if result is None:
            # do NOT cache failures — let a subsequent run retry them
            return dict(mock_default)  # safe fallback keeps this batch alive
        self.cache.set(key, {**result, "_in": in_tok, "_out": out_tok})
        return result

    # ------------------------------------------------------------------
    def _call_with_retries(self, *, model, system, messages, tool, tool_name,
                          max_tokens):
        import anthropic
        last_err = None
        # send temperature unless it's None or this model is known to reject it
        send_temperature = (config.RUNTIME.temperature is not None
                            and model not in self._no_temp_models)
        for attempt in range(config.RUNTIME.max_retries):
            try:
                kwargs = dict(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool_name},
                    messages=messages,
                )
                if send_temperature:
                    kwargs["temperature"] = config.RUNTIME.temperature
                resp = self._client.messages.create(**kwargs)
                tool_input = None
                for block in resp.content:
                    if getattr(block, "type", None) == "tool_use":
                        tool_input = block.input
                        break
                in_tok = resp.usage.input_tokens
                out_tok = resp.usage.output_tokens
                return tool_input, in_tok, out_tok
            except Exception as e:  # broad: covers RateLimit, APIStatus, overload
                last_err = e
                msg = str(e).lower()
                # Newer models deprecate `temperature`: drop it and retry now.
                if send_temperature and "temperature" in msg:
                    self._no_temp_models.add(model)
                    send_temperature = False
                    continue
                status = getattr(e, "status_code", None)
                retryable = (
                    isinstance(e, getattr(anthropic, "RateLimitError", ())) or
                    isinstance(e, getattr(anthropic, "APIStatusError", ())) or
                    isinstance(e, getattr(anthropic, "APIConnectionError", ())) or
                    (status in (408, 409, 429, 500, 502, 503, 529))
                )
                if not retryable or attempt == config.RUNTIME.max_retries - 1:
                    break
                sleep = config.RUNTIME.base_backoff_s * (2 ** attempt)
                sleep += random.uniform(0, sleep * 0.25)  # jitter
                time.sleep(sleep)
        print(f"[llm] giving up after retries: {last_err}")
        return None, 0, 0


def _ser(messages):
    """Stable serialization for cache key — drop raw image bytes, hash them."""
    import hashlib
    out = []
    for m in messages:
        blocks = []
        for b in (m["content"] if isinstance(m["content"], list) else [m["content"]]):
            if isinstance(b, dict) and b.get("type") == "image":
                data = b["source"]["data"]
                blocks.append({"type": "image",
                               "sha": hashlib.sha256(data.encode()).hexdigest()})
            else:
                blocks.append(b)
        out.append({"role": m["role"], "content": blocks})
    return out


def _estimate_tokens(system: str, messages: list) -> int:
    """Rough char/4 token estimate, for dry-run accounting only."""
    chars = len(system or "")
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    chars += len(b.get("text", "")) if b.get("type") == "text" else 0
                else:
                    chars += len(str(b))
        else:
            chars += len(str(c))
    return max(1, chars // 4)
