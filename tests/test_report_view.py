"""Report view model (report/view.py): derived metrics, edge cases, radar."""

import asyncio

from app.core.models import (
    AdExtraction, AdObservation, EvaluationResult, EvaluationTrace,
    Persona, PersonaDemographics, PersonaSet, ScoreSummary, Theme,
)
from app.report.view import build_report_view
from tests.test_pipeline import BRIEF, full_fake, make_png


def _run(qids):
    from app.core.pipeline import run_pipeline

    return asyncio.run(run_pipeline(
        brief_data=BRIEF, image=make_png(), filename="a.png",
        content_type="image/png", question_ids=qids,
        client=full_fake(question_ids=tuple(qids))))


def test_view_shape_from_real_pipeline():
    v = build_report_view(_run(["attention", "clarity", "relevance"]))
    assert len(v["dims"]) == 3
    assert v["has_ratings"] is True
    assert v["panel_size"] == 12
    assert len(v["heatmap"]["rows"]) == 12
    assert len(v["heatmap"]["cols"]) == 3
    assert all(len(r["cells"]) == 3 for r in v["heatmap"]["rows"])
    assert v["radar_uri"] and v["radar_uri"].startswith("data:image/svg+xml;base64,")
    # distributions sum to the rated count
    for d in v["dims"]:
        assert sum(d["distribution"]) == d["count"]
    # composition totals equal the panel size
    assert v["composition"]["stance"]["total"] == 12
    assert v["composition"]["familiarity"]["total"] == 12
    assert v["theme_rows"] and sum(r["count"] for r in v["theme_rows"]) == v["theme_total"]
    assert v["trace_stats"]["calls"] > 0


def test_radar_requires_at_least_three_rated_dimensions():
    v = build_report_view(_run(["clarity"]))
    assert v["radar_uri"] is None  # a single axis is not a polygon
    assert len(v["dims"]) == 1


def test_view_handles_no_personas_and_no_ratings():
    result = EvaluationResult(
        evaluation_id="eval-empty", status="insufficient_evidence",
        scores=ScoreSummary(), trace=EvaluationTrace(evaluation_id="eval-empty", model="m"))
    v = build_report_view(result, ["clarity"])
    assert v["has_ratings"] is False
    assert v["radar_uri"] is None
    assert v["heatmap"]["rows"] == []
    assert v["composition"]["stance"]["total"] == 0
    assert v["show_confidence"] is False
    assert v["show_model_mix"] is False


def test_view_computes_confidence_and_strategies():
    observation = AdObservation(id="o1", field="headline_text", value="Buy now",
                                evidence_quote="Buy now", confidence=80)
    result = EvaluationResult(
        evaluation_id="eval-x", status="complete",
        extraction=AdExtraction(observations=[observation],
                                persuasion_strategies=["scarcity_urgency", "value_price"]),
        personas=PersonaSet(personas=[Persona(
            id="p1", segment="seg", demographics=PersonaDemographics(age=30, location="Austin"),
            pain_emphasis="x", interest_emphasis="y")]),
        themes=[Theme(title="t", sentiment="minority", summary="s")],
        scores=ScoreSummary(), trace=EvaluationTrace(evaluation_id="eval-x", model="m"))
    v = build_report_view(result, [])
    assert v["confidence_rows"] == [
        {"id": "o1", "field": "headline text", "value": "Buy now", "confidence": 80}]
    assert {r["key"] for r in v["strategy_rows"]} == {"scarcity_urgency", "value_price"}
    assert next(r for r in v["theme_rows"] if r["key"] == "minority")["count"] == 1
