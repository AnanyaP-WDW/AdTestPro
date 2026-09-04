"""Benchmark metrics + replay (P5/E5/S6, V1/V2). Stdlib only.

Usage:
  python benchmarks/evaluate.py metrics --pred preds.json --human humans.json
  python benchmarks/evaluate.py replay-cached   # bit-identical cached replay (V2)
  python benchmarks/evaluate.py replay-fresh --n 5  # 5 live runs, stability report (needs key)

preds.json / humans.json: {"<ad_id>": {"<question_id>": mean_rating}}.
Extraction annotation files: {"<ad_id>": {"fields": {...}, "strategies": [...]}}.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from pathlib import Path

BENCHMARK_VERSION = "adtestpro-bench-v1"


# ---------------------------------------------------------------- rank stats (no scipy)

def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    """Spearman rank correlation (ties averaged). Returns 0.0 for degenerate input."""
    if len(a) != len(b) or len(a) < 2:
        return 0.0
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return 0.0
    return cov / math.sqrt(va * vb)


def mae(a: list[float], b: list[float]) -> float:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return float("nan")
    return sum(abs(x - y) for x, y in pairs) / len(pairs)


def mean_bias(pred: list[float], human: list[float]) -> float:
    return statistics.fmean(pred) - statistics.fmean(human)


def variance_ratio(synth: list[float], human: list[float]) -> float:
    vh = statistics.pvariance(human) if len(human) > 1 else 0.0
    vs = statistics.pvariance(synth) if len(synth) > 1 else 0.0
    return (vs / vh) if vh else float("nan")


def f1_pairwise(pred: list, gold: list) -> float:
    """Micro-F1 over (field, value) or label sets; for core-field / persuasion scoring."""
    ps, gs = set(map(str, pred)), set(map(str, gold))
    if not ps and not gs:
        return 1.0
    if not ps or not gs:
        return 0.0
    tp = len(ps & gs)
    prec = tp / len(ps)
    rec = tp / len(gs)
    return 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)


def macro_f1(per_label_f1: list[float]) -> float:
    return statistics.fmean(per_label_f1) if per_label_f1 else 0.0


def pairwise_accuracy(pred_means: dict[str, float], human_means: dict[str, float],
                      pairs: list[tuple[str, str]]) -> float:
    """Fraction of matched creative pairs ranked the same way as humans."""
    hits = 0
    for x, y in pairs:
        hp, hh = pred_means[x] - pred_means[y], human_means[x] - human_means[y]
        if (hp > 0) == (hh > 0) or (hp == 0 and hh == 0):
            hits += 1
    return hits / len(pairs) if pairs else float("nan")


def per_ad_stability(runs: list[dict[str, float]]) -> dict[str, float]:
    """Per-ad SD across fresh runs (S6 gate: <= 0.20)."""
    ads = {a for r in runs for a in r}
    return {a: (statistics.pstdev([r[a] for r in runs if a in r]) if len(runs) > 1 else 0.0)
            for a in ads}


# ---------------------------------------------------------------- gates

def score_gate(name: str, value: float, threshold: float, direction: str = ">=") -> dict:
    ok = value >= threshold if direction == ">=" else value <= threshold
    return {"gate": name, "value": value, "threshold": threshold, "pass": bool(ok)}


def scoring_gates(pred: dict, human: dict) -> list[dict]:
    """S6 engineering-side gates computable without new human data."""
    ads = sorted(set(pred) & set(human))
    qids = sorted({q for a in ads for q in human[a]})
    out = []
    for q in qids:
        p = [pred[a][q] for a in ads if q in pred[a]]
        h = [human[a][q] for a in ads if q in human[a]]
        out.append(score_gate(f"spearman[{q}]", spearman(p, h), 0.40))
        out.append(score_gate(f"mae[{q}]", mae(p, h), 0.75, "<="))
    pall = [pred[a][q] for a in ads for q in qids if q in pred.get(a, {})]
    hall = [human[a][q] for a in ads for q in qids if q in human.get(a, {})]
    out.append(score_gate("spearman[overall]", spearman(pall, hall), 0.50))
    return out


# ---------------------------------------------------------------- replay (V2)

def _fixture_fake():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os_env_model = "replay-model"
    import os
    os.environ.setdefault("ADTESTPRO_MODEL", os_env_model)
    from tests.test_pipeline import BRIEF, full_fake, make_png
    return BRIEF, full_fake, make_png


def replay_cached() -> dict:
    """Bit-for-bit deterministic replay with recorded fixtures (no network)."""
    BRIEF, full_fake, make_png = _fixture_fake()
    from app.core.pipeline import run_pipeline
    img = make_png()

    async def once():
        return await run_pipeline(brief_data=BRIEF, image=img, filename="replay.png",
                                  content_type="image/png", question_ids=["clarity", "relevance"],
                                  client=full_fake(), evaluation_id="replay-fixed")

    r1 = asyncio.run(once())
    r2 = asyncio.run(once())
    identical = (r1.personas.model_dump_json() == r2.personas.model_dump_json()
                 and r1.scores.model_dump_json() == r2.scores.model_dump_json())
    return {"benchmark_version": BENCHMARK_VERSION, "cached_replay_identical": identical,
            "status": r1.status, "pass": identical and r1.status == "complete"}


def replay_fresh(n: int = 5) -> dict:
    """Fresh live runs for stability (S6/V2). Requires OPENAI_API_KEY."""
    BRIEF, _, make_png = _fixture_fake()
    from app.core.pipeline import run_pipeline
    from tests.test_pipeline import BRIEF as _B
    img = make_png()
    runs = []
    for _ in range(n):
        r = asyncio.run(run_pipeline(brief_data=_B, image=img, filename="fresh.png",
                                     content_type="image/png",
                                     question_ids=["clarity", "relevance"]))
        runs.append({q.question_id: q.mean for q in r.scores.per_question if q.mean is not None})
    stab = per_ad_stability(runs)
    ok = all(v <= 0.20 for v in stab.values())
    return {"benchmark_version": BENCHMARK_VERSION, "n": n, "per_ad_sd": stab,
            "max_sd": max(stab.values()) if stab else None, "pass": ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("metrics")
    m.add_argument("--pred", required=True)
    m.add_argument("--human", required=True)
    sub.add_parser("replay-cached")
    f = sub.add_parser("replay-fresh")
    f.add_argument("--n", type=int, default=5)
    args = ap.parse_args()
    if args.cmd == "metrics":
        pred = json.loads(Path(args.pred).read_text())
        human = json.loads(Path(args.human).read_text())
        print(json.dumps({"benchmark_version": BENCHMARK_VERSION,
                          "gates": scoring_gates(pred, human)}, indent=2))
    elif args.cmd == "replay-cached":
        print(json.dumps(replay_cached(), indent=2))
    elif args.cmd == "replay-fresh":
        print(json.dumps(replay_fresh(args.n), indent=2))


if __name__ == "__main__":
    main()
