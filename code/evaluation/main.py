#!/usr/bin/env python3
"""Evaluation entry point.

Runs one or more strategies on the LABELED sample set, scores predictions
against the gold labels, compares strategies, and writes:
  * evaluation/results.json            (full metrics + per-row breakdown)
  * evaluation/metrics_table.md        (auto-generated comparison table)
  * evaluation/sample_predictions_<strategy>.csv

Usage:
    python code/evaluation/main.py                       # default 2-strategy compare
    python code/evaluation/main.py --dry-run             # offline plumbing check
    python code/evaluation/main.py --strategies orchestrated_opus monolithic_opus
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    load_dotenv()
except Exception:
    pass

from orchestrate import config, io_utils
from orchestrate.pipeline import run_batch
from evaluation import metrics

EVAL_DIR = Path(__file__).resolve().parent


def main(argv=None):
    p = argparse.ArgumentParser(description="Evaluate strategies on the sample set")
    p.add_argument("--strategies", nargs="+",
                   default=["orchestrated_opus", "orchestrated_sonnet"],
                   choices=list(config.STRATEGIES))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-workers", type=int, default=None)
    args = p.parse_args(argv)

    sample = io_utils.read_claims(
        config.DATASET_DIR / "sample_claims.csv", config.DATASET_DIR)
    if args.limit:
        sample = sample[:args.limit]
    golds = [c.expected for c in sample]
    if any(g is None for g in golds):
        print("[eval][warn] some sample rows have no gold labels; scoring available rows only")

    history = io_utils.read_user_history(config.DATASET_DIR / "user_history.csv")
    requirements = io_utils.read_evidence_requirements(
        config.DATASET_DIR / "evidence_requirements.csv")

    results_by_strategy, usage_by_strategy = {}, {}
    for sname in args.strategies:
        strategy = config.STRATEGIES[sname]
        print(f"\n===== strategy: {sname} =====")
        rows, usage = run_batch(
            sample, strategy=strategy, requirements=requirements,
            history_index=history, dry_run=True if args.dry_run else None,
            max_workers=args.max_workers, progress=True)
        io_utils.write_output(rows, EVAL_DIR / f"sample_predictions_{sname}.csv")
        res = metrics.evaluate(rows, golds)
        results_by_strategy[sname] = res
        usage_by_strategy[sname] = usage.summary()
        print(f"  weighted={res['weighted_score']:.3f} "
              f"claim_status_acc={res['field_accuracy']['claim_status']:.3f} "
              f"macroF1={res['claim_status_macro_f1']:.3f} "
              f"risk_f1={res['risk_flags_set_f1']:.3f} "
              f"cost=${usage_by_strategy[sname]['est_cost_usd']:.4f}")
        print("  confusion (gold->pred):")
        for g, d in res["claim_status_confusion"].items():
            print(f"    {g}: {dict(d)}")

    # write artifacts
    (EVAL_DIR / "results.json").write_text(
        json.dumps({"results": results_by_strategy, "usage": usage_by_strategy},
                   indent=2), encoding="utf-8")
    table = metrics.format_report(results_by_strategy, usage_by_strategy)
    (EVAL_DIR / "metrics_table.md").write_text(table, encoding="utf-8")
    print(f"\n[eval] wrote results.json + metrics_table.md to {EVAL_DIR}")
    print("\n" + table)


if __name__ == "__main__":
    main()
