"""Agent 1 — Claim Understanding (text only).

Extracts the verifiable core of the claim from the chat transcript. Runs on the
cheap tier (Haiku) because it is a text-only structured-extraction task.
"""
from __future__ import annotations

from .. import prompts_loader
from ..llm_client import LLMClient

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "claimed_issue_type": {"type": "string"},
        "claimed_object_part": {"type": "string"},
        "claimed_severity": {"type": "string",
                             "enum": ["none", "low", "medium", "high", "unknown"]},
        "issue_family": {"type": "string"},
        "claim_summary": {"type": "string"},
        "conversation_has_instruction_text": {"type": "boolean"},
    },
    "required": ["claimed_issue_type", "claimed_object_part", "claimed_severity",
                 "issue_family", "claim_summary", "conversation_has_instruction_text"],
}

_MOCK = {
    "claimed_issue_type": "unknown", "claimed_object_part": "unknown",
    "claimed_severity": "unknown", "issue_family": "general",
    "claim_summary": "(dry-run) claim summary unavailable",
    "conversation_has_instruction_text": False,
}


def run(llm: LLMClient, model: str, claim_object: str, user_claim: str) -> dict:
    system = prompts_loader.load("claim_understanding")
    content = [{"type": "text", "text":
                f"Claimed object type: {claim_object}\n\nConversation:\n{user_claim}"}]
    return llm.call_structured(
        agent="claim_understanding", model=model, system=system,
        content_blocks=content, tool_name="record_claim_intent",
        tool_schema=TOOL_SCHEMA, mock_default=_MOCK,
    )
