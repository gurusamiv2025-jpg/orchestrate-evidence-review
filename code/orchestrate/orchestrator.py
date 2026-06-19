"""Orchestrator — runs the agent graph for one claim and assembles the final row.

Pipeline (orchestrated strategy):

    claim_understanding (text)            what is being claimed
            |
    evidence_resolver (deterministic)     what evidence is required
            |
    for each image:
       image_triage (vision)              is the image usable & authentic?
       damage_inspection (vision, Opus)   what damage is actually visible?
            |
    history_risk (deterministic)          is the claimant risky?
            |
    adjudicator (text, Opus)              final judgment
            |
    risk-flag assembly + normalization    deterministic contract enforcement

Division of labour: LLMs do perception & judgment; deterministic code does
bookkeeping (evidence mapping, risk-flag union, enum normalization, consistency).
"""
from __future__ import annotations

from . import schema
from .agents import (adjudicator, claim_understanding, damage_inspection,
                     evidence_resolver, history_risk, image_triage, monolithic)
from .config import Strategy
from .io_utils import Claim
from .llm_client import LLMClient


def process_claim(claim: Claim, *, llm: LLMClient, strategy: Strategy,
                  requirements: list[dict], history_index: dict) -> dict:
    history_row = history_index.get(claim.user_id)
    hist = history_risk.run(history_row)
    available_ids = {ref.image_id for ref in claim.images}

    if strategy.monolithic:
        decision = _run_monolithic(claim, llm, strategy, requirements, hist)
        return _finalize(claim, decision, hist, triage=[], available_ids=available_ids,
                         monolithic=True)

    # 1. understand the claim (text, cheap)
    intent = claim_understanding.run(
        llm, strategy.claim_understanding_model, claim.claim_object, claim.user_claim)

    # 2. resolve evidence requirement (deterministic)
    requirement = evidence_resolver.resolve(
        requirements, claim.claim_object, intent.get("issue_family", "general"))

    # 3. per-image triage + damage inspection (vision)
    triage, inspection = [], []
    for ref in claim.images:
        triage.append(image_triage.run(
            llm, strategy.image_triage_model, claim.claim_object, ref))
        inspection.append(damage_inspection.run(
            llm, strategy.damage_inspection_model, claim.claim_object, intent, ref))

    # 4. adjudicate (text, Opus)
    decision = adjudicator.run(
        llm, strategy.adjudicator_model, claim_object=claim.claim_object,
        intent=intent, requirement=requirement, triage=triage,
        inspection=inspection, history=hist)
    decision["_intent"] = intent
    return _finalize(claim, decision, hist, triage=triage,
                     available_ids=available_ids, monolithic=False)


def _run_monolithic(claim, llm, strategy, requirements, hist):
    requirement = evidence_resolver.resolve(requirements, claim.claim_object, "general")
    return monolithic.run(
        llm, strategy.monolithic_model, claim_object=claim.claim_object,
        user_claim=claim.user_claim, requirement=requirement,
        images=claim.images, history_summary=hist.get("summary", ""))


# ---------------------------------------------------------------------------
def _assemble_risk_flags(decision, hist, triage, claim_status, monolithic) -> list[str]:
    flags: set[str] = set()

    if monolithic:
        # baseline returns its own flag list; we still union history + policy.
        for f in decision.get("risk_flags", []) or []:
            flags.add(f)
    else:
        # quality / authenticity / injection flags from triage (any image)
        for t in triage:
            for q in t.get("quality_flags", []) or []:
                flags.add(q)
            if t.get("non_original_image"):
                flags.add("non_original_image")
            if t.get("possible_manipulation"):
                flags.add("possible_manipulation")
            if t.get("text_instruction_present"):
                flags.add("text_instruction_present")
        # semantic flags from the adjudicator
        for f in decision.get("extra_risk_flags", []) or []:
            flags.add(f)

    # user-history risk (deterministic)
    if hist.get("user_history_risk"):
        flags.add("user_history_risk")

    # manual-review policy: escalate to a human when we would deny the claim,
    # when authenticity is in doubt, or when the claimant is high-risk.
    authenticity_doubt = bool(flags & {"non_original_image", "possible_manipulation"})
    if (hist.get("user_history_risk") or hist.get("manual_review_in_history")
            or authenticity_doubt or claim_status == "contradicted"):
        flags.add("manual_review_required")

    flags.discard("none")
    return list(flags)


def _finalize(claim, decision, hist, *, triage, available_ids, monolithic) -> dict:
    claim_status = schema.norm_claim_status(decision.get("claim_status"))

    # valid_image: deterministic from triage usability when available.
    if not monolithic and triage:
        valid_image = any(t.get("usable_for_review") for t in triage)
    else:
        valid_image = schema.norm_bool(decision.get("valid_image"), default=True)

    risk_list = _assemble_risk_flags(decision, hist, triage, claim_status, monolithic)

    row = {
        # passthrough inputs
        "user_id": claim.user_id,
        "image_paths": claim.image_paths,
        "user_claim": claim.user_claim,
        "claim_object": claim.claim_object,
        # judgments
        "evidence_standard_met": schema.norm_bool(decision.get("evidence_standard_met")),
        "evidence_standard_met_reason": (decision.get("evidence_standard_met_reason") or "").strip(),
        "risk_flags": schema.norm_risk_flags(risk_list),
        "issue_type": schema.norm_issue_type(decision.get("issue_type")),
        "object_part": schema.norm_object_part(decision.get("object_part"), claim.claim_object),
        "claim_status": claim_status,
        "claim_status_justification": (decision.get("claim_status_justification") or "").strip(),
        "supporting_image_ids": schema.norm_supporting_ids(
            decision.get("supporting_image_ids", []), available_ids),
        "valid_image": valid_image,
        "severity": schema.norm_severity(decision.get("severity")),
    }
    row = schema.enforce_consistency(row)
    # re-normalize risk flags after consistency may have changed status
    if row["claim_status"] != claim_status:
        risk_list = _assemble_risk_flags(decision, hist, triage, row["claim_status"], monolithic)
        row["risk_flags"] = schema.norm_risk_flags(risk_list)
    return row
