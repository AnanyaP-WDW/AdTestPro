"""A2: browser pages. Same validation as the API; thin rendering only."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.core.pipeline import MAX_IMAGE_BYTES, run_pipeline

router = APIRouter(tags=["pages"])


def _templates(request: Request):
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
async def form_page(request: Request):
    return _templates(request).TemplateResponse(request, "form.html")


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
    image: UploadFile = File(...),
):
    tpl = _templates(request)
    form = await request.form()
    qids = form.getlist("question_ids") or ["attention", "clarity", "relevance"]
    content = await image.read(MAX_IMAGE_BYTES + 2)
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
        client = getattr(request.app.state, "llm_client", None)
        result = await run_pipeline(
            brief_data=brief_data, image=content,
            filename=image.filename or "upload",
            content_type=image.content_type or "application/octet-stream",
            question_ids=qids, client=client,
        )
    except Exception:
        # ponytail: safe error page, never raw tracebacks outward.
        return tpl.TemplateResponse(request, "results.html",
                                    {"error": "Evaluation failed. Check inputs and retry.",
                                     "result": None}, status_code=502)
    return tpl.TemplateResponse(request, "results.html", {"error": None, "result": result})
