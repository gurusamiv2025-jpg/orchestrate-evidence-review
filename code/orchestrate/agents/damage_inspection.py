"""Agent 4 — Damage Inspection (vision, primary = Opus).

The core visual reasoning step. Per image, identifies the object/part actually
shown, the visible issue and severity, and whether the visible evidence is
consistent with the claim. The claim is passed as *context to look for*, never
as an assumption to confirm.
"""
from __future__ import annotations

from .. import prompts_loader
from ..io_utils import ImageRef, encode_image
from ..llm_client import LLMClient

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "object_type_in_image": {"type": "string"},
        "object_matches_claim": {"type": "boolean"},
        "claimed_part_visible": {"type": "boolean"},
        "visible_object_part": {"type": "string"},
        "visible_issue_type": {"type": "string"},
        "damage_present": {"type": "boolean"},
        "severity": {"type": "string",
                     "enum": ["none", "low", "medium", "high", "unknown"]},
        "consistency_with_claim": {"type": "string",
                                   "enum": ["match", "mismatch", "unclear"]},
        "description": {"type": "string"},
    },
    "required": ["object_type_in_image", "object_matches_claim",
                 "claimed_part_visible", "visible_object_part",
                 "visible_issue_type", "damage_present", "severity",
                 "consistency_with_claim", "description"],
}

_MOCK = {
    "object_type_in_image": "unknown", "object_matches_claim": True,
    "claimed_part_visible": True, "visible_object_part": "unknown",
    "visible_issue_type": "unknown", "damage_present": False, "severity": "unknown",
    "consistency_with_claim": "unclear", "description": "(dry-run) inspection stub",
}


def run(llm: LLMClient, model: str, claim_object: str, intent: dict,
        ref: ImageRef) -> dict:
    system = prompts_loader.load("damage_inspection")
    img_block = encode_image(ref)
    if img_block is None:
        return {**_MOCK, "object_type_in_image": "missing/unreadable",
                "object_matches_claim": False, "claimed_part_visible": False,
                "consistency_with_claim": "unclear",
                "description": "image could not be read", "image_id": ref.image_id}
    context = (
        f"Claimed object: {claim_object}\n"
        f"Claimed part: {intent.get('claimed_object_part', 'unknown')}\n"
        f"Claimed issue: {intent.get('claimed_issue_type', 'unknown')}\n"
        f"Claimed severity (from words): {intent.get('claimed_severity', 'unknown')}\n"
        f"Image ID: {ref.image_id}\n\nInspect this single image:"
    )
    result = llm.call_structured(
        agent="damage_inspection", model=model, system=system,
        content_blocks=[{"type": "text", "text": context}, img_block],
        tool_name="record_damage_inspection", tool_schema=TOOL_SCHEMA,
        mock_default=_MOCK, n_images=1,
    )
    result["image_id"] = ref.image_id
    return result
