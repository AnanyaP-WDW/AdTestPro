"""A1: one end-to-end endpoint. HTTP boundary only; no LLM logic here."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Optional

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.active import ACTIVE, consume_task_error, new_run_id
from app.core.models import EvaluationResult
from app.core.pipeline import (
    BriefInvalid,
    ImageInvalid,
    MAX_IMAGE_BYTES,
    MAX_PERSONAS,
    PERSONA_COUNT,
    normalize_kind,
    run_pipeline,
    select_questions,
)
from app.core.llm import LLMError
from app.core import runs as runs_store

router = APIRouter(prefix="/api", tags=["evaluations"])

# ponytail: in-process dict, not a DB (persistence is out of MVP scope).
# Capped because keys are client-supplied: unbounded growth is a memory DoS.
MAX_IDEMPOTENT_RESULTS = 100
_IDEMPOTENT_RESULTS: dict[str, dict] = {}


def _key(raw: Optional[str], body: bytes, fields: str) -> Optional[str]:
    if not raw:
        return None
    return hashlib.sha256(f"{raw}\n{fields}\n{len(body)}".encode()).hexdigest()


@router.post("/evaluations", response_model=EvaluationResult)
async def create_evaluation(
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
    question_ids: str = Form("attention,clarity,relevance"),
    persona_count: int = Form(PERSONA_COUNT),
    creative_kind: str = Form("image"),
    idempotency_key: Optional[str] = Form(None),
    image: UploadFile = File(...),
    x_idempotency_key: Optional[str] = Header(None),
):
    key_seed = x_idempotency_key or idempotency_key
    try:
        kind = normalize_kind(creative_kind)  # cheap check before buffering up to 15MB
    except ImageInvalid as e:
        return JSONResponse(status_code=422, content={"detail": f"invalid request: {e}"})
    content = await image.read(MAX_IMAGE_BYTES + 2)
    fields_sig = "|".join([product_description, campaign_objective, str(age_min), str(age_max),
                            location, interests, pain_points, category_familiarity,
                            question_ids or "", str(persona_count), kind])
    digest = _key(key_seed, content, fields_sig)
    if digest and digest in _IDEMPOTENT_RESULTS:
        return JSONResponse(content=_IDEMPOTENT_RESULTS[digest],
                            headers={"X-Idempotent-Replay": "true"})
    # Validate at the HTTP boundary: no LLM call on invalid input.
    brief_data = {
        "product_description": product_description, "campaign_objective": campaign_objective,
        "age_min": age_min, "age_max": age_max, "location": location,
        "interests": interests, "pain_points": pain_points,
        "category_familiarity": category_familiarity,
        "gender_constraint": gender_constraint or None,
        "price_sensitivity": price_sensitivity or None,
        "brand_familiarity": brand_familiarity or None,
    }
    try:
        qids = [q.strip() for q in (question_ids or "").split(",") if q.strip()]
        select_questions(qids)
        from app.core.pipeline import parse_brief  # boundary validation first
        parse_brief(brief_data)
    except (BriefInvalid, ValueError) as e:
        return JSONResponse(status_code=422, content={"detail": f"invalid request: {e}"})
    if not (1 <= persona_count <= MAX_PERSONAS):
        return JSONResponse(status_code=422,
                            content={"detail": f"persona_count must be between 1 and {MAX_PERSONAS}"})
    if len(content) > MAX_IMAGE_BYTES:
        return JSONResponse(status_code=422, content={"detail": "image over size limit"})

    def _busy(active) -> JSONResponse:
        return JSONResponse(status_code=409, content={
            "detail": "an evaluation is already running",
            "evaluation_id": active.evaluation_id,
            "status_url": f"/runs/{active.evaluation_id}/status",
        })

    active = ACTIVE.current()
    if active is not None:
        return _busy(active)
    eid = new_run_id()
    if not ACTIVE.claim(eid, kind=kind, panel_size=persona_count, questions=len(qids)):
        current = ACTIVE.current()
        if current is not None:
            return _busy(current)
        return JSONResponse(status_code=409, content={"detail": "another evaluation is starting"})

    client = getattr(request.app.state, "llm_client", None)

    async def _run_tracked() -> EvaluationResult:
        try:
            result = await run_pipeline(
                brief_data=brief_data, image=content,
                filename=image.filename or "upload",
                content_type=image.content_type or "application/octet-stream",
                question_ids=qids, client=client, persona_count=persona_count, kind=kind,
                evaluation_id=eid, progress=ACTIVE.update,
            )
            runs_store.record(result)  # API has no thumbnail; history detail notes it
            return result
        finally:
            ACTIVE.finish(eid)

    task = asyncio.create_task(_run_tracked())
    task.add_done_callback(consume_task_error)
    try:
        result = await asyncio.shield(task)
    except LLMError:
        # ponytail: safe mapping, no keys/prompts/stack traces outward.
        return JSONResponse(status_code=502, content={"detail": "evaluation provider unavailable"})
    body = result.model_dump(mode="json")
    if digest:
        _IDEMPOTENT_RESULTS[digest] = body
        while len(_IDEMPOTENT_RESULTS) > MAX_IDEMPOTENT_RESULTS:
            _IDEMPOTENT_RESULTS.pop(next(iter(_IDEMPOTENT_RESULTS)))
    return JSONResponse(content=body)
