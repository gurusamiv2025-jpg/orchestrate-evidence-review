"""Scoring for the sample set: per-field accuracy, claim_status macro-F1 +
confusion matrix, risk-flag set F1, and a documented weighted overall score.

Justification fields are free text and are not auto-scored (they are reviewed
qualitatively). The weighted score weights the decision (`claim_status`) most,
since that is the headline output, then evidence/risk, then the descriptive
fields.
"""
from __future__ import annotations

from collections import defaultdict

# Fields compared (categorical). Justifications excluded.
ACC_FIELDS = ["evidence_standard_met", "issue_type", "object_part",
              "claim_status", "valid_image", "severity"]

WEIGHTS = {
    "claim_status": 0.40,
    "evidence_standard_met": 0.15,
    "risk_flags_f1": 0.15,
    "issue_type": 0.10,
    "object_part": 0.10,
    "severity": 0.05,
    "valid_image": 0.05,
}


def _norm(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip().lower()


def _flag_set(v) -> set[str]:
    s = {f.strip().lower() for f in str(v).split(";") if f.strip()}
    s.discard("none")
    return s


def evaluate(preds: list[dict], golds: list[dict]) -> dict:
    assert len(preds) == len(golds), "pred/gold length mismatch"
    n = len(preds)

    field_correct = defaultdict(int)
    # claim_status confusion + per-class PRF
    classes = ["supported", "contradicted", "not_enough_information"]
    confusion = {g: defaultdict(int) for g in classes}

    # risk-flag set F1 (sample-averaged) + micro counts
    rf_f1_sum = 0.0
    micro_tp = micro_fp = micro_fn = 0
    rf_exact = 0

    per_row = []
    for p, g in zip(preds, golds):
        row_info = {"user_id": p.get("user_id")}
        for f in ACC_FIELDS:
            ok = _norm(p.get(f)) == _norm(g.get(f))
            field_correct[f] += int(ok)
            row_info[f] = ok
        # confusion
        gp = _norm(g.get("claim_status"))
        pp = _norm(p.get("claim_status"))
        if gp in confusion:
            confusion[gp][pp] += 1
        # risk flags
        ps, gs = _flag_set(p.get("risk_flags")), _flag_set(g.get("risk_flags"))
        tp = len(ps & gs); fp = len(ps - gs); fn = len(gs - ps)
        micro_tp += tp; micro_fp += fp; micro_fn += fn
        if ps == gs:
            rf_exact += 1
        prec = tp / (tp + fp) if (tp + fp) else (1.0 if not gs else 0.0)
        rec = tp / (tp + fn) if (tp + fn) else (1.0 if not ps else 0.0)
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else (1.0 if not gs and not ps else 0.0)
        rf_f1_sum += f1
        row_info["risk_f1"] = round(f1, 3)
        per_row.append(row_info)

    field_acc = {f: field_correct[f] / n for f in ACC_FIELDS}
    rf_f1 = rf_f1_sum / n

    # macro-F1 for claim_status
    macro = []
    for c in classes:
        tp = confusion[c][c]
        fp = sum(confusion[o][c] for o in classes if o != c)
        fn = sum(confusion[c][o] for o in classes if o != c)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        macro.append(f1)
    macro_f1 = sum(macro) / len(macro)

    weighted = (
        WEIGHTS["claim_status"] * field_acc["claim_status"]
        + WEIGHTS["evidence_standard_met"] * field_acc["evidence_standard_met"]
        + WEIGHTS["risk_flags_f1"] * rf_f1
        + WEIGHTS["issue_type"] * field_acc["issue_type"]
        + WEIGHTS["object_part"] * field_acc["object_part"]
        + WEIGHTS["severity"] * field_acc["severity"]
        + WEIGHTS["valid_image"] * field_acc["valid_image"]
    )

    return {
        "n": n,
        "field_accuracy": field_acc,
        "claim_status_macro_f1": macro_f1,
        "claim_status_confusion": {g: dict(d) for g, d in confusion.items()},
        "risk_flags_set_f1": rf_f1,
        "risk_flags_micro": {"tp": micro_tp, "fp": micro_fp, "fn": micro_fn},
        "risk_flags_exact_match": rf_exact / n,
        "weighted_score": weighted,
        "per_row": per_row,
    }


def format_report(results_by_strategy: dict, usage_by_strategy: dict) -> str:
    """Render a markdown comparison table over strategies."""
    lines = ["## Sample-set metrics (auto-generated)\n"]
    lines.append("| metric | " + " | ".join(results_by_strategy) + " |")
    lines.append("|" + "---|" * (len(results_by_strategy) + 1))

    def row(label, fn):
        return "| " + label + " | " + " | ".join(
            fn(results_by_strategy[s]) for s in results_by_strategy) + " |"

    lines.append(row("weighted score", lambda r: f"{r['weighted_score']:.3f}"))
    lines.append(row("claim_status acc", lambda r: f"{r['field_accuracy']['claim_status']:.3f}"))
    lines.append(row("claim_status macro-F1", lambda r: f"{r['claim_status_macro_f1']:.3f}"))
    lines.append(row("evidence_standard acc", lambda r: f"{r['field_accuracy']['evidence_standard_met']:.3f}"))
    lines.append(row("risk_flags set-F1", lambda r: f"{r['risk_flags_set_f1']:.3f}"))
    lines.append(row("issue_type acc", lambda r: f"{r['field_accuracy']['issue_type']:.3f}"))
    lines.append(row("object_part acc", lambda r: f"{r['field_accuracy']['object_part']:.3f}"))
    lines.append(row("severity acc", lambda r: f"{r['field_accuracy']['severity']:.3f}"))
    lines.append(row("valid_image acc", lambda r: f"{r['field_accuracy']['valid_image']:.3f}"))

    if usage_by_strategy:
        lines.append(row("est. cost (sample)",
                         lambda r: ""))  # placeholder row label
        lines[-1] = "| est. cost (sample) | " + " | ".join(
            f"${usage_by_strategy.get(s, {}).get('est_cost_usd', 0):.4f}"
            for s in results_by_strategy) + " |"
        lines.append("| live model calls | " + " | ".join(
            str(usage_by_strategy.get(s, {}).get('live_calls', 0))
            for s in results_by_strategy) + " |")
    return "\n".join(lines)
