"""A2: browser pages. Same validation as the API; thin rendering only."""

from __future__ import annotations

import base64
import io
import os
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.core.pipeline import (
    MAX_IMAGE_BYTES,
    MAX_PERSONAS,
    PERSONA_COUNT,
    QUESTION_IDS,
    QUESTIONS,
    BriefInvalid,
    run_pipeline,
    select_questions,
    verify_image,
)
from app.core.models import AudienceBrief

router = APIRouter(tags=["pages"])

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

THUMB_MAX_PX = 320  # bounded report thumbnail; originals are never stored


def _templates(request: Request):
    return request.app.state.templates


def _readiness() -> tuple[bool, list[str]]:
    missing = []
    if not os.getenv("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not os.getenv("ADTESTPRO_MODEL", "").strip() and not os.getenv("ADTESTPRO_MODEL", "gpt-4o-mini-2024-07-18"):
        missing.append("ADTESTPRO_MODEL")
    return (not missing), missing


def _display_ctx(qids: list[str]) -> dict:
    """Shared display maps for templates: labels, full question text."""
    return {
        "q_labels": QUESTION_LABELS,
        "q_texts": {q.id: q.text for q in QUESTIONS.values()},
        "selected_labels": [QUESTION_LABELS.get(q, q) for q in qids],
    }


def _thumbnail_uri(content: bytes, mime: str) -> Optional[str]:
    """Bounded in-memory thumbnail as a data URI. Never exposes files or paths."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content))
        img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=70)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _field_errors(form: dict) -> dict[str, str]:
    """Field-specific validation at the browser boundary (parity with client)."""
    errs: dict[str, str] = {}
    for key in ("product_description", "campaign_objective", "location", "interests", "pain_points"):
        if not str(form.get(key, "") or "").strip():
            errs[key] = "This field is required."
    try:
        amin, amax = int(form.get("age_min")), int(form.get("age_max"))
    except (TypeError, ValueError):
        errs["age_min"] = "Ages must be numbers between 13 and 100."
    else:
        if not (13 <= amin <= 100):
            errs["age_min"] = "Min age must be 13–100."
        if not (13 <= amax <= 100):
            errs["age_max"] = "Max age must be 13–100."
        if amin > amax:
            errs["age_max"] = "Max age must be ≥ min age."
    return errs


@router.get("/", response_class=HTMLResponse)
async def form_page(request: Request):
    ready, missing = _readiness()
    return _templates(request).TemplateResponse(request, "form.html", {
        "ready": ready, "ready_missing": missing, "nav": "evaluate",
        "form_values": {}, "field_errors": {}, "question_ids_list": QUESTION_IDS,
        "q_texts": {q.id: q.text for q in QUESTIONS.values()},
        "persona_count_default": PERSONA_COUNT, "persona_count_max": MAX_PERSONAS,
    })


def _render_form_error(request: Request, status: int, title: str, errors: dict[str, str],
                       form_values: dict, qids: list[str]):
    ready, missing = _readiness()
    return _templates(request).TemplateResponse(request, "form.html", {
        "ready": ready, "ready_missing": missing, "nav": "evaluate",
        "submit_error": title, "field_errors": errors, "form_values": form_values,
        "selected_questions": qids,
        "question_ids_list": QUESTION_IDS,
        "q_texts": {q.id: q.text for q in QUESTIONS.values()},
        "persona_count_default": PERSONA_COUNT, "persona_count_max": MAX_PERSONAS,
    }, status_code=status)


@router.post("/evaluate", response_class=HTMLResponse)
async def evaluate_page(
    request: Request,
    product_description: str = Form(...),
    campaign_objective: str = Form(...),
    age_min: int = Form(...),
    age_max: int = Form(...),
    location: str = Form(...),
    interests: str = Form(""),
    pain_points: str = Form(""),
    category_familiarity: str = Form("casual"),
    gender_constraint: Optional[str] = Form(None),
    price_sensitivity: Optional[str] = Form(None),
    brand_familiarity: Optional[str] = Form(None),
    persona_count: int = Form(PERSONA_COUNT),
    image: UploadFile = File(...),
):
    tpl = _templates(request)
    form = await request.form()
    # Accept repeated fields (browser checkboxes) and comma-joined strings (API parity).
    qids: list[str] = []
    for q in form.getlist("question_ids"):
        qids.extend(s.strip() for s in str(q).split(",") if s.strip())
    brief_data = {
        "product_description": product_description, "campaign_objective": campaign_objective,
        "age_min": age_min, "age_max": age_max, "location": location,
        "interests": interests, "pain_points": pain_points,
        "category_familiarity": category_familiarity,
        "gender_constraint": gender_constraint or None,
        "price_sensitivity": price_sensitivity or None,
        "brand_familiarity": brand_familiarity or None,
    }
    keep = dict(brief_data, persona_count=persona_count)

    # Boundary validation before any LLM call; values preserved on failure.
    errors = _field_errors(brief_data)
    if not (1 <= persona_count <= MAX_PERSONAS):
        errors["persona_count"] = f"Panel size must be between 1 and {MAX_PERSONAS}."
    if not qids:
        errors["question_ids"] = "Select at least one question."
    else:
        try:
            select_questions(qids)
        except BriefInvalid as e:
            errors["question_ids"] = str(e)
    if errors:
        return _render_form_error(request, 422, "Fix the highlighted fields and resubmit.",
                                  errors, keep, qids)

    content = await image.read(MAX_IMAGE_BYTES + 2)
    try:
        content, mime, checksum = verify_image(content, image.filename or "upload",
                                               image.content_type or "application/octet-stream")
    except Exception as e:
        return _render_form_error(request, 422, "The image could not be used.",
                                  {"image": str(e)}, keep, qids)

    try:
        client = getattr(request.app.state, "llm_client", None)
        result = await run_pipeline(
            brief_data=brief_data, image=content,
            filename=image.filename or "upload",
            content_type=mime,
            question_ids=qids, client=client, persona_count=persona_count,
        )
    except Exception:
        # ponytail: safe error page, never raw tracebacks outward.
        return tpl.TemplateResponse(request, "results.html",
                                    {"error": "Evaluation failed. Check inputs and retry.",
                                     "result": None, "ready": _readiness()[0],
                                     "nav": "evaluate", "form_values": keep}, status_code=502)

    obs_ids = {o.id for o in result.extraction.observations} if result.extraction else set()
    response_map = {r.persona_id: r.answers for r in result.responses}
    rated = [q for q in result.scores.per_question if q.mean is not None]
    highest = max(rated, key=lambda q: q.mean) if rated else None
    lowest = min(rated, key=lambda q: q.mean) if rated else None
    stance_counts: dict[str, int] = {}
    fam_counts: dict[str, int] = {}
    if result.personas:
        for p in result.personas.personas:
            stance_counts[p.stance] = stance_counts.get(p.stance, 0) + 1
            fam_counts[p.category_familiarity] = fam_counts.get(p.category_familiarity, 0) + 1
    ctx = {
        "error": None, "result": result, "ready": _readiness()[0], "nav": "evaluate",
        "status_label": STATUS_LABELS.get(result.status, (result.status, "warn"))[0],
        "status_kind": STATUS_LABELS.get(result.status, (result.status, "warn"))[1],
        "thumb_uri": _thumbnail_uri(content, mime),
        "obs_ids": obs_ids,
        "response_map": response_map,
        "panel_size": len(result.personas.personas) if result.personas else persona_count,
        "highest": highest, "lowest": lowest,
        "stance_counts": stance_counts, "fam_counts": fam_counts,
        **_display_ctx(qids),
    }
    return tpl.TemplateResponse(request, "results.html", ctx)
