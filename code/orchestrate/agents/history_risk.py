"""Agent 5 — User-History Risk (deterministic, no LLM).

Turns the user_history row into a risk signal. Kept rule-based so it is cheap,
explainable, and stable. The published `history_flags` column is the primary
signal; a ratio-based backstop catches risky patterns even when the flag is
absent. History adds context only — it never overrides clear visual evidence
(that policy is enforced in the adjudicator + orchestrator).
"""
from __future__ import annotations


def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def run(history_row: dict | None) -> dict:
    if not history_row:
        return {"user_history_risk": False, "manual_review_in_history": False,
                "rationale": "No user history on file.", "summary": ""}

    flags = (history_row.get("history_flags") or "").lower()
    flagged_risk = "user_history_risk" in flags
    flagged_manual = "manual_review_required" in flags

    past = _int(history_row.get("past_claim_count"))
    rejected = _int(history_row.get("rejected_claim"))
    recent = _int(history_row.get("last_90_days_claim_count"))

    # Derived backstop: heavy rejection history or a recent burst of claims.
    derived_risk = (
        rejected >= 2
        or (past >= 3 and rejected / past >= 0.30)
        or recent >= 4
    )

    risk = bool(flagged_risk or derived_risk)
    reasons = []
    if flagged_risk:
        reasons.append("history flagged as risky")
    if derived_risk and not flagged_risk:
        reasons.append(f"{rejected}/{past} prior claims rejected, {recent} in last 90 days")
    return {
        "user_history_risk": risk,
        "manual_review_in_history": bool(flagged_manual),
        "rationale": "; ".join(reasons) if reasons else "history within normal range",
        "summary": history_row.get("history_summary", ""),
    }
