from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Ensure static dir exists so clean checkouts mount safely.
(BASE_DIR / "static").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "templates").mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="AdTestPro",
    description="Experimental creative-screening signal (not a replacement for human research).",
    version="2.0.0",
)


def _cors_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return [o.strip() for o in raw.split(",") if o.strip()]


_origins = _cors_origins()
# ponytail: wildcard + credentials is unsafe; drop credentials when wildcard is used.
_allow_credentials = "*" not in _origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

from app.routers.evaluations import router as evaluations_router  # noqa: E402
from app.routers.pages import router as pages_router  # noqa: E402

app.include_router(evaluations_router)
app.include_router(pages_router)
app.state.templates = templates


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/ready")
def readiness_check():
    # Fails with a clear error when required config is absent; /health stays offline-safe.
    missing = []
    if not os.getenv("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not os.getenv("ADTESTPRO_MODEL", "gpt-4o-mini-2024-07-18"):
        missing.append("ADTESTPRO_MODEL")
    if missing:
        return {"ready": False, "missing": missing}
    return {"ready": True, "model": os.getenv("ADTESTPRO_MODEL", "gpt-4o-mini-2024-07-18")}
