"""Monolithic single-pass baseline (for the strategy comparison).

One vision call sees the claim, all images, the evidence requirement, and the
history summary, and returns the entire output schema directly. This is the
"just throw it at one big prompt" baseline the orchestrated pipeline is measured
against in evaluation/.
"""
from __future__ import annotations

from .. import prompts_loader
from ..io_utils import ImageRef, encode_image
from ..llm_client import LLMClient

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_standard_met": {"type": "boolean"},
        "evidence_standard_met_reason": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "issue_type": {"type": "string"},
        "object_part": {"type": "string"},
        "claim_status": {"type": "string",
                         "enum": ["supported", "contradicted", "not_enough_information"]},
        "claim_status_justification": {"type": "string"},
        "supporting_image_ids": {"type": "array", "items": {"type": "string"}},
        "valid_image": {"type": "boolean"},
        "severity": {"type": "string",
                     "enum": ["none", "low", "medium", "high", "unknown"]},
    },
    "required": ["evidence_standard_met", "evidence_standard_met_reason",
                 "risk_flags", "issue_type", "object_part", "claim_status",
                 "claim_status_justification", "supporting_image_ids",
                 "valid_image", "severity"],
}

_MOCK = {
    "evidence_standard_met": False, "evidence_standard_met_reason": "(dry-run) stub",
    "risk_flags": ["none"], "issue_type": "unknown", "object_part": "unknown",
    "claim_status": "not_enough_information",
    "claim_status_justification": "(dry-run) baseline stub",
    "supporting_image_ids": [], "valid_image": True, "severity": "unknown",
}


def run(llm: LLMClient, model: str, *, claim_object: str, user_claim: str,
        requirement: dict, images: list[ImageRef], history_summary: str) -> dict:
    system = prompts_loader.load("monolithic_baseline")
    blocks = [{"type": "text", "text":
               f"Claimed object: {claim_object}\n\nConversation:\n{user_claim}\n\n"
               f"Minimum image evidence required: {requirement.get('minimum_image_evidence')}\n"
               f"User history: {history_summary or 'none'}\n\n"
               "Images follow (labeled by ID):"}]
    n = 0
    for ref in images:
        b = encode_image(ref)
        if b is None:
            continue
        blocks.append({"type": "text", "text": f"Image ID: {ref.image_id}"})
        blocks.append(b)
        n += 1
    return llm.call_structured(
        agent="monolithic", model=model, system=system, content_blocks=blocks,
        tool_name="record_full_decision", tool_schema=TOOL_SCHEMA,
        mock_default=_MOCK, n_images=n,
    )
