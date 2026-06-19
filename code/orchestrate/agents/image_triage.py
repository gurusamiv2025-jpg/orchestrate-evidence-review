"""Agent 3 — Image Triage (vision).

Per-image quality, authenticity, and prompt-injection screening. Decides
`valid_image` inputs and most quality/authenticity risk flags. Runs on a
mid-tier model by default (configurable) — this is screening, not fine damage
assessment.
"""
from __future__ import annotations

from .. import prompts_loader
from ..io_utils import ImageRef, encode_image
from ..llm_client import LLMClient

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "object_category_seen": {"type": "string"},
        "shows_object_type_matching_claim": {"type": "boolean"},
        "quality_flags": {
            "type": "array",
            "items": {"type": "string", "enum": [
                "blurry_image", "low_light_or_glare",
                "cropped_or_obstructed", "wrong_angle"]},
        },
        "non_original_image": {"type": "boolean"},
        "possible_manipulation": {"type": "boolean"},
        "text_instruction_present": {"type": "boolean"},
        "usable_for_review": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["object_category_seen", "shows_object_type_matching_claim",
                 "quality_flags", "non_original_image", "possible_manipulation",
                 "text_instruction_present", "usable_for_review", "notes"],
}

_MOCK = {
    "object_category_seen": "unknown", "shows_object_type_matching_claim": True,
    "quality_flags": [], "non_original_image": False, "possible_manipulation": False,
    "text_instruction_present": False, "usable_for_review": True,
    "notes": "(dry-run) triage stub",
}


def run(llm: LLMClient, model: str, claim_object: str, ref: ImageRef) -> dict:
    system = prompts_loader.load("image_triage")
    img_block = encode_image(ref)
    if img_block is None:
        return {**_MOCK, "object_category_seen": "missing/unreadable",
                "shows_object_type_matching_claim": False,
                "usable_for_review": False, "quality_flags": ["cropped_or_obstructed"],
                "notes": "image could not be read"}
    content = [
        {"type": "text", "text":
         f"Claimed object type: {claim_object}\nImage ID: {ref.image_id}\n"
         "Assess this single image:"},
        img_block,
    ]
    result = llm.call_structured(
        agent="image_triage", model=model, system=system, content_blocks=content,
        tool_name="record_image_triage", tool_schema=TOOL_SCHEMA, mock_default=_MOCK,
        n_images=1,
    )
    result["image_id"] = ref.image_id
    return result
