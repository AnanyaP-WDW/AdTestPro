# AdTestPro — produces schema-valid, evidence-linked ad evaluations

Experimental creative-screening signal. Not a replacement for human research.
No CTR, sales, or causal-lift claims (release label per `PLAN.md` Task V3:
engineering gate only; higher claims require benchmark evidence).

## Local startup (one command)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env   # fill in OPENAI_API_KEY
uvicorn app.main:app --reload
```

Health: `GET /health` → `200 {"status": "healthy"}` (works offline).
Readiness: `GET /ready` → `{"ready": true|false}` (false with missing config names, no secrets printed).

## Tests

```bash
pytest -q
```

Offline: fixtures run the full pipeline with a fake LLM client (no network).
Live LLM calls require `OPENAI_API_KEY` + `ADTESTPRO_MODEL`.

## Docker (case-sensitive Linux safe)

```bash
docker compose up --build
curl -f http://localhost:8000/health
```

## Cost estimate (12 personas × 3 questions)

Rough order of magnitude with the default screening model (~$0.001 / 1k blended tokens):

| Stage | Calls | ≈ tokens |
|---|---|---|
| personas (+consistency) | 2 | ~8k in / ~8k out |
| extraction | 1 | image + ~2k out |
| responses | 12 | ~12×2k in / ~12×0.6k out |
| synthesize + critic | 2 | ~10k in / ~2k out |
| **Total** | **~17** | **~$0.05–0.15 / run** |

Per-run budget enforced via `ADTESTPRO_PIPELINE_TIMEOUT_S` (default 300s),
`ADTESTPRO_MAX_CONCURRENCY` (default 4), `ADTESTPRO_TIMEOUT_S` per call,
max 3 questions, max 12 personas, and capped `max_tokens` per stage.
Logs carry eval id / stage / duration / tokens / cost only — never image bytes, keys, or profiles.
