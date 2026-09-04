"""F2 exit criteria: JSON round-trip, rating/MIME/audience validation, missing stays missing."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.models import (
    AdExtraction,
    AudienceBrief,
    EvaluationResult,
    EvaluationTrace,
    PersonaAnswer,
    PersonaResponse,
    PersonaSet,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text())


def test_brief_valid_roundtrip_and_missing_stays_missing():
    brief = AudienceBrief.model_validate(_load("brief_valid.json"))
    assert brief.gender_constraint is None
    assert brief.brand_familiarity is None
    rt = AudienceBrief.model_validate(json.loads(brief.model_dump_json()))
    assert rt == brief


def test_brief_invalid_fails():
    with pytest.raises(ValidationError):
        AudienceBrief.model_validate(_load("brief_invalid.json"))


def test_personas_roundtrip():
    ps = PersonaSet.model_validate(_load("personas.json"))
    assert PersonaSet.model_validate(json.loads(ps.model_dump_json())) == ps
    with pytest.raises(ValidationError):
        PersonaSet.model_validate({"coverage_label": "coverage_panel", "personas": []})


def test_extraction_roundtrip_and_mime_rejected():
    ex = AdExtraction.model_validate(_load("extraction.json"))
    assert AdExtraction.model_validate(json.loads(ex.model_dump_json())) == ex
    # missing optional evidence remains missing, not invented
    price = next(o for o in ex.observations if o.field == "price")
    assert price.value is None and price.evidence_quote is None
    with pytest.raises(ValidationError):
        AdExtraction.model_validate({**_load("extraction.json"), "mime": "image/gif"})
    # non-unknown value without evidence fails
    bad = _load("extraction.json")
    bad["observations"][0].pop("evidence_quote")
    with pytest.raises(ValidationError):
        AdExtraction.model_validate(bad)


def test_responses_roundtrip_and_rating_bounds():
    resp = PersonaResponse.model_validate(_load("responses.json")[0])
    assert PersonaResponse.model_validate(json.loads(resp.model_dump_json())) == resp
    for bad_rating in (0, 6):
        with pytest.raises(ValidationError):
            PersonaAnswer(
                question_id="clarity",
                rating=bad_rating,
                explanation="x",
                evidence_ids=[],
            )
    # NEI distinguishable from low rating
    nei = PersonaAnswer(
        question_id="clarity", not_enough_information=True, explanation="no price shown", evidence_ids=[]
    )
    assert nei.rating is None


def test_e2_schema_variant_fixtures():
    """E2: fixtures cover text-heavy, visual-only, unknown-brand, implicit-CTA ads."""
    for name in ("extraction_text_heavy.json", "extraction_visual_only.json",
                 "extraction_unknown_brand.json", "extraction_implicit_cta.json"):
        ex = AdExtraction.model_validate(_load(name))
        assert AdExtraction.model_validate(json.loads(ex.model_dump_json())) == ex
    heavy = AdExtraction.model_validate(_load("extraction_text_heavy.json"))
    num = next(o for o in heavy.observations if o.field == "numerical_claim")
    assert num.value == "50% OFF, qualifier: Today Only"  # exact value + qualifier
    visual = AdExtraction.model_validate(_load("extraction_visual_only.json"))
    assert next(o for o in visual.observations if o.field == "brand").value is None
    assert next(o for o in visual.observations if o.field == "cta").value is None
    implicit = AdExtraction.model_validate(_load("extraction_implicit_cta.json"))
    assert next(o for o in implicit.observations if o.field == "cta").value is None
    # interpretations never leak into observations
    for name in ("extraction_text_heavy.json", "extraction_visual_only.json"):
        ex = AdExtraction.model_validate(_load(name))
        assert all(o.field not in ("tone", "symbolism", "persuasive_reason") for o in ex.observations)


def test_evaluation_result_valid_and_invalid():
    trace = EvaluationTrace(evaluation_id="e1", model="fake")
    ok = EvaluationResult(evaluation_id="e1", status="complete", trace=trace)
    assert EvaluationResult.model_validate(json.loads(ok.model_dump_json())) == ok
    with pytest.raises(ValidationError):
        EvaluationResult(evaluation_id="e1", status="definitely_complete", trace=trace)
