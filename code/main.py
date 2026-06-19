#!/usr/bin/env python3
"""Entry point: run the evidence-review system over a claims CSV -> output.csv.

Usage:
    python code/main.py                      # run on dataset/claims.csv -> output.csv
    python code/main.py --dry-run            # no API key needed; schema-valid stubs
    python code/main.py --strategy orchestrated_sonnet
    python code/main.py --input dataset/sample_claims.csv --output sample_out.csv
    python code/main.py --limit 5            # first N claims (debugging)

Reads ANTHROPIC_API_KEY from the environment / .env. If absent, runs in dry-run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# allow `python code/main.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv()
except Exception:
    pass

from orchestrate import config, io_utils
from orchestrate.pipeline import run_batch


def main(argv=None):
    p = argparse.ArgumentParser(description="Multi-modal evidence review")
    p.add_argument("--input", default=str(config.DATASET_DIR / "claims.csv"))
    p.add_argument("--output", default=str(config.REPO_ROOT / "output.csv"))
    p.add_argument("--images-root", default=str(config.DATASET_DIR))
    p.add_argument("--strategy", default=config.DEFAULT_STRATEGY,
                   choices=list(config.STRATEGIES))
    p.add_argument("--dry-run", action="store_true",
                   help="run without an API key (schema-valid stubs)")
    p.add_argument("--max-workers", type=int, default=None)
    p.add_argument("--limit", type=int, default=None,
                   help="process only the first N claims")
    p.add_argument("--usage-out", default=None,
                   help="where to write usage.json (default: alongside output)")
    args = p.parse_args(argv)

    strategy = config.STRATEGIES[args.strategy]
    images_root = Path(args.images_root)

    claims = io_utils.read_claims(Path(args.input), images_root)
    if args.limit:
        claims = claims[:args.limit]
    history = io_utils.read_user_history(config.DATASET_DIR / "user_history.csv")
    requirements = io_utils.read_evidence_requirements(
        config.DATASET_DIR / "evidence_requirements.csv")

    t0 = time.time()
    rows, usage = run_batch(
        claims, strategy=strategy, requirements=requirements,
        history_index=history, dry_run=True if args.dry_run else None,
        max_workers=args.max_workers)
    elapsed = time.time() - t0

    out_path = Path(args.output)
    io_utils.write_output(rows, out_path)

    usage_path = Path(args.usage_out) if args.usage_out else out_path.with_name(
        out_path.stem + "_usage.json")
    summary = usage.summary()
    summary["elapsed_seconds"] = round(elapsed, 1)
    summary["claims"] = len(claims)
    summary["strategy"] = strategy.name
    Path(usage_path).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n[done] wrote {len(rows)} rows -> {out_path}")
    print(f"[usage] calls={summary['calls']} live={summary['live_calls']} "
          f"cached={summary['cached_calls']} images={summary['images']} "
          f"in_tok={summary['input_tokens']} out_tok={summary['output_tokens']} "
          f"est_cost=${summary['est_cost_usd']} time={summary['elapsed_seconds']}s")
    print(f"[usage] detail -> {usage_path}")


if __name__ == "__main__":
    main()
