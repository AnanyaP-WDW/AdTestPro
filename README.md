# AdTestPro — Synthetic Focus Groups for Ad Creatives

Upload an ad. Get a coverage panel of up to 25 AI respondents (default 12), structured
extraction of what's actually in the creative, dimension scores with disagreement flags,
and evidence-linked recommendations — in about a minute, for cents per run.

> **Honest label:** produces schema-valid, evidence-linked ad evaluations. This is an
> experimental creative-screening signal — not a replacement for human research, and it
> makes no CTR, sales, or causal-lift claims.

## Why it exists

Human panels are slow and expensive; gut-feel creative review is fast but uncalibrated.
AdTestPro sits between: a **bounded, auditable pipeline** where LLMs produce
evidence-grounded judgments and **Python computes every number**. The model never writes
a final score.

```text
Brief → N constrained personas (1–25, default 12) → 1 multimodal extraction → independent answers
      → deterministic aggregates → theme synthesis → evidence critic → result
```

## What you get per run

- **Coverage panel, not fake people** — 12 personas spanning your pain points, interests,
  familiarity, price sensitivity, and skeptical→receptive stance, each tracing every fact
  to your brief (`supplied`) vs. inference (`hypothesis + basis`). No names, no
  backstories, no sensitive attributes.
- **Observation vs. interpretation split** — visible text (exact), brand, claims, CTA with
  evidence quotes and image regions, kept separate from tone/symbolism/persuasion reads.
  Missing logo, price, or CTA stays `unknown` — never invented.
- **Stable 1–5 rubrics** — attention, clarity, relevance, credibility, action intent, each
  with behavioral anchors. Disagreement widens the range instead of averaging it away,
  and minority views survive synthesis by construction.
- **Receipts** — every run records model ID, prompt hashes, token use, latency, repairs,
  warnings, and code revision. Cached replay is bit-for-bit deterministic.

## Quickstart

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env   # add your key (OpenAI, or OpenRouter, see below)
uvicorn app.main:app --reload
```

Open `http://localhost:8000/`, fill the brief, upload a PNG/JPEG (≤15MB), pick up to 3
questions, set the panel size (1–25 personas, default 12 — larger panels cost and run
linearly longer), submit. JSON API at `POST /api/evaluations` (optional `persona_count`
form field); contracts in `/openapi.json`.

**OpenRouter:**

```bash
OPENAI_API_KEY=sk-or-v1-your-key
ADTESTPRO_BASE_URL=https://openrouter.ai/api/v1
ADTESTPRO_MODEL=openai/gpt-4o-mini   # must be vision-capable
```

`GET /ready` reports `{"ready": true}` when configured; `GET /health` is the offline
liveness probe. ~$0.05–0.15 per 12-persona × 3-question run.

**Model hedge (optional):** set `ADTESTPRO_MODELS=modelA,modelB` to rotate a pool of
models across personas during scoring — each persona answers via `pool[i % len(pool)]`,
so a single vendor's priors can't dominate every judgment. Extraction, synthesis, and
the critic stay on the primary `ADTESTPRO_MODEL`; per-call models are recorded in
`trace.calls[].model`, and disagreeing scores widen ranges rather than average away.

## UI conventions

Professional B2B operator UI (`app/templates/` + `app/static/app.css` design system).
No frontend framework, no CDN, no remote fonts: tokens and components live in one
checked-in stylesheet (light/dark via CSS variables), behavior in one `app.js`.
Shell = brand + primary nav (Evaluate, API docs) + provider readiness + theme toggle;
every page has one `<h1>`, a skip link, and labelled scrollable tables.
Flow: guided three-step form (Creative → Audience → Research setup) with local image
preview, field-level validation parity between browser and server, an honest pending
state (no fake progress stages), and a decision-ready report ordered
Context → At a glance → Recommended actions → Dimension scores (with 1–5 distributions)
→ Themes (evidence-linked) → Extraction → Panel details → Provenance. Rendered
snapshots: `assets/*.snapshot.html` (screenshots blocked: no browser engine here).

## Docs & rigor

- `benchmarks/README.md` — PersonaBench / AdExtract-60 / AdScore-24 protocols, gate
  thresholds, and what's blocked on human data
- `benchmarks/evaluate.py` — metrics + deterministic replay (`replay-cached`, `replay-fresh`)
- 83 offline tests (`pytest tests/`) run the full pipeline on fixtures with zero network

## Research grounding

Academic (most-cited first):

1. Generative Agents (Park et al., Stanford/Google, UIST'23) — 25-agent society — https://arxiv.org/abs/2304.03442
2. Out of One, Many / Silicon Samples (Argyle et al., 2022/23) — template for persona conditioning — https://arxiv.org/abs/2209.06899
3. Automatic Understanding of Image/Video Ads (Hussain et al., CVPR'17) — Pitt Ads 64k benchmark — https://people.cs.pitt.edu/~kovashka/ads/
4. Generative Agent Simulations of 1,000 People (Stanford, 2024) — https://arxiv.org/abs/2411.10109
5. Persuasion Strategies in Ads (AAAI'23) — https://doi.org/10.1609/aaai.v37i1.25076
6. Focus Agent: LLM Virtual Focus Group (2024) — https://arxiv.org/html/2409.01907
7. ADVI-SOR (ACL Industry'26) — https://aclanthology.org/2026.acl-industry.28.pdf
8. TRADE (ACL'24) — https://aclanthology.org/2024.acl-short.77.pdf

Industry / popular:

9. Microsoft TinyTroupe — https://github.com/microsoft/TinyTroupe
10. I Asked 100 AI Agents to Judge an Ad (Every.to, 2025) — https://every.to/also-true-for-humans/how-i-made-ai-think-like-a-focus-group
11. Evidenza / Toluna Instant / SyntheticUsers + FishDog — https://www.evidenza.ai/ , https://tolunacorporate.com/our-solutions/creative-and-campaigns/creative-pretest-instant/ , https://fish.dog/product-releases/introducing-screening-room-test-ads-content-and-films-with-a-synthetic-audience
12. your-ai-focus-group (OSS near-clone) — https://github.com/shagghiesuperstar/your-ai-focus-group

## License

See `LICENSE`.
