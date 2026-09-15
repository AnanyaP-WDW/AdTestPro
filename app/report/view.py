"""Report view model (A2/report). One pure builder feeds the web report and the PDF.

Every number the UI or the PDF shows is derived here, so the two surfaces cannot
disagree: both templates include the same partial and read the same dict.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from app.report.charts import radar_svg

RATING_SCALE = 5

# Human-readable labels; raw ids stay in data attributes for tests/provenance.
STATUS_LABELS = {
    "complete": ("Complete", "ok"),
    "complete_with_warnings": ("Complete — with warnings", "warn"),
    "complete_high_disagreement": ("Complete — high disagreement", "warn"),
    "insufficient_evidence": ("Insufficient evidence", "warn"),
    "persona_invalid": ("Brief rejected", "danger"),
    "extraction_invalid": ("Ad could not be analyzed", "danger"),
    "budget_exhausted": ("Time budget exceeded", "danger"),
    "pipeline_error": ("Run failed", "danger"),
}
QUESTION_LABELS = {
    "attention": "Attention",
    "clarity": "Clarity",
    "relevance": "Relevance",
    "credibility": "Credibility",
    "action_intent": "Action intent",
}
STANCE_ORDER = ["skeptical", "neutral", "receptive"]
FAMILIARITY_ORDER = ["new", "casual", "regular", "expert"]
SENTIMENT_ORDER = ["positive", "negative", "mixed", "minority"]


def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1) if total else 0.0


def _humanize(token: str) -> str:
    return str(token).replace("_", " ")


def _answer_index(result):
    """(persona_id, question_id) -> PersonaAnswer."""
    idx: dict[tuple[str, str], object] = {}
    for r in result.responses:
        for a in r.answers:
            idx[(r.persona_id, a.question_id)] = a
    return idx


def _composition(key: str, order: list[str], personas) -> dict:
    counts = Counter(getattr(p, key) for p in personas if getattr(p, key) is not None)
    rows = [{"key": k, "label": k, "count": counts.get(k, 0)} for k in order]
    for extra in sorted(set(counts) - set(order)):
        rows.append({"key": extra, "label": extra, "count": counts[extra]})
    total = sum(r["count"] for r in rows)
    for r in rows:
        r["pct"] = _pct(r["count"], total)
    return {"rows": rows, "total": total}


def _trace_stats(result) -> dict:
    calls = result.trace.calls
    try:
        from app.core.pipeline import estimate_cost_usd
        cost = estimate_cost_usd(result.trace)
    except Exception:  # pragma: no cover - cost estimate is best-effort
        cost = 0.0
    return {
        "calls": len(calls),
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "latency_ms": sum(c.latency_ms for c in calls),
        "cost_usd": cost,
    }


def build_report_view(result, question_ids: Optional[list[str]] = None) -> dict:
    """Derive every datum the report (UI + PDF) renders."""
    labels = QUESTION_LABELS
    qids = list(question_ids or [q.question_id for q in result.scores.per_question])
    persona_objs = list(result.personas.personas) if result.personas else []
    answers = _answer_index(result)

    # -- dimensions + distributions --
    dims: list[dict] = []
    for q in result.scores.per_question:
        dist = {int(k): int(v) for k, v in (q.distribution or {}).items()}
        counts = [dist.get(k, 0) for k in range(1, RATING_SCALE + 1)]
        total = sum(counts)
        nei = sum(1 for p in persona_objs
                  if (a := answers.get((p.id, q.question_id))) is not None
                  and (a.not_enough_information or a.rating is None))
        mean_pct = round((q.mean or 0) / RATING_SCALE * 100, 1)
        sd_pct = round((q.stdev or 0) / RATING_SCALE * 100, 1)
        sd_left = max(round(mean_pct - sd_pct / 2, 1), 0.0)
        dims.append({
            "id": q.question_id,
            "label": labels.get(q.question_id, q.question_id),
            "mean": q.mean, "median": q.median, "stdev": q.stdev,
            "count": q.count, "disagreement": q.disagreement,
            "distribution": counts,
            "dist_pct": [_pct(c, total) for c in counts],
            "dist_total": total,
            "nei": nei,
            "mean_pct": mean_pct,
            "sd_left": sd_left,
            "sd_width": min(sd_pct, round(100 - sd_left, 1)),
            "is_mode": [c == max(counts) and c > 0 for c in counts] if total else [False] * 5,
        })

    rated = [q for q in result.scores.per_question if q.mean is not None]
    highest = max(rated, key=lambda q: q.mean) if rated else None
    lowest = min(rated, key=lambda q: q.mean) if rated else None

    # -- persona x dimension heatmap --
    heat_rows = []
    for p in persona_objs:
        cells = []
        for qid in qids:
            a = answers.get((p.id, qid))
            if a is None:
                cells.append({"rating": None, "nei": True, "missing": True})
            else:
                nei = a.not_enough_information or a.rating is None
                cells.append({"rating": a.rating, "nei": nei, "missing": False})
        heat_rows.append({"id": p.id, "segment": p.segment, "stance": p.stance,
                          "cells": cells})

    # -- composition --
    composition = {
        "stance": _composition("stance", STANCE_ORDER, persona_objs),
        "familiarity": _composition("category_familiarity", FAMILIARITY_ORDER, persona_objs),
        "price": _composition("price_sensitivity", ["low", "medium", "high"], persona_objs),
        "brand": _composition("brand_familiarity",
                              ["unaware", "aware", "customer", "loyal"], persona_objs),
    }

    # -- themes / persuasion / models / evidence --
    theme_counts = Counter(t.sentiment for t in result.themes)
    theme_total = sum(theme_counts.values())
    theme_rows = [{"key": s, "label": s, "count": theme_counts.get(s, 0),
                   "pct": _pct(theme_counts.get(s, 0), theme_total)}
                  for s in SENTIMENT_ORDER]

    strategy_counts = Counter(result.extraction.persuasion_strategies) if result.extraction else Counter()
    strategy_rows = [{"key": k, "label": _humanize(k), "count": v}
                     for k, v in sorted(strategy_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    model_counts = Counter(r.model for r in result.responses if r.model)
    model_rows = [{"key": k, "label": k, "count": v}
                  for k, v in sorted(model_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    confidence_rows = []
    if result.extraction:
        for o in result.extraction.observations:
            confidence_rows.append({"id": o.id, "field": _humanize(o.field),
                                    "value": o.value, "confidence": o.confidence})

    # -- radar (needs >=3 rated dimensions) --
    radar_uri = radar_svg([d["label"] for d in dims], [d["mean"] for d in dims])

    # -- debias receipt --
    from app.core.settings import VENDOR_NAMES, pool_vendors  # local: avoid import churn
    scoring_models: list[str] = []
    for c in result.trace.calls:
        if c.stage == "respond" and c.model not in scoring_models:
            scoring_models.append(c.model)
    extraction_models = [c.model for c in result.trace.calls if c.stage == "extraction"][:1]
    vendors = pool_vendors(scoring_models)
    vendor_txt = ", ".join(VENDOR_NAMES.get(v, v) for v in vendors) if vendors else "—"
    mix_note = None
    if scoring_models:
        mix_note = (f"Scored by {len(scoring_models)} model(s) across {len(vendors)} "
                    f"vendor(s) [{vendor_txt}]")
        if len(vendors) == 1:
            mix_note += " — single-family pool, family bias not hedged"

    obs_ids = {o.id for o in result.extraction.observations} if result.extraction else set()
    response_map = {r.persona_id: r.answers for r in result.responses}
    response_models = {r.persona_id: r.model for r in result.responses}
    stance_counts = Counter(p.stance for p in persona_objs)
    fam_counts = Counter(p.category_familiarity for p in persona_objs)

    return {
        "result": result,
        "status_label": STATUS_LABELS.get(result.status, (result.status, "warn"))[0],
        "status_kind": STATUS_LABELS.get(result.status, (result.status, "warn"))[1],
        "q_labels": labels,
        "q_texts": {},
        "selected_labels": [labels.get(q, q) for q in qids],
        "question_ids": qids,
        "obs_ids": obs_ids,
        "response_map": response_map,
        "response_models": response_models,
        "panel_size": len(persona_objs),
        "persona_count": len(persona_objs),
        "highest": highest,
        "lowest": lowest,
        "stance_counts": dict(stance_counts),
        "fam_counts": dict(fam_counts),
        "scoring_models": scoring_models,
        "extraction_models": extraction_models,
        "mix_note": mix_note,
        # -- visual report --
        "dims": dims,
        "has_ratings": bool(rated),
        "overall_mean": result.scores.overall_mean,
        "valid_responses": result.scores.valid_responses,
        "missing_responses": result.scores.missing_responses,
        "disagreement_count": sum(1 for q in result.scores.per_question if q.disagreement),
        "heatmap": {"cols": [labels.get(q, q) for q in qids], "rows": heat_rows},
        "composition": composition,
        "theme_rows": theme_rows,
        "theme_total": theme_total,
        "strategy_rows": strategy_rows,
        "model_rows": model_rows,
        "model_max": max((r["count"] for r in model_rows), default=0),
        "show_model_mix": len(model_rows) >= 2,
        "confidence_rows": confidence_rows,
        "show_confidence": bool(confidence_rows),
        "radar_uri": radar_uri,
        "trace_stats": _trace_stats(result),
    }
