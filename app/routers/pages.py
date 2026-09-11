"""A2: browser pages. Same validation as the API; thin rendering only."""

from __future__ import annotations

import base64
import io
from dataclasses import replace
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

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
from app.core.models import AudienceBrief, EvaluationResult
from app.core import runs as runs_store
from app.core.runs import RunRecordError
from app.core.settings import (
    ApiKey,
    ProviderSettings,
    apply_settings,
    new_key_id,
    probe_connection,
    save_settings,
)

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


def _readiness(request: Request) -> tuple[bool, list[str]]:
    """Provider is ready iff a stored API key is active (env key is not read)."""
    settings = getattr(request.app.state, "provider_settings", None) or ProviderSettings()
    if settings.is_configured:
        return True, []
    return False, ["Provider API key"]


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
    ready, missing = _readiness(request)
    return _templates(request).TemplateResponse(request, "form.html", {
        "ready": ready, "ready_missing": missing, "nav": "evaluate",
        "form_values": {}, "field_errors": {}, "question_ids_list": QUESTION_IDS,
        "q_texts": {q.id: q.text for q in QUESTIONS.values()},
        "persona_count_default": PERSONA_COUNT, "persona_count_max": MAX_PERSONAS,
    })


def _render_form_error(request: Request, status: int, title: str, errors: dict[str, str],
                       form_values: dict, qids: list[str]):
    ready, missing = _readiness(request)
    return _templates(request).TemplateResponse(request, "form.html", {
        "ready": ready, "ready_missing": missing, "nav": "evaluate",
        "submit_error": title, "field_errors": errors, "form_values": form_values,
        "selected_questions": qids,
        "question_ids_list": QUESTION_IDS,
        "q_texts": {q.id: q.text for q in QUESTIONS.values()},
        "persona_count_default": PERSONA_COUNT, "persona_count_max": MAX_PERSONAS,
    }, status_code=status)


def _results_ctx(result, qids: list[str], thumb_uri, persona_count_fallback: int = 0) -> dict:
    """Shared report context for fresh runs and stored history (results.html)."""
    obs_ids = {o.id for o in result.extraction.observations} if result.extraction else set()
    response_map = {r.persona_id: r.answers for r in result.responses}
    response_models = {r.persona_id: r.model for r in result.responses}
    rated = [q for q in result.scores.per_question if q.mean is not None]
    highest = max(rated, key=lambda q: q.mean) if rated else None
    lowest = min(rated, key=lambda q: q.mean) if rated else None
    stance_counts: dict[str, int] = {}
    fam_counts: dict[str, int] = {}
    if result.personas:
        for p in result.personas.personas:
            stance_counts[p.stance] = stance_counts.get(p.stance, 0) + 1
            fam_counts[p.category_familiarity] = fam_counts.get(p.category_familiarity, 0) + 1
    # Debias receipt: which models actually scored, from how many vendors.
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
    return {
        "result": result,
        "status_label": STATUS_LABELS.get(result.status, (result.status, "warn"))[0],
        "status_kind": STATUS_LABELS.get(result.status, (result.status, "warn"))[1],
        "thumb_uri": thumb_uri,
        "obs_ids": obs_ids,
        "response_map": response_map,
        "response_models": response_models,
        "panel_size": len(result.personas.personas) if result.personas else persona_count_fallback,
        "highest": highest, "lowest": lowest,
        "stance_counts": stance_counts, "fam_counts": fam_counts,
        "scoring_models": scoring_models, "extraction_models": extraction_models,
        "mix_note": mix_note,
        **_display_ctx(qids),
    }


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
                                     "result": None, "ready": _readiness(request)[0],
                                     "nav": "evaluate", "form_values": keep}, status_code=502)

    ctx = {
        "error": None, "ready": _readiness(request)[0], "nav": "evaluate",
        **_results_ctx(result, qids, _thumbnail_uri(content, mime), persona_count),
    }
    runs_store.record(result, ctx["thumb_uri"])
    return tpl.TemplateResponse(request, "results.html", ctx)


# ---------------------------------------------------------------- settings

def _settings_ctx(request: Request, *, saved: bool = False,
                  probe_result: Optional[tuple] = None,
                  submit_error: Optional[str] = None,
                  field_errors: Optional[dict] = None,
                  values: Optional[dict] = None,
                  selected: Optional[list] = None,
                  pool_warning: Optional[str] = None,
                  revealed_key_id: Optional[str] = None,
                  key_form: Optional[dict] = None,
                  editing_key_id: Optional[str] = None,
                  edit_form: Optional[dict] = None) -> dict:
    from app.core.settings import (  # local: avoid import churn
        SUPPORTED_POOL_MODELS, VENDOR_NAMES, keyring_available, mask_key,
    )

    ready, missing = _readiness(request)
    cur = getattr(request.app.state, "provider_settings", None) or ProviderSettings()
    pool = cur.effective_pool()
    if values is None:
        values = {
            "model": cur.model,
            "image_model": cur.image_model,
            "timeout_s": "" if cur.timeout_s is None else str(cur.timeout_s).rstrip("0").rstrip("."),
        }
    if selected is None:
        selected = pool
    active = cur.active_key()
    active_id = active.id if active else ""
    rows = [{
        "id": k.id, "label": k.label or "(unnamed)", "masked": mask_key(k.key),
        "base_url": k.base_url, "active": k.id == active_id,
        "has_secret": bool(k.key.strip()), "source": k.secret_source,
    } for k in cur.keys]
    revealed_value = ""
    if revealed_key_id:
        revealed_value = next((k.key for k in cur.keys if k.id == revealed_key_id), "")
    return {
        "ready": ready, "ready_missing": missing, "nav": "settings",
        "saved": saved, "probe_result": probe_result,
        "submit_error": submit_error, "field_errors": field_errors or {},
        "values": values, "key_rows": rows, "active_key_id": active_id,
        "revealed_key_id": revealed_key_id or "", "revealed_key_value": revealed_value,
        "key_form": key_form or {},
        "editing_key_id": editing_key_id or "", "edit_form": edit_form or {},
        "keyring_available": keyring_available(), "keyring_enabled": cur.keyring_enabled,
        "supported_pool_models": SUPPORTED_POOL_MODELS, "vendor_names": VENDOR_NAMES,
        "selected_pool_models": selected, "pool_warning": pool_warning,
    }


def _merge_pool(checked: list[str]) -> tuple[str, Optional[str]]:
    """Dedup checkbox ids into a stored pool string, with a diversity warning."""
    from app.core.settings import pool_vendors  # local: avoid import churn

    seen: list[str] = []
    for raw in checked:
        mid = raw.strip()
        if mid and mid not in seen:
            seen.append(mid)
    vendors = pool_vendors(seen)
    warning = None
    if len(seen) >= 2 and len(vendors) == 1:
        name = seen[0].split("/")[0]
        warning = (f"Single-vendor pool ({name}): every persona is still judged inside one "
                   f"model family. Add a model from another vendor to hedge family bias.")
    elif len(seen) == 1:
        warning = ("Single-model pool: judgments carry that model's full bias. "
                   "Check at least one more box to debias.")
    return ", ".join(seen), warning


def _persist(request: Request, settings: ProviderSettings) -> None:
    save_settings(settings)
    apply_settings(settings)
    request.app.state.provider_settings = settings


def _handle_key_action(request: Request, tpl, cur: ProviderSettings, action: str,
                       key_id: str, key_label: str, key_value: str, key_base_url: str,
                       edit_label: str = "", edit_value: str = "", edit_base_url: str = ""):
    """Add / edit / activate / delete / reveal a stored key. Never stores from .env."""
    if action == "reveal_key":
        return tpl.TemplateResponse(request, "settings.html",
                                    _settings_ctx(request, revealed_key_id=key_id))
    if action == "edit_key":
        if not any(k.id == key_id for k in cur.keys):
            return tpl.TemplateResponse(request, "settings.html",
                                        _settings_ctx(request, submit_error="That key no longer exists."),
                                        status_code=422)
        return tpl.TemplateResponse(request, "settings.html",
                                    _settings_ctx(request, editing_key_id=key_id))
    if action == "add_key":
        label, value, base = key_label.strip(), key_value.strip(), key_base_url.strip()
        errs: dict[str, str] = {}
        if not label:
            errs["key_label"] = "Label is required."
        elif any(k.label.strip() == label for k in cur.keys):
            errs["key_label"] = "That label is already used."
        if not value:
            errs["key_value"] = "API key is required."
        if errs:
            return tpl.TemplateResponse(request, "settings.html",
                                        _settings_ctx(request, submit_error="Fix the highlighted fields.",
                                                      field_errors=errs,
                                                      key_form={"label": label, "base_url": base}),
                                        status_code=422)
        new_key = ApiKey(id=new_key_id(), label=label, key=value, base_url=base)
        new = replace(cur, keys=[*cur.keys, new_key],
                      active_key_id=cur.active_key_id or new_key.id)
        _persist(request, new)
        return tpl.TemplateResponse(request, "settings.html", _settings_ctx(request, saved=True))
    if not any(k.id == key_id for k in cur.keys):
        return tpl.TemplateResponse(request, "settings.html",
                                    _settings_ctx(request, submit_error="That key no longer exists."),
                                    status_code=422)
    if action == "activate_key":
        new = replace(cur, active_key_id=key_id)
    elif action == "update_key":
        label = edit_label.strip()
        errs = {}
        if not label:
            errs["edit_label"] = "Label is required."
        elif any(k.label.strip() == label for k in cur.keys if k.id != key_id):
            errs["edit_label"] = "That label is already used."
        if errs:
            return tpl.TemplateResponse(request, "settings.html",
                                        _settings_ctx(request, submit_error="Fix the highlighted fields.",
                                                      field_errors=errs, editing_key_id=key_id,
                                                      edit_form={"key_id": key_id, "label": label,
                                                                 "base_url": edit_base_url}),
                                        status_code=422)
        keys = []
        for k in cur.keys:
            if k.id == key_id:
                keys.append(replace(k, label=label, key=edit_value.strip() or k.key,
                                    base_url=edit_base_url.strip(),
                                    secret_source="keyring" if k.secret_source == "keyring"
                                    and not edit_value.strip() else "file"))
            else:
                keys.append(k)
        new = replace(cur, keys=keys)
    else:  # delete_key
        keys = [k for k in cur.keys if k.id != key_id]
        active = (cur.active_key_id if any(k.id == cur.active_key_id for k in keys)
                  else (keys[0].id if keys else ""))
        new = replace(cur, keys=keys, active_key_id=active)
    _persist(request, new)
    return tpl.TemplateResponse(request, "settings.html", _settings_ctx(request, saved=True))


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return _templates(request).TemplateResponse(
        request, "settings.html", _settings_ctx(request))


@router.post("/settings", response_class=HTMLResponse)
async def save_settings_page(
    request: Request,
    action: str = Form("save"),
    model: str = Form(""),
    image_model: str = Form(""),
    timeout_s: str = Form(""),
    key_id: str = Form(""),
    key_label: str = Form(""),
    key_value: str = Form(""),
    key_base_url: str = Form(""),
    edit_label: str = Form(""),
    edit_value: str = Form(""),
    edit_base_url: str = Form(""),
):
    tpl = _templates(request)
    cur = getattr(request.app.state, "provider_settings", None) or ProviderSettings()
    form = await request.form()

    if action == "set_storage":
        new = replace(cur, keyring_enabled="keyring_enabled" in form)
        _persist(request, new)
        return tpl.TemplateResponse(request, "settings.html", _settings_ctx(request, saved=True))

    if action in ("add_key", "activate_key", "delete_key", "reveal_key",
                  "edit_key", "update_key"):
        return _handle_key_action(request, tpl, cur, action, key_id, key_label,
                                  key_value, key_base_url,
                                  edit_label, edit_value, edit_base_url)

    checked = [str(v).strip() for v in form.getlist("pool_models") if str(v).strip()]
    merged, pool_warning = _merge_pool(checked)
    errs: dict[str, str] = {}
    timeout: Optional[float] = None
    if timeout_s.strip():
        try:
            timeout = float(timeout_s.strip())
        except ValueError:
            errs["timeout_s"] = "Timeout must be a number of seconds."
    new = replace(cur, model=model.strip(), models=merged, image_model=image_model.strip(),
                  timeout_s=None if "timeout_s" in errs else timeout)
    errs.update(new.validate())
    values = {"model": model, "image_model": image_model, "timeout_s": timeout_s}
    selected = checked
    if errs:
        return tpl.TemplateResponse(request, "settings.html",
                                    _settings_ctx(request, submit_error="Fix the highlighted fields.",
                                                  field_errors=errs, values=values,
                                                  selected=selected, pool_warning=pool_warning),
                                    status_code=422)
    if action == "test":
        active = cur.active_key()
        if not active or not active.key.strip():
            return tpl.TemplateResponse(request, "settings.html",
                                        _settings_ctx(request, submit_error="No key to test.",
                                                      field_errors={"keys": "Add and activate a key first."},
                                                      values=values, selected=selected,
                                                      pool_warning=pool_warning),
                                        status_code=422)
        ok, msg = probe_connection(active.key, active.base_url, 10.0)
        return tpl.TemplateResponse(request, "settings.html",
                                    _settings_ctx(request, probe_result=(ok, msg), values=values,
                                                  selected=selected, pool_warning=pool_warning))
    _persist(request, new)
    return tpl.TemplateResponse(request, "settings.html",
                                _settings_ctx(request, saved=True, pool_warning=pool_warning))


# ---------------------------------------------------------------- run history

@router.get("/runs", response_class=HTMLResponse)
async def runs_page(request: Request):
    ready, missing = _readiness(request)
    try:
        rows = runs_store.list_runs()
        db_error = None
    except Exception as e:
        rows, db_error = [], f"Run history unavailable ({type(e).__name__})."
    return _templates(request).TemplateResponse(request, "runs.html", {
        "ready": ready, "ready_missing": missing, "nav": "runs",
        "rows": rows, "db_error": db_error, "q_labels": QUESTION_LABELS,
        "status_labels": {k: v[0] for k, v in STATUS_LABELS.items()},
    })


@router.get("/runs/{evaluation_id}", response_class=HTMLResponse)
async def run_detail_page(request: Request, evaluation_id: str):
    tpl = _templates(request)
    ready, missing = _readiness(request)
    base = {"ready": ready, "ready_missing": missing, "nav": "runs"}
    try:
        row = runs_store.get_run(evaluation_id)
        result = EvaluationResult.model_validate(row["result"])
    except (RunRecordError, ValidationError):
        return tpl.TemplateResponse(request, "results.html",
                                    {**base, "error": "Run not found or stored in an older format.",
                                     "result": None}, status_code=404)
    ctx = {**base, "error": None,
           **_results_ctx(result, row["question_ids"], row["thumb_uri"])}
    return tpl.TemplateResponse(request, "results.html", ctx)
