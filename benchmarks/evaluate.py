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


# ---------------------------------------------------------------- specificity ablation (P3)

_STOP = {
    "that", "with", "this", "they", "their", "have", "from", "when", "what", "would",
    "could", "about", "into", "than", "then", "them", "these", "those", "your", "you",
    "and", "for", "the", "are", "not", "but", "its", "will", "can", "has", "was", "were",
    "been", "more", "less", "most", "only", "also", "because", "before", "after", "while",
    "over", "under", "just", "very", "much", "some", "any", "all", "each", "other", "such",
}


def _tokens(text: str) -> set[str]:
    import re
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) >= 4 and w not in _STOP}


def generic_personas(personas: list) -> list:
    """Strip decision-relevant specificity to reproduce the old generic panel."""
    from app.core.pipeline import SPECIFICITY_FIELDS

    return [p.model_copy(update={
        "situation": "", "job_to_be_done": "", "current_solution": "",
        "objections": [], "proof_needs": [], "switching_cost": "medium",
        "inferred_hypotheses": [h for h in p.inferred_hypotheses
                                if h.field.strip().lower() not in SPECIFICITY_FIELDS],
    }) for p in personas]


def attribute_utilization(responses, personas) -> float:
    """Fraction of personas whose answers reference a persona-specific attribute."""
    vocab = {
        p.id: _tokens(" ".join([p.situation, p.job_to_be_done, p.current_solution,
                                *p.objections, *p.proof_needs, *p.decision_criteria]))
        for p in personas
    }
    if not responses:
        return float("nan")
    hits = sum(
        1 for r in responses
        if any(vocab.get(r.persona_id, set()) & _tokens(a.explanation) for a in r.answers)
    )
    return hits / len(responses)


def _mean_sd(responses, qids) -> float:
    sds = []
    for q in qids:
        ratings = [a.rating for r in responses for a in r.answers
                   if a.question_id == q and a.rating is not None]
        if len(ratings) > 1:
            sds.append(statistics.pstdev(ratings))
    return statistics.fmean(sds) if sds else 0.0


def specificity_ablation(brief_data: dict, image_bytes: bytes, image_name: str,
                         question_ids: list[str], panel: int = 12) -> dict:
    """Generic-vs-specific respond ablation (needs a provider key).

    Holds the ad, brief, and persona slots constant; only the decision-relevant
    fields are stripped for the generic condition. Reports between-persona rating
    SD, attribute utilization, and respond-token delta.
    """
    from app.core.models import EvaluationTrace, PersonaSet
    from app.core.pipeline import collect_responses, run_pipeline, select_questions, verify_image

    ctype = "image/png" if image_name.lower().endswith(".png") else "image/jpeg"
    content, mime, _ = verify_image(image_bytes, image_name, ctype)
    questions = select_questions(question_ids)
    base = asyncio.run(run_pipeline(
        brief_data=brief_data, image=content, filename=image_name, content_type=mime,
        question_ids=question_ids, persona_count=panel))
    ok_status = ("complete", "complete_with_warnings", "complete_high_disagreement")
    if base.status not in ok_status or base.personas is None or base.extraction is None:
        return {"benchmark_version": BENCHMARK_VERSION, "error": base.status, "pass": False}
    generic_set = PersonaSet(coverage_label="coverage_panel",
                             personas=generic_personas(base.personas.personas))
    trace = EvaluationTrace(evaluation_id="ablation-generic", model=base.trace.model)
    generic = asyncio.run(collect_responses(generic_set, base.extraction, questions, None, trace))
    spec_sd = _mean_sd(base.responses, question_ids)
    gen_sd = _mean_sd(generic, question_ids)
    util = attribute_utilization(base.responses, base.personas.personas)
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "panel": len(base.personas.personas),
        "questions": question_ids,
        "specific_between_persona_sd": round(spec_sd, 4),
        "generic_between_persona_sd": round(gen_sd, 4),
        "specific_attribute_utilization": round(util, 3),
        "specific_respond_tokens": sum(c.output_tokens for c in base.trace.calls
                                       if c.stage == "respond"),
        "generic_respond_tokens": sum(c.output_tokens for c in trace.calls if c.stage == "respond"),
        "pass": bool(spec_sd >= gen_sd and util >= 0.3),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("metrics")
    m.add_argument("--pred", required=True)
    m.add_argument("--human", required=True)
    sub.add_parser("replay-cached")
    f = sub.add_parser("replay-fresh")
    f.add_argument("--n", type=int, default=5)
    s = sub.add_parser("specificity")
    s.add_argument("--brief", required=True, help="JSON file with AudienceBrief fields")
    s.add_argument("--image", required=True, help="ad image (PNG/JPEG)")
    s.add_argument("--questions", default="clarity,relevance")
    s.add_argument("--panel", type=int, default=12)
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
    elif args.cmd == "specificity":
        brief = json.loads(Path(args.brief).read_text())
        image_path = Path(args.image)
        print(json.dumps(specificity_ablation(brief, image_path.read_bytes(), image_path.name,
                                              args.questions.split(","), args.panel), indent=2))


if __name__ == "__main__":
    main()
