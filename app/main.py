from fastapi import FastAPI, Request, HTTPException
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="AdTestPro",
    description="Synthetic Focus Group testing for ad creatives",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
