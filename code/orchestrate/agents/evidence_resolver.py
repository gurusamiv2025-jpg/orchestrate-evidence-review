"""Agent 2 — Evidence-Requirement Resolver (deterministic, no LLM).

Maps (claim_object, issue_family) to the minimum-evidence rule(s) from
evidence_requirements.csv. Pure code => free, deterministic, fully auditable.
The resolved requirement text is injected into the adjudicator so the evidence
decision is anchored to the published checklist rather than the model's whim.
"""
from __future__ import annotations

# issue_family (from claim understanding) -> applies_to substrings to match
_FAMILY_HINTS = {
    "dent or scratch": ["dent or scratch"],
    "crack, broken, or missing part": ["crack, broken, or missing part"],
    "glass/light/mirror": ["crack, broken, or missing part"],
    "vehicle identity or orientation": ["vehicle identity or orientation"],
    "screen/keyboard/trackpad": ["screen, keyboard, or trackpad"],
    "hinge/lid/corner/body/port": ["hinge, lid, corner, body, or port"],
    "package exterior": ["crushed, torn, or seal damage"],
    "package label or stain": ["water, stain, or label damage"],
    "package contents": ["contents or inner item"],
}


def resolve(requirements: list[dict], claim_object: str, issue_family: str) -> dict:
    """Return the most specific applicable requirement plus the general ones."""
    obj = (claim_object or "").lower()
    fam = (issue_family or "general").lower()
    hints = _FAMILY_HINTS.get(fam, [])

    specific = []
    general = []
    for r in requirements:
        ro = r.get("claim_object", "").lower()
        applies = r.get("applies_to", "").lower()
        text = r.get("minimum_image_evidence", "")
        if ro == "all":
            general.append(text)
        elif ro == obj:
            if any(h in applies for h in hints):
                specific.append(text)

    chosen = specific[0] if specific else (
        # fall back to any object-specific rule, else general
        next((r.get("minimum_image_evidence", "") for r in requirements
              if r.get("claim_object", "").lower() == obj), "")
    )
    return {
        "minimum_image_evidence": chosen or (general[0] if general else
            "The claimed object and part must be clearly visible."),
        "general_requirements": general,
    }
