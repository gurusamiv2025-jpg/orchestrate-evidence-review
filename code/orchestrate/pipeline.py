"""Batch runner: process a claims CSV with bounded concurrency and emit rows.

Concurrency is at the *claim* level (a thread pool of size max_workers). Within
a claim the agent calls run sequentially because they are data-dependent. This
keeps us well under TPM/RPM limits while still overlapping network latency. The
content-hash cache makes the whole run resumable: a crash + re-run only pays for
claims not already cached.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, orchestrator
from .cache import DiskCache
from .config import Strategy
from .io_utils import Claim
from .llm_client import LLMClient
from .usage import UsageTracker


def run_batch(claims: list[Claim], *, strategy: Strategy, requirements: list[dict],
              history_index: dict, dry_run: bool | None = None,
              max_workers: int | None = None, progress: bool = True):
    usage = UsageTracker()
    cache = DiskCache(config.RUNTIME.cache_dir)
    llm = LLMClient(usage=usage, cache=cache, dry_run=dry_run)
    workers = max_workers or config.RUNTIME.max_workers

    results: dict[int, dict] = {}
    errors: list[str] = []

    def _work(idx_claim):
        idx, claim = idx_claim
        try:
            row = orchestrator.process_claim(
                claim, llm=llm, strategy=strategy, requirements=requirements,
                history_index=history_index)
            return idx, row, None
        except Exception as e:  # never let one bad claim kill the batch
            return idx, _fallback_row(claim), f"row {idx}: {e!r}"

    mode = "DRY-RUN" if llm.dry_run else "LIVE"
    print(f"[pipeline] {mode} | strategy={strategy.name} | {len(claims)} claims "
          f"| {workers} workers")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_work, (i, c)) for i, c in enumerate(claims)]
        done = 0
        for fut in as_completed(futures):
            idx, row, err = fut.result()
            results[idx] = row
            if err:
                errors.append(err)
            done += 1
            if progress and (done % 5 == 0 or done == len(claims)):
                print(f"[pipeline] {done}/{len(claims)} "
                      f"(cache hits={cache.hits}, live calls={usage.calls - usage.cached_calls})")

    rows = [results[i] for i in range(len(claims))]
    for e in errors:
        print(f"[pipeline][warn] {e}")
    return rows, usage


def _fallback_row(claim: Claim) -> dict:
    """Schema-valid safe row if a claim errors out entirely."""
    return {
        "user_id": claim.user_id, "image_paths": claim.image_paths,
        "user_claim": claim.user_claim, "claim_object": claim.claim_object,
        "evidence_standard_met": False,
        "evidence_standard_met_reason": "processing error; defaulted",
        "risk_flags": "manual_review_required", "issue_type": "unknown",
        "object_part": "unknown", "claim_status": "not_enough_information",
        "claim_status_justification": "Could not process this claim automatically.",
        "supporting_image_ids": "none", "valid_image": False, "severity": "unknown",
    }
