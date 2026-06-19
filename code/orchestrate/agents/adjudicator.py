"""Agent 6 — Adjudicator (text, primary = Opus).

Combines all structured findings into the final decision. Receives NO raw
images (cheaper, and forces grounding in the inspection findings rather than
re-deriving from pixels). Emits the judgment fields + the *semantic* risk flags;
quality / authenticity / history flags are unioned in deterministically by the
orchestrator.
"""
from __future__ import annotations

import json

from .. import prompts_loader
from ..llm_client import LLMClient

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_standard_met": {"type": "boolean"},
        "evidence_standard_met_reason": {"type": "string"},
        "issue_type": {"type": "string"},
        "object_part": {"type": "string"},
        "claim_status": {"type": "string",
                         "enum": ["supported", "contradicted", "not_enough_information"]},
        "claim_status_justification": {"type": "string"},
        "supporting_image_ids": {"type": "array", "items": {"type": "string"}},
        "valid_image": {"type": "boolean"},
        "severity": {"type": "string",
                     "enum": ["none", "low", "medium", "high", "unknown"]},
        "extra_risk_flags": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "claim_mismatch", "wrong_object", "wrong_object_part",
                "damage_not_visible"]},
        },
    },
    "required": ["evidence_standard_met", "evidence_standard_met_reason",
                 "issue_type", "object_part", "claim_status",
                 "claim_status_justification", "supporting_image_ids",
                 "valid_image", "severity", "extra_risk_flags"],
}

_MOCK = {
    "evidence_standard_met": False, "evidence_standard_met_reason": "(dry-run) stub",
    "issue_type": "unknown", "object_part": "unknown",
    "claim_status": "not_enough_information",
    "claim_status_justification": "(dry-run) no live model decision",
    "supporting_image_ids": [], "valid_image": True, "severity": "unknown",
    "extra_risk_flags": [],
}


def run(llm: LLMClient, model: str, *, claim_object: str, intent: dict,
        requirement: dict, triage: list[dict], inspection: list[dict],
        history: dict) -> dict:
    system = prompts_loader.load("adjudicator")
    payload = {
        "claim_object": claim_object,
        "claim_intent": intent,
        "minimum_image_evidence": requirement.get("minimum_image_evidence"),
        "per_image_quality": [
            {"image_id": t.get("image_id"),
             "object_category_seen": t.get("object_category_seen"),
             "matches_claim_object": t.get("shows_object_type_matching_claim"),
             "usable_for_review": t.get("usable_for_review"),
             "non_original_image": t.get("non_original_image"),
             "possible_manipulation": t.get("possible_manipulation"),
             "quality_flags": t.get("quality_flags")}
            for t in triage
        ],
        "per_image_damage": [
            {"image_id": d.get("image_id"),
             "object_matches_claim": d.get("object_matches_claim"),
             "claimed_part_visible": d.get("claimed_part_visible"),
             "visible_object_part": d.get("visible_object_part"),
             "visible_issue_type": d.get("visible_issue_type"),
             "damage_present": d.get("damage_present"),
             "severity": d.get("severity"),
             "consistency_with_claim": d.get("consistency_with_claim"),
             "description": d.get("description")}
            for d in inspection
        ],
        "user_history_risk": history.get("user_history_risk"),
        "user_history_summary": history.get("summary"),
    }
    content = [{"type": "text", "text":
                "Adjudicate this claim using the structured findings below. "
                "Return the final decision.\n\n" + json.dumps(payload, indent=2)}]
    return llm.call_structured(
        agent="adjudicator", model=model, system=system, content_blocks=content,
        tool_name="record_decision", tool_schema=TOOL_SCHEMA, mock_default=_MOCK,
    )
