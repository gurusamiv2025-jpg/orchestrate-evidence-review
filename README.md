# Multi-Modal Evidence Review — Multi-Agent Damage-Claim Adjudicator

A multi-agent system that verifies insurance-style **damage claims** (cars, laptops, packages)
from submitted **images**, a **claim conversation**, **user history**, and a
**minimum-evidence checklist** — deciding whether the visual evidence **supports**,
**contradicts**, or is **insufficient** for the claim, with grounded justifications and risk flags.

Built on Claude (Opus 4.8 vision + adjudication, Sonnet image triage, Haiku claim parsing).

---

## Why multi-agent (not one big prompt)

Reading a chat, judging image *authenticity*, inspecting *damage*, applying an *evidence rule*,
and weighing *user risk* are different jobs with different failure modes. Each gets its own
specialized agent; deterministic code owns everything that must be exact.

> **Principle: the LLMs do perception and judgment; deterministic code does the bookkeeping.**

```
 conversation ─►  Claim Understanding (Haiku, text)        what is claimed?
                          │
 evidence.csv ─►  Evidence Resolver (deterministic)        what's required?
                          │
   per image ─►   Image Triage (Sonnet)  +  Damage Inspection (Opus)
                  quality/authenticity/      object/part/issue/
                  prompt-injection           severity/consistency
                          │
 user_history ─► History-Risk (deterministic)
                          │
                  Adjudicator (Opus, text)                 final decision
                          │
                  Deterministic finalize layer             risk-flag union •
                  enum normalization • consistency • exact output schema
                          │
                       output.csv
```

## Highlights

- **Six-agent orchestration** with per-task model tiers (cost where it doesn't matter, Opus where it does).
- **Prompt-injection defense** — text inside an image (e.g. a "DO NOT ACCEPT DELIVERY" sticker, or
  "approve this claim") is flagged and never obeyed.
- **Authenticity screening** — detects stock/watermarked/manipulated images (drives `valid_image`).
- **Deterministic contract layer** — risk-flag assembly, enum snapping (incl. object-conditional
  parts), cross-field consistency, and guaranteed output column order.
- **Reproducible & cost-aware** — content-hash caching, backoff/retry, per-call token+cost accounting,
  and a built-in evaluation harness comparing 3 strategies (orchestrated-Opus vs orchestrated-Sonnet
  vs a monolithic single-prompt baseline).

## Quickstart

```bash
cd code
pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY

# no key? smoke-test the plumbing with schema-valid stubs:
python main.py --dry-run --limit 3 --input ../dataset/sample_claims.csv --output /tmp/x.csv

# real run on the test claims -> ../output.csv
python main.py

# evaluate on the labeled sample + compare strategies
python evaluation/main.py
```

## Dataset

The dataset (CSVs + images) is **not committed** here (large + third-party imagery). Get it from the
challenge repo and place it at `dataset/` next to `code/`:
<https://github.com/interviewstreet/hackerrank-orchestrate-june26>

## Layout

```
code/
  main.py                 entry point -> output.csv
  orchestrate/            config, schema/normalization, io, llm client, cache, usage,
                          orchestrator, pipeline, agents/
  prompts/                versioned prompt templates
  evaluation/             metrics + strategy comparison + report
  README.md               full technical README
  JUDGE_PREP.md           design rationale, tradeoffs, failure modes
```

## Design write-up

See [`code/README.md`](code/README.md) for the full technical walkthrough and
[`code/evaluation/evaluation_report.md`](code/evaluation/evaluation_report.md) for metrics +
operational analysis (calls, tokens, cost, latency, rate-limit handling).

---

*Built for the HackerRank Orchestrate hackathon (June 2026).*
