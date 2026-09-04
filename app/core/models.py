"""Application contracts (F2). All boundary objects round-trip through JSON."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Stable version strings for prompts / pipeline / schemas.
PIPELINE_VERSION = "v0.1.0"
SCHEMA_VERSION = "v0.1.0"
PROMPT_VERSIONS = {
    "personas": "personas-v1",
    "extract_ad": "extract_ad-v1",
    "respond": "respond-v1",
    "synthesize": "synthesize-v1",
    "consistency": "consistency-v1",
    "critic": "critic-v1",
}

Rating = Annotated[int, Field(ge=1, le=5)]
Confidence = Annotated[int, Field(ge=0, le=100)]

SupportedImageMime = Literal["image/jpeg", "image/png"]

QuestionId = Literal["attention", "clarity", "relevance", "credibility", "action_intent"]

PersuasionStrategy = Literal[
    "emotional_appeal",
    "logical_evidence",
    "authority",
    "social_proof",
    "scarcity_urgency",
    "value_price",
    "identity_aspiration",
    "humor",
    "fear_loss_avoidance",
    "other",
    "unclear",
]

TerminalStatus = Literal[
    "complete",
    "complete_with_warnings",
    "complete_high_disagreement",
    "insufficient_evidence",
    "persona_invalid",
    "extraction_invalid",
    "budget_exhausted",
    "pipeline_error",
]

UNKNOWN = "unknown"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _nonempty_str_list(v: Optional[list[str]], *, max_items: int, max_len: int, name: str) -> list[str]:
    items = [s.strip() for s in (v or []) if s and s.strip()]
    if len(items) > max_items:
        raise ValueError(f"{name}: at most {max_items} items")
    for s in items:
        if len(s) > max_len:
            raise ValueError(f"{name}: item over {max_len} chars")
    # normalize: dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


class AudienceBrief(BaseModel):
    """User-supplied evidence. Optional fields stay None (missing), never invented."""

    product_description: str = Field(min_length=1, max_length=2000)
    campaign_objective: str = Field(min_length=1, max_length=1000)
    age_min: int = Field(ge=13, le=100)
    age_max: int = Field(ge=13, le=100)
    location: str = Field(min_length=1, max_length=200)
    interests: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    category_familiarity: Literal["new", "casual", "regular", "expert"] = "casual"
    gender_constraint: Optional[str] = Field(default=None, max_length=100)
    price_sensitivity: Optional[Literal["low", "medium", "high"]] = None
    brand_familiarity: Optional[Literal["unaware", "aware", "customer", "loyal"]] = None

    @model_validator(mode="after")
    def _check_ranges(self):
        if self.age_min > self.age_max:
            raise ValueError("age_min must be <= age_max")
        return self

    @field_validator("interests", "pain_points", mode="before")
    @classmethod
    def _normalize_lists(cls, v):
        if isinstance(v, str):  # accept comma-separated form input
            v = [p.strip() for p in v.split(",")]
        return _nonempty_str_list(v, max_items=20, max_len=200, name="list field")

    @field_validator("product_description", "campaign_objective", "location", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class InferredAttribute(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    basis: str = Field(min_length=1, max_length=500)


class PersonaDemographics(BaseModel):
    """Constrained demographics only. No sensitive attributes by construction."""

    age: int = Field(ge=13, le=100)
    location: str = Field(min_length=1, max_length=200)
    gender: Optional[str] = Field(default=None, max_length=100)


class Persona(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    segment: str = Field(min_length=1, max_length=200)
    demographics: PersonaDemographics
    needs: list[str] = Field(default_factory=list)
    pain_emphasis: str = Field(min_length=1, max_length=500)
    interest_emphasis: str = Field(min_length=1, max_length=500)
    category_familiarity: Literal["new", "casual", "regular", "expert"] = "casual"
    price_sensitivity: Optional[Literal["low", "medium", "high"]] = None
    brand_familiarity: Optional[Literal["unaware", "aware", "customer", "loyal"]] = None
    media_habits: str = Field(default="", max_length=500)
    decision_criteria: list[str] = Field(default_factory=list)
    communication_style: str = Field(default="", max_length=300)
    stance: Literal["skeptical", "neutral", "receptive"] = "neutral"
    supplied_facts: list[str] = Field(default_factory=list)  # came from the user
    inferred_hypotheses: list[InferredAttribute] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class PersonaSet(BaseModel):
    personas: list[Persona] = Field(min_length=1, max_length=24)
    coverage_label: Literal["coverage_panel", "representative_sample"] = "coverage_panel"

    @field_validator("personas", mode="after")
    @classmethod
    def _unique_ids(cls, v: list[Persona]):
        ids = [p.id for p in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate persona ids")
        return v


class AdObservation(BaseModel):
    """What is visible. Non-unknown values require evidence."""

    id: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=100)
    value: Optional[str] = Field(default=None, max_length=2000)
    evidence_quote: Optional[str] = Field(default=None, max_length=1000)
    region: Optional[str] = Field(default=None, max_length=100)  # coarse, e.g. top-left
    confidence: Confidence = 50

    @model_validator(mode="after")
    def _evidence_required(self):
        if self.value not in (None, "", UNKNOWN) and not self.evidence_quote:
            raise ValueError(f"observation {self.id}: non-unknown value requires evidence_quote")
        return self


class AdInterpretation(BaseModel):
    """What the model thinks it means. Never stored in observations."""

    id: str = Field(min_length=1, max_length=64)
    aspect: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = 50


class AdExtraction(BaseModel):
    observations: list[AdObservation] = Field(min_length=1)
    interpretations: list[AdInterpretation] = Field(default_factory=list)
    persuasion_strategies: list[PersuasionStrategy] = Field(default_factory=list)
    media_checksum: str = Field(min_length=8, max_length=128)
    mime: SupportedImageMime

    @field_validator("observations", mode="after")
    @classmethod
    def _unique_obs_ids(cls, v: list[AdObservation]):
        ids = [o.id for o in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate observation ids")
        return v

    @model_validator(mode="after")
    def _evidence_refs_valid(self):
        known = {o.id for o in self.observations}
        for interp in self.interpretations:
            for eid in interp.evidence_ids:
                if eid not in known:
                    raise ValueError(f"interpretation {interp.id}: unknown evidence id {eid}")
        return self


class SurveyQuestion(BaseModel):
    id: QuestionId
    text: str = Field(min_length=1, max_length=500)
    rubric: dict[int, str]  # behavioral anchor per point 1..5
    allow_nei: bool = True

    @field_validator("rubric", mode="after")
    @classmethod
    def _full_rubric(cls, v: dict[int, str]):
        if set(v.keys()) != {1, 2, 3, 4, 5}:
            raise ValueError("rubric must define anchors for 1..5")
        return v


class PersonaAnswer(BaseModel):
    question_id: QuestionId
    rating: Optional[Rating] = None
    not_enough_information: bool = False
    explanation: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = 50

    @model_validator(mode="after")
    def _rating_or_nei(self):
        # NEI is distinguishable from a low rating.
        if self.not_enough_information and self.rating is not None:
            raise ValueError("not_enough_information answers must not carry a rating")
        if not self.not_enough_information and self.rating is None:
            raise ValueError("rating required unless not_enough_information")
        return self


class PersonaResponse(BaseModel):
    persona_id: str = Field(min_length=1, max_length=64)
    answers: list[PersonaAnswer] = Field(min_length=1)

    @field_validator("answers", mode="after")
    @classmethod
    def _unique_questions(cls, v: list[PersonaAnswer]):
        ids = [a.question_id for a in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate answers for a question")
        return v


class QuestionScore(BaseModel):
    question_id: QuestionId
    count: int = Field(ge=0)
    mean: Optional[float] = None
    median: Optional[float] = None
    stdev: Optional[float] = None
    distribution: dict[int, int] = Field(default_factory=dict)
    disagreement: bool = False


class ScoreSummary(BaseModel):
    per_question: list[QuestionScore] = Field(default_factory=list)
    overall_mean: Optional[float] = None
    valid_responses: int = 0
    missing_responses: int = 0


class Theme(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    sentiment: Literal["positive", "negative", "mixed", "minority"] = "mixed"
    persona_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=2000)


class CallRecord(BaseModel):
    stage: str
    model: str
    prompt_version: str
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0
    timestamp: datetime = Field(default_factory=_utcnow)


class EvaluationTrace(BaseModel):
    evaluation_id: str
    pipeline_version: str = PIPELINE_VERSION
    schema_version: str = SCHEMA_VERSION
    model: str
    prompt_versions: dict[str, str] = Field(default_factory=lambda: dict(PROMPT_VERSIONS))
    prompt_hashes: dict[str, str] = Field(default_factory=dict)
    code_revision: str = "unknown"
    states: list[str] = Field(default_factory=list)
    calls: list[CallRecord] = Field(default_factory=list)
    repairs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None


class EvaluationResult(BaseModel):
    evaluation_id: str
    status: TerminalStatus
    brief: Optional[AudienceBrief] = None
    personas: Optional[PersonaSet] = None
    extraction: Optional[AdExtraction] = None
    responses: list[PersonaResponse] = Field(default_factory=list)
    scores: ScoreSummary = Field(default_factory=ScoreSummary)
    themes: list[Theme] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    trace: EvaluationTrace
