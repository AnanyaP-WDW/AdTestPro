# AdTestPro Implementation Plan

## Core Decisions
- Build on the current Python/FastAPI `v2` branch.
- Reuse concepts and prompts from `origin/main`, not its broken class hierarchy.
- Use a direct `AsyncOpenAI`-compatible client with Pydantic structured outputs.
- Do **not** use Pi as the initial backbone. Pi is a Node-centric coding-agent harness; using it from FastAPI would add subprocess/RPC lifecycle complexity without improving this deterministic workflow.
- Implement an explicit bounded pipeline, not an autonomous open-ended agent:

```text
Validate input
    → generate constrained personas
    → extract observable ad facts
    → collect independent responses
    → aggregate scores deterministically
    → synthesize themes
    → verify evidence
    → return result with uncertainty and warnings
```

- Support static PNG/JPEG creatives first. Video, persistence, long-lived persona memory, moderated group discussions, and CTR prediction remain outside the MVP.
- Position the output as an **experimental creative-screening signal**, not a replacement for human research or a prediction of sales.

## Proposed Structure

```text
app/
├── main.py
├── core/
│   ├── models.py
│   ├── llm.py
│   ├── pipeline.py
│   └── prompts/
│       ├── personas.txt
│       ├── extract_ad.txt
│       ├── respond.txt
│       └── synthesize.txt
├── templates/
│   ├── form.html
│   └── results.html
└── static/
tests/
├── fixtures/
│   ├── personas.json
│   ├── extraction.json
│   └── responses.json
└── test_pipeline.py
benchmarks/
├── personas/
├── extraction/
├── scoring/
└── evaluate.py
```

`models.py` holds application contracts, `llm.py` owns the single provider client, and `pipeline.py` owns orchestration and deterministic calculations. More layers are unnecessary until the application has multiple providers or persistence requirements.

---

# 0. Foundation

## Task F1: Make the Current Application Reproducibly Runnable ✅ DONE

**Work**
- Fix clean-checkout startup around the missing `app/static` directory.
- Correct Docker filename casing and health check.
- Add required runtime dependencies: OpenAI client and multipart form support.
- Populate `.env.sample` with model and API configuration names.
- Replace unsafe wildcard credentialed CORS with a development-safe configuration.
- Resolve paths relative to the application module rather than the working directory.
- Document local startup and test commands.

**Exit criteria**
- A clean checkout starts with one documented command.
- `GET /health` returns `200`.
- The container starts on a case-sensitive Linux filesystem.
- No API key is committed or printed.
- Startup fails with a clear error when required configuration is absent.
- An offline smoke test verifies application import and `/health`.

## Task F2: Define the Domain Contracts ✅ DONE

**Work**
- Add Pydantic models for:
  - `AudienceBrief`
  - `Persona`
  - `PersonaSet`
  - `AdObservation`
  - `AdInterpretation`
  - `AdExtraction`
  - `SurveyQuestion`
  - `PersonaAnswer`
  - `PersonaResponse`
  - `QuestionScore`
  - `ScoreSummary`
  - `EvaluationTrace`
  - `EvaluationResult`
- Use stable string IDs for personas, questions, evidence, prompts, and pipeline versions.
- Define rating as an integer from `1..5`.
- Define confidence separately as `0..100`, but do not use it as a score weight.
- Represent missing information as `null` or `unknown`; never force the model to guess.
- Include model ID, prompt version, timestamps, latency, token use, repair history, and warnings in the trace.

**Exit criteria**
- Every boundary object round-trips through JSON.
- Ratings outside `1..5` fail validation.
- Unsupported MIME types and malformed audience fields fail before an LLM call.
- Missing optional evidence remains missing rather than becoming an empty invented value.
- Tests cover one valid and one invalid fixture for each top-level result.

## Task F3: Implement a Bounded LLM Adapter ✅ DONE

**Work**
- Create one shared async client.
- Require exact model configuration rather than an unversioned alias where the provider supports it.
- Use provider-supported structured outputs mapped to Pydantic schemas.
- Centralize timeout, retry, token, and concurrency limits.
- Allow at most one structured-output repair attempt.
- Accept an injected fake client in tests without introducing a provider interface with only one implementation.
- Delimit audience text and OCR as untrusted data to reduce prompt-injection risk.

**Exit criteria**
- Recorded fixtures can run the complete pipeline without network access.
- Provider timeout and malformed output become typed application failures.
- No stage retries indefinitely.
- Every call records model, prompt version, token usage, latency, and retry count.
- Concurrent calls respect a fixed semaphore.

---

# 1. Credible Personas

## Scientific Basis

| Research | What AdTestPro should borrow | What it should not claim |
|---|---|---|
| Silicon Samples | Condition responses on explicit audience attributes and validate response distributions | A plausible persona is representative of a real population |
| 1,000 People | Rich self-report or interview grounding is stronger than demographics alone | A generated biography is equivalent to an interview-grounded digital twin |
| Generative Agents | Stable identity and memory matter in long multi-turn simulations | Memory/reflection is necessary for three independent survey questions |
| TinyTroupe | Typed persona records and reproducible population generation | Framework adoption without measuring fidelity |
| Focus Agent | Independent responses before any group synthesis | Moderator-induced consensus as evidence of accuracy |

The immediate goal is not to create vivid fictional biographies. It is to produce constrained, auditable respondent profiles whose answers measurably depend on supplied audience evidence.

## Task P1: Expand and Validate the Audience Brief ✅ DONE

**Work**
- Wire the current form into `AudienceBrief`.
- Capture:
  - product or service description;
  - campaign objective;
  - age range;
  - location;
  - interests;
  - pain points;
  - category familiarity;
  - optional gender constraints;
  - optional price sensitivity;
  - optional brand familiarity;
- Normalize lists and reject impossible age ranges.
- Mark each field as user-supplied evidence.
- Keep optional fields optional instead of inventing defaults.

**Exit criteria**
- Browser and server enforce the same required fields.
- The server rejects invalid ranges, oversized fields, and unsupported values.
- The serialized brief clearly distinguishes supplied facts from missing data.
- No persona-generation prompt contains fields the form did not supply.

## Task P2: Define an Evidence-Aware Persona Schema ✅ DONE

**Work**
- Give each persona:
  - stable ID;
  - audience segment label;
  - constrained demographics;
  - relevant needs and pain points;
  - category and brand familiarity;
  - price sensitivity;
  - media or shopping habits;
  - decision criteria;
  - communication style;
  - supplied facts;
  - inferred hypotheses;
  - uncertainty notes.
- Require every inferred field to include a short basis.
- Exclude decorative facts such as pets, favorite restaurants, or detailed occupations unless relevant to the advertised category.
- Do not infer sensitive attributes.

**Exit criteria**
- Every persona satisfies hard audience constraints.
- Every non-supplied behavioral attribute is labeled as inferred.
- No sensitive attribute is inferred from demographics, location, or imagery.
- A reviewer can identify exactly which persona facts came from the user.
- Personas remain useful when names and prose styling are removed.

## Task P3: Generate a Coverage-Oriented Persona Set ✅ DONE

**Work**
- Generate a default panel of 12 personas.
- Construct a small coverage matrix in Python before generation:
  - pain-point emphasis;
  - interest emphasis;
  - category familiarity;
  - price sensitivity, when supplied;
  - skeptical versus receptive stance.
- Ask the model to fill the constrained slots rather than merely requesting “12 diverse people.”
- Generate all persona records with low temperature and stable ordering.
- Detect duplicate or near-identical personas by normalized field overlap.
- Do not assign population weights unless the user supplies or imports a distribution.

**Exit criteria**
- All requested pain points and interests appear in the coverage matrix.
- No two personas are identical across segment, needs, familiarity, and decision criteria.
- Hard constraints have 100% compliance.
- Re-running cached responses produces byte-identical persona records.
- A generated panel without supplied weights is labeled “coverage panel,” not “representative sample.”

## Task P4: Check Persona Consistency Before Scoring ✅ DONE

**Work**
- Run deterministic validations first:
  - age and location constraints;
  - required coverage;
  - duplicate IDs;
  - duplicate personas;
  - unsupported sensitive claims.
- Use one bounded LLM check only for semantic contradictions not expressible in code.
- Permit one correction pass.
- Mark the run invalid rather than repeatedly regenerating until it looks convincing.

**Exit criteria**
- Invalid personas never enter scoring.
- The consistency checker reports field-level failures.
- One correction pass either produces a valid persona set or terminates with `persona_invalid`.
- Tests include contradictory, duplicated, and stereotype-leaking fixtures.

## Task P5: Build `PersonaBench-MVP` 🟡 SCAFFOLD DONE — human data BLOCKED (see benchmarks/README.md)

**Work**
- Recruit approximately 30 consenting participants from the initial target market.
- Collect a short structured profile, ratings for 12 ads, hidden duplicate questions, and a small 7–14 day retest.
- Build three conditions:
  - grounded persona;
  - demographics-only persona;
  - shuffled-profile control.
- Keep held-out ratings out of prompts.
- Measure:
  - profile-fact accuracy;
  - contradiction rate;
  - rating MAE and Spearman correlation;
  - aggregate mean bias;
  - synthetic-to-human variance ratio;
  - grounded improvement over shuffled controls;
  - unsupported demographic claims.

**Exit criteria**
- Hard profile fidelity is at least 95%.
- Contradiction rate is no more than 5%.
- Grounded personas improve over shuffled profiles by at least `0.10` Spearman or 10% MAE.
- Synthetic/human variance ratio is between `0.70` and `1.30`.
- Unsupported demographic explanation rate is no more than 2%.
- If grounded and shuffled personas perform similarly, stop claiming personalization and use audience-level generic panels only.

---

# 2. Structured Extract

## Scientific Basis

| Research | AdTestPro application |
|---|---|
| Pitt Ads | Separate objects, topic, sentiment, intended action, persuasive reason, and symbolism |
| Persuasion Strategies | Use an explicit multilabel persuasion taxonomy |
| TRADE | Add adversarial tests that distinguish genuine ad reasoning from visual grounding shortcuts |
| ADVI-SOR | Build brand-aware criteria from observable evidence, but validate them before using them for ranking |

The extraction must distinguish **what is visible** from **what the model thinks it means**.

## Task E1: Secure the Image Boundary ✅ DONE

**Work**
- Accept only JPEG and PNG for the MVP.
- Enforce size limits server-side.
- Verify MIME type and decoded media rather than trusting filename extensions.
- Strip or ignore unsafe filenames.
- Compute a media checksum.
- Keep image bytes in memory for the request; do not persist uploads yet.
- Return a safe error for malformed or unsupported media.

**Exit criteria**
- Renamed non-image files are rejected.
- Oversized files are rejected before an LLM call.
- Supported images produce a checksum and verified MIME type.
- No user-controlled filename becomes a filesystem path.
- Tests cover valid PNG/JPEG, malformed content, MIME mismatch, and oversized input.

## Task E2: Define the Extraction Schema ✅ DONE

**Work**
- Separate `observations` from `interpretations`.
- Capture observations:
  - visible text;
  - brand and logo;
  - product or service;
  - explicit numerical claims;
  - CTA;
  - subjects and actions;
  - colors and visual hierarchy;
  - legibility;
  - evidence quote and coarse image region.
- Capture interpretations:
  - tone;
  - intended audience cues;
  - persuasive reason;
  - persuasion strategies;
  - symbolism;
  - likely attention drivers.
- Give every assertion an evidence ID and confidence.
- Require `unknown` when the evidence does not support an answer.
- Do not represent inferred target audience as an observable fact.

**Exit criteria**
- Every non-unknown observation has evidence.
- Numerical claims preserve exact value and qualifier.
- Interpretations never appear in the observations collection.
- Missing logo, CTA, price, or brand remains explicitly absent.
- Schema fixtures cover text-heavy, visual-only, unknown-brand, and implicit-CTA ads.

## Task E3: Implement One Multimodal Extraction Call ✅ DONE

**Work**
- Replace the former three-image-call design with one structured multimodal request.
- Send the image once and return one typed `AdExtraction`.
- Use low temperature.
- Validate evidence references after parsing.
- Permit one repair for schema or evidence-reference errors.
- Do not ask for hidden chain-of-thought.
- Store a short result explanation, not internal reasoning.

**Exit criteria**
- One supported image causes one primary multimodal call.
- The response validates directly into `AdExtraction`.
- Invalid evidence IDs cause one repair and then a typed failure.
- Adversarial text inside the image cannot change system instructions in the fixture tests.
- Extraction failures do not proceed to persona scoring.

## Task E4: Add Persuasion Classification ✅ DONE

**Work**
- Start with a small documented taxonomy:
  - emotional appeal;
  - logical evidence;
  - authority;
  - social proof;
  - scarcity or urgency;
  - value or price;
  - identity or aspiration;
  - humor;
  - fear or loss avoidance.
- Treat classification as multilabel.
- Require evidence for every selected strategy.
- Permit `other` and `unclear`.
- Avoid category-specific taxonomies until benchmark errors justify them.

**Exit criteria**
- Multiple strategies can coexist.
- Every selected strategy references visible text or imagery.
- Unsupported strategies are rejected during validation.
- The taxonomy and examples are documented in the prompt and benchmark rubric.
- Rare labels are reported separately rather than hidden by overall accuracy.

## Task E5: Build `AdExtract-60` 🟡 SCAFFOLD DONE — annotation BLOCKED (see benchmarks/README.md)

**Work**
- Assemble 60 legally usable static ad images balanced across:
  - text density;
  - known and unknown brands;
  - explicit and implicit CTA;
  - literal and symbolic messages;
  - persuasion strategies.
- Have two humans independently annotate observations and interpretations.
- Adjudicate disagreements.
- Add controlled variants:
  - logo removed;
  - CTA removed;
  - price changed;
  - decorative object added;
  - text made unreadable.
- Measure OCR error, core-field F1, persuasion macro-F1, unsupported-assertion rate, and perturbation behavior.

**Exit criteria**
- Human categorical agreement reaches at least `κ = 0.60`.
- Core brand/product/CTA micro-F1 reaches at least `0.90`.
- Explicit-claim F1 reaches at least `0.85`.
- Persuasion macro-F1 reaches at least `0.65`.
- Unsupported assertions remain below 3%.
- Price, percentage, health, and legal-claim hallucinations are zero.
- At least 90% of unrelated fields remain stable across controlled variants.
- If observable fields pass but interpretations fail, ship interpretations as experimental.

---

# 3. Stable Scoring

## Scientific Basis

The LLM should not create the final number. It should produce independent evidence-grounded judgments; Python should calculate the aggregate.

Focus Agent supports moderated synthesis for theme discovery, but not necessarily better quantitative prediction. The moderator therefore remains optional until it beats simpler scoring on held-out human data.

## Task S1: Define Stable Questions and Rubrics ✅ DONE

**Work**
- Replace `q1`–`q5` with stable IDs:
  - `attention`
  - `clarity`
  - `relevance`
  - `credibility`
  - `action_intent`
- Define behavioral anchors for every point on the `1..5` scale.
- Keep a maximum of three selected questions in the UI for cost control.
- Include `not_enough_information`.
- Keep rating, explanation, evidence, and model confidence separate.

**Exit criteria**
- Every question has an unambiguous rubric.
- Question IDs remain stable across API and UI.
- A model cannot submit a rating outside `1..5`.
- `not_enough_information` remains distinguishable from a low rating.
- Tests verify all rubric boundaries.

## Task S2: Collect Independent Persona Responses ✅ DONE

**Work**
- Give each persona:
  - its own validated profile;
  - the same validated extraction;
  - selected rubrics;
  - explicit instruction not to infer missing ad details.
- Run responses independently and concurrently with a fixed limit.
- Do not expose other persona responses.
- Require each answer to cite extraction evidence IDs.
- Use low temperature and exact model configuration.
- Do not add persona memory or group conversation for the initial scoring pass.

**Exit criteria**
- Every response belongs to exactly one persona and question.
- Every rationale cites valid extraction evidence or declares insufficient information.
- No answer invents a feature absent from the extraction fixture.
- A partial model failure produces a visible incomplete-panel warning.
- The pipeline enforces a minimum valid response count before aggregation.

## Task S3: Aggregate Scores Deterministically ✅ DONE

**Work**
- Calculate in Python:
  - count;
  - arithmetic mean;
  - median;
  - standard deviation;
  - score distribution;
  - disagreement flag;
  - per-question and overall results.
- Keep the overall score as a documented unweighted mean initially.
- Do not confidence-weight scores until confidence is calibrated.
- Do not suppress minority or negative responses.
- Label intervals as synthetic-panel dispersion, not population confidence intervals.

**Exit criteria**
- Cached responses always produce byte-identical aggregates.
- Hand-calculated fixtures match the implementation exactly.
- Missing ratings are excluded and reported, never treated as zero.
- High disagreement widens the displayed range and sets a warning.
- No LLM call can modify numeric aggregates.

## Task S4: Add Theme Synthesis and One Evidence Critic ✅ DONE

**Work**
- Ask a synthesis call to:
  - group recurring reasons;
  - identify minority views;
  - report positive and negative themes;
  - suggest evidence-linked creative changes.
- Prohibit synthesis from changing scores.
- Run one critic pass checking:
  - unsupported claims;
  - invalid evidence;
  - arithmetic mismatch;
  - persona-response contradiction;
  - demographic stereotyping.
- Permit one correction pass for textual output only.
- Keep the moderator discussion out of the MVP unless benchmarked.

**Exit criteria**
- Every reported theme links to persona responses and ad evidence.
- Minority views remain visible.
- Numeric scores before and after synthesis are identical.
- The critic cannot persuade personas to converge.
- A failed critic returns `complete_with_warnings` or `insufficient_evidence`, not silently repaired certainty.

## Task S5: Define the Bounded Execution Loop ✅ DONE

**Work**
- Use explicit states:

```text
RECEIVED
→ VALIDATED
→ PERSONAS_READY
→ EXTRACTION_READY
→ RESPONSES_READY
→ AGGREGATED
→ REVIEWED
→ COMPLETE
```

- Give each LLM stage one repair attempt.
- Cap persona calls, tokens, cost, and total wall-clock time.
- Support terminal outcomes:
  - `complete`
  - `complete_high_disagreement`
  - `insufficient_evidence`
  - `persona_invalid`
  - `extraction_invalid`
  - `budget_exhausted`
  - `pipeline_error`
- Never continue merely to force consensus.

**Exit criteria**
- Every execution ends in a documented terminal state.
- No stage can loop indefinitely.
- Cancellation propagates to outstanding async calls.
- Budget exhaustion returns partial trace data safely.
- State-transition tests reject invalid transitions.

## Task S6: Build `AdScore-24` 🟡 SCAFFOLD DONE — human ratings BLOCKED (see benchmarks/README.md)

**Work**
- Use 24 held-out ads with approximately 15 human ratings each.
- Include matched creative pairs and deliberately degraded variants.
- Collect human ratings using the same five dimensions.
- Record hidden duplicate ratings to measure human reliability.
- Compare:
  - grand-mean baseline;
  - simple extraction-rule baseline;
  - direct VLM rating without personas;
  - independent persona panel;
  - persona panel plus synthesis/critic.
- Measure correlation, MAE, pairwise accuracy, stability, and sensitivity to degraded variants.

**Exit criteria**
- Overall Spearman correlation with human means is at least `0.50`.
- Median dimension-level Spearman is at least `0.40`.
- MAE is no more than `0.75` on the five-point scale.
- Matched-pair accuracy is at least 70%.
- At least 80% of degraded variants move in the expected direction.
- Across five fresh runs, per-ad SD is no more than `0.20`.
- Rank correlation between repeated runs is at least `0.90`.
- The full loop must improve over direct scoring by at least `0.05` Spearman or 10% MAE.
- If synthesis/critic does not beat independent scoring, remove it from the scoring path.

---

# 4. API and User Experience

## Task A1: Implement One End-to-End Endpoint ✅ DONE

**Work**
- Add `POST /api/evaluations` using multipart form data.
- Validate form and image at the HTTP boundary.
- Invoke the pipeline without embedding LLM logic in route handlers.
- Return `EvaluationResult` as typed JSON.
- Map external provider failures to safe client responses.
- Generate or accept an idempotency key to prevent accidental duplicate runs.

**Exit criteria**
- One request executes the complete fake-client pipeline in tests.
- Invalid inputs cause no LLM calls.
- Provider errors do not expose keys, raw prompts, or stack traces.
- Duplicate idempotent requests do not start duplicate evaluations within the process.
- API documentation exposes the exact request and response contracts.

## Task A2: Wire the Existing Form and Results Page ✅ DONE

**Work**
- Add valid `method`, `action`, `enctype`, and field names.
- Render the form from `GET /`.
- Preserve accessible labels and keyboard behavior.
- Display:
  - audience constraints;
  - generated coverage personas;
  - structured extraction;
  - dimension scores;
  - dispersion and disagreement;
  - positive, negative, and minority themes;
  - evidence-linked recommendations;
  - experimental-use disclaimer.
- Make desktop and mobile layouts usable.

**Exit criteria**
- A user can upload and evaluate an ad without manually calling the API.
- Browser and server validation agree.
- Loading, error, empty, partial, and high-disagreement states render clearly.
- Scores are not displayed without their scale and sample count.
- Warnings and limitations are visible rather than buried.

## Task A3: Add Operational Observability ✅ DONE

**Work**
- Log evaluation ID, stage, duration, status, model, tokens, and estimated cost.
- Do not log image bytes, API keys, or full personal profiles by default.
- Add stage-level timeout and cancellation.
- Expose readiness separately from basic liveness if configuration validation requires it.
- Document cost estimates for 12 personas and three questions.

**Exit criteria**
- A failed run can be localized to one pipeline stage from logs.
- Token and latency totals equal the sum of stage calls.
- Logs contain no secrets or uploaded media.
- A disconnected or timed-out request cancels pending work.
- A declared per-run budget is enforced.

---

# 5. Scientific Release Gates

## Task V1: Freeze an End-to-End Holdout 🟡 MANIFEST READY — run BLOCKED on P5/E5/S6

**Work**
- Select 12 unseen ads after prompts and thresholds are fixed.
- Include difficult implicit-message and numerical-claim cases.
- Keep holdout annotations and human scores outside prompts.
- Run the release candidate once.
- Publish item-level metrics, not only aggregate results.

**Exit criteria**
- Persona, extraction, and scoring gates pass without holdout tuning.
- Any failed safety-sensitive claim blocks release.
- Prompt changes after a holdout failure create a new benchmark version.
- The holdout cannot be repeatedly queried until it passes.

## Task V2: Add Reproducibility Metadata ✅ DONE

**Work**
- Record:
  - media checksum;
  - benchmark version;
  - prompt hashes;
  - exact model ID;
  - model parameters;
  - persona ordering;
  - code revision;
  - schema and scoring versions;
  - raw structured responses;
  - retry history;
  - tokens, cost, and latency.
- Add cached replay and fresh replay commands.

**Exit criteria**
- Cached replay is bit-for-bit deterministic.
- Five fresh runs satisfy scoring stability thresholds.
- Persona-order randomization changes aggregate scores by no more than `0.15`.
- Another clean checkout reproduces benchmark metrics within documented tolerance.

## Task V3: Establish Claim-Safe Release Labels ✅ DONE (engineering-only label applied)

| Passed gates | Allowed description |
|---|---|
| Engineering only | “Produces schema-valid, evidence-linked ad evaluations” |
| Extraction benchmark | “Extracts tested ad attributes with published benchmark accuracy” |
| Persona and scoring benchmarks | “Provides an experimental audience-level creative-screening signal on tested categories” |
| Prospective campaign experiment | Only then discuss CTR, conversion, or ROAS prediction |

**Exit criteria**
- README and UI claims match the highest passed gate.
- The product never says “replaces focus groups.”
- No CTR, sales, or causal-lift claim appears without prospective campaign evidence.
- Unsupported geographies, categories, and languages are identified.

---

# Execution Order

1. `F1-F3`: runnable app, contracts, bounded provider.
2. `P1-P4`: engineering-correct coverage personas.
3. `E1-E4`: evidence-grounded static-image extraction.
4. `S1-S5`: independent responses and deterministic scoring.
5. `A1-A3`: API, UI, and observability.
6. `P5`, `E5`, `S6`: human and annotation benchmarks.
7. `V1-V3`: frozen holdout and claim-safe release.

Each implementation task should follow the same agent loop:

```text
Inspect affected flow
→ implement the smallest complete change
→ run the focused offline check
→ run the full existing suite
→ inspect diff for unrelated changes
→ record measured exit criteria
→ stop only when criteria pass or report a named blocker
```

No task exits on “the output looks plausible.”

# Pi Decision

Do not use Pi initially. This pipeline is a bounded state machine with typed stages, not an open-ended coding agent. A direct Python client is smaller, safer, and easier to test inside FastAPI.

Reconsider Pi as an isolated service only if AdTestPro later needs long-lived exploratory sessions, dynamic tools, user-installed skills, provider-wide normalization, branching, or steering. At that point, expose narrow ad-analysis tools and disable filesystem/shell coding tools.

Skipped from the MVP: database persistence, video, group discussion, persona memory, confidence-weighted scores, national representativeness, and campaign-performance prediction. Add each only when a measured requirement or benchmark shows the simpler pipeline is insufficient.
