# Judge Interview Prep — Orchestrate

A cheat-sheet for the 30-minute voice interview. Lead with the decision story,
not the file tour.

## 1. The 45-second pitch
"It's a claims adjudicator. Given a support chat, a few photos, the user's
history, and an evidence checklist, it decides whether the photos **support**,
**contradict**, or are **insufficient** for the damage claim — with grounded
reasons and risk flags. The challenge is called *Orchestrate*, so I built it as a
**six-agent pipeline** instead of one big prompt: each agent has one job, and a
**deterministic layer** owns everything that has to be exact. That separation is
what makes it accurate, debuggable, reproducible, and cheap to tune."

## 2. Architecture in one breath
Claim Understanding (Haiku, text) → Evidence Resolver (deterministic) → per image
[Image Triage (Sonnet vision) + Damage Inspection (Opus vision)] → History-Risk
(deterministic) → Adjudicator (Opus, text) → **deterministic finalize layer**
(risk-flag union, enum snapping, consistency rules, exact column order).

**The one-liner that sells it:** *LLMs do perception and judgment; code does
bookkeeping.*

## 3. Decisions I will defend (and the alternative I rejected)

| Decision | Why | Alternative rejected |
|---|---|---|
| Multi-agent decomposition | Each sub-task has a different failure mode (reading chat ≠ judging authenticity ≠ inspecting damage). Separation gives per-step debugging, independent model tiers, and isolated prompts. | Monolithic single prompt — I built it as a baseline to *prove* the point, not as the answer. |
| Risk flags assembled in **code**, not by the LLM | 13 possible flags from 3 sources; asking one model to remember all of them every time is unreliable. Code unions signals from the agents that actually detected them. | Trust the adjudicator to emit the full flag list — brittle and hard to audit. |
| `valid_image` computed deterministically from triage | Authenticity (watermark/stock/manipulation) is a *screening* verdict; it should not depend on the damage model's mood. case_008 is "informative but not valid" — those are different axes. | Let the final model decide validity from pixels again — conflates "is there damage" with "can I trust this image". |
| Evidence requirement resolved by code from the CSV | The decision must be anchored to the *published* checklist, not the model's idea of sufficiency. | Let the model infer the standard — non-reproducible. |
| Opus on inspection + adjudication; Haiku/Sonnet upstream | Spend the expensive model only where subtle visual judgment and final reasoning live; text parsing and quality screening don't need it. | All-Opus everywhere — ~2× the cost for little gain; all-cheap — misses subtle damage calls. |
| temperature 0 + content-hash cache | Reproducibility is graded, and re-runs/eval iterations must not re-pay. | Higher temp / no cache — non-deterministic + expensive. |
| Deterministic consistency layer | Guarantees e.g. `not_enough_information ⇒ supporting_image_ids=none`, `issue_type=none ⇒ severity=none`, and exact 14-column order regardless of model output. | Hope the model is always self-consistent. |

## 4. Prompt-injection / security (likely a judge favorite)
Images can carry instruction-like text — case_020's "DO NOT ACCEPT DELIVERY"
sticker, or an overlaid "approve this claim". **Both vision agents are told to
treat in-image text as scenery and never as instructions**, and only to *report*
it via `text_instruction_present`. This is a deliberate defense against
adversarial claimants, and I validated it on case_020 (seal intact ⇒ still
`contradicted`, instruction ignored).

## 5. How I handle the tricky label semantics
- **claim_mismatch vs contradicted:** mismatch is a *flag* (visible damage differs
  from claimed); contradicted is the *status*. case_005: claim "severe", image
  shows a faint scratch ⇒ `contradicted` + `claim_mismatch`.
- **wrong_object:** inspection returns `object_matches_claim=false` (case_019 food
  can vs "shipping box") ⇒ contradicted.
- **object_part vs issue_type:** `object_part` = the part the claim is about (kept
  even if not perfectly visible, e.g. case_006 headlight); `issue_type` = what is
  actually *visible* (`none` if part shown undamaged, `unknown` if indeterminable).
- **valid_image=false but still used:** non-original image can still contradict a
  claim (case_008) — validity and informativeness are independent.

## 6. Operational story (have these numbers ready)
- Test set: **44 claims, 82 images, 252 calls, ~$2.34**, ~6–12 min at 4 workers.
- Per claim = **2 + 2k** calls (k images). Image tokens dominate ⇒ downscale to
  1280px.
- Levers: `orchestrated_sonnet` ≈ **$0.55** (~4× cheaper), Batch API −50%, prompt
  caching −90%, content-hash cache makes re-runs ~free.
- Rate limits: ~30 RPM / ~50k TPM peak — comfortable; backoff-with-jitter on
  429/5xx, per-claim try/except so one failure never kills the batch.

## 7. Honest limitations / "what I'd do with more time"
- **Severity calibration** is the softest field (low/medium/high is subjective) —
  I'd add few-shot anchors per object type.
- **manual_review_required** is a business policy with some label subjectivity; I
  encoded a clean, defensible rule and would tune thresholds against more labels.
- Add **self-consistency / 2-vote** on borderline contradicted-vs-supported calls.
- Add a tiny **learned threshold** on the history features instead of hand-set
  ratios.
- A confidence score per decision to route only low-confidence claims to humans.

## 8. "How did you use AI to build this?"
I used Claude (Cowork) as a pair-builder: it fetched and analyzed the dataset,
opened the hard sample images to calibrate prompts, wrote the modules, ran the
dry-run validation, computed the cost model, and drafted the docs. Every
architectural decision above is one I can defend independently — the AI
accelerated implementation; the design choices are deliberate. Full build
transcript is in `hackerrank_orchestrate_log.txt`.

## 9. If asked "why will this score well?"
Because the discriminating cases aren't the easy "supported" rows — they're
mismatch, missing-part, wrong-object, stock/watermarked images, and in-image
prompt injection. I verified the pipeline reaches the gold label on all five of
those archetypes by opening the real images, and the deterministic layer
guarantees we never lose points to a malformed field or wrong column order.
