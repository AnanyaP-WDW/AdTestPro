# Benchmarks (P5 / E5 / S6) — status: scaffold + metric tooling DONE, human data BLOCKED

Engineering is complete: `benchmarks/evaluate.py` implements every computable metric
(Spearman, MAE, mean bias, synthetic/human variance ratio, core-field F1,
persuasion macro-F1, pairwise accuracy, per-ad stability SD) with stdlib only,
plus `replay-cached` (V2 bit-identical check) and `replay-fresh --n 5` (S6/V2 stability).

```bash
venv/bin/python benchmarks/evaluate.py replay-cached
venv/bin/python benchmarks/evaluate.py metrics --pred preds.json --human humans.json
OPENAI_API_KEY=... venv/bin/python benchmarks/evaluate.py replay-fresh --n 5
```

## What's blocked on human participation (named blockers)

- **P5 PersonaBench-MVP** — BLOCKED on recruiting ~30 consenting participants, collecting
  structured profiles + 12-ad ratings + duplicates + 7–14-day retest. Protocol per PLAN.md.
  Gates: profile fidelity ≥95%, contradiction ≤5%, grounded beats shuffled by ≥0.10
  Spearman or 10% MAE, variance ratio 0.70–1.30, unsupported-demo-explanation ≤2%.
  Fallback (in plan): if grounded ≈ shuffled, drop personalization claims, use generic panels.
- **E5 AdExtract-60** — BLOCKED on assembling 60 legally-usable ads + 2 independent annotators
  + adjudication + controlled variants (logo/CTA removed, price changed, object added,
  unreadable text). Gates: κ≥0.60, core micro-F1≥0.90, claim F1≥0.85, persuasion macro-F1≥0.65,
  unsupported <3%, zero price/health/legal hallucinations, ≥90% perturbation stability.
- **S6 AdScore-24** — BLOCKED on 24 held-out ads × ~15 human ratings with duplicates +
  matched pairs + degraded variants. Gates per PLAN.md (overall Spearman ≥0.50, MAE ≤0.75,
  pair accuracy ≥70%, degraded-direction ≥80%, fresh-run SD ≤0.20, repeat rank-corr ≥0.90,
  loop beats direct scoring by ≥0.05 Spearman or 10% MAE or synthesis/critic leaves scoring path).
- **V1 holdout** — BLOCKED until above pass; 12 unseen ads (`holdout_manifest.json`), run once.

## Release labels (V3) — current gate: engineering only

> “Produces schema-valid, evidence-linked ad evaluations”

Higher claims unlock only with the matching benchmark evidence. Never “replaces focus
groups”; no CTR/sales/causal-lift language without prospective campaign evidence.
