"""Output schema, allowed enum values, and the deterministic normalization layer.

The LLM agents return judgments; this module is the *contract enforcer*. It
snaps every field to an allowed value, applies cross-field consistency rules,
de-duplicates risk flags, and guarantees the exact output column order. Keeping
this deterministic (no LLM) is what makes the submission reproducible and is the
last line of defence against a model returning an off-spec string.
"""
from __future__ import annotations

import difflib
from typing import Iterable

# ---- Exact output column order (must match problem_statement.md) -----------
OUTPUT_COLUMNS = [
    "user_id",
    "image_paths",
    "user_claim",
    "claim_object",
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "claim_status_justification",
    "supporting_image_ids",
    "valid_image",
    "severity",
]

# ---- Allowed values --------------------------------------------------------
CLAIM_STATUS = {"supported", "contradicted", "not_enough_information"}

ISSUE_TYPE = {
    "dent", "scratch", "crack", "glass_shatter", "broken_part", "missing_part",
    "torn_packaging", "crushed_packaging", "water_damage", "stain",
    "none", "unknown",
}

OBJECT_PART = {
    # car
    "front_bumper", "rear_bumper", "door", "hood", "windshield", "side_mirror",
    "headlight", "taillight", "fender", "quarter_panel", "body",
    # laptop
    "screen", "keyboard", "trackpad", "hinge", "lid", "corner", "port", "base",
    # package
    "box", "package_corner", "package_side", "seal", "label", "contents", "item",
    # shared
    "unknown",
}

PART_BY_OBJECT = {
    "car": {"front_bumper", "rear_bumper", "door", "hood", "windshield",
            "side_mirror", "headlight", "taillight", "fender", "quarter_panel",
            "body", "unknown"},
    "laptop": {"screen", "keyboard", "trackpad", "hinge", "lid", "corner",
               "port", "base", "body", "unknown"},
    "package": {"box", "package_corner", "package_side", "seal", "label",
                "contents", "item", "unknown"},
}

RISK_FLAGS = {
    "none", "blurry_image", "cropped_or_obstructed", "low_light_or_glare",
    "wrong_angle", "wrong_object", "wrong_object_part", "damage_not_visible",
    "claim_mismatch", "possible_manipulation", "non_original_image",
    "text_instruction_present", "user_history_risk", "manual_review_required",
}

SEVERITY = {"none", "low", "medium", "high", "unknown"}

# Risk flags ordered for stable, readable output.
RISK_FLAG_ORDER = [
    "blurry_image", "cropped_or_obstructed", "low_light_or_glare", "wrong_angle",
    "wrong_object", "wrong_object_part", "damage_not_visible", "claim_mismatch",
    "possible_manipulation", "non_original_image", "text_instruction_present",
    "user_history_risk", "manual_review_required",
]


def _closest(value: str, allowed: Iterable[str], default: str) -> str:
    """Snap a free-form model string to the closest allowed enum value."""
    if value is None:
        return default
    v = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    allowed = set(allowed)
    if v in allowed:
        return v
    # common synonyms
    synonyms = {
        "shattered_glass": "glass_shatter", "shattered": "glass_shatter",
        "broken": "broken_part", "missing": "missing_part",
        "torn": "torn_packaging", "crushed": "crushed_packaging",
        "wet": "water_damage", "no_issue": "none", "no_damage": "none",
        "mirror": "side_mirror", "bumper": "body", "panel": "quarter_panel",
        "screen_crack": "crack",
    }
    if v in synonyms and synonyms[v] in allowed:
        return synonyms[v]
    match = difflib.get_close_matches(v, allowed, n=1, cutoff=0.82)
    return match[0] if match else default


def norm_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}


def norm_issue_type(value) -> str:
    return _closest(value, ISSUE_TYPE, "unknown")


def norm_object_part(value, claim_object: str | None = None) -> str:
    allowed = PART_BY_OBJECT.get(claim_object, OBJECT_PART) if claim_object else OBJECT_PART
    return _closest(value, allowed, "unknown")


def norm_severity(value) -> str:
    return _closest(value, SEVERITY, "unknown")


def norm_claim_status(value) -> str:
    v = _closest(value, CLAIM_STATUS, "not_enough_information")
    return v


def norm_risk_flags(flags: Iterable[str]) -> str:
    """De-dupe, validate, order; collapse to 'none' when empty."""
    seen = set()
    for f in flags or []:
        nf = _closest(f, RISK_FLAGS, "")
        if nf and nf != "none":
            seen.add(nf)
    if not seen:
        return "none"
    return ";".join(f for f in RISK_FLAG_ORDER if f in seen)


def norm_supporting_ids(ids: Iterable[str], available: set[str]) -> str:
    """Keep only image IDs that actually exist for the claim; 'none' if empty."""
    out = []
    for i in ids or []:
        i = str(i).strip()
        if i in available and i not in out:
            out.append(i)
    return ";".join(out) if out else "none"


def enforce_consistency(row: dict) -> dict:
    """Cross-field rules so the row is internally coherent. Defensible and
    deterministic — applied after the adjudicator returns its judgment."""
    status = row["claim_status"]

    # not_enough_information => no supporting images, evidence not met.
    if status == "not_enough_information":
        row["supporting_image_ids"] = "none"
        row["evidence_standard_met"] = False

    # If evidence standard is not met, we cannot affirm or contradict.
    if not row["evidence_standard_met"] and status != "not_enough_information":
        row["claim_status"] = "not_enough_information"
        row["supporting_image_ids"] = "none"

    # No visible issue => severity none.
    if row["issue_type"] == "none":
        row["severity"] = "none"

    # Indeterminable issue => severity unknown (unless already none).
    if row["issue_type"] == "unknown" and row["severity"] not in {"none", "unknown"}:
        row["severity"] = "unknown"

    # supported decision must cite at least one supporting image.
    if status == "supported" and row["supporting_image_ids"] == "none":
        # fall back: insufficient grounding -> downgrade
        row["claim_status"] = "not_enough_information"
        row["evidence_standard_met"] = False

    # manual_review_required implies the review is flagged; ensure ordering kept.
    return row
