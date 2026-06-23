"""FastAPI app — AI Job Counselor."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from api.routes.consult import router as consult_router
from config.llm import default_chat_model, is_llm_available, list_available_models
from config.logging import setup_logging
from config.settings import settings

STATIC_DIR = Path(__file__).resolve().parent / "static"

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Job Counselor", version="1.0.0")
app.include_router(consult_router, prefix="/api")


class ApiTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = settings.webui_api_token.strip()
        if not token:
            return await call_next(request)

        path = request.url.path
        if path in {"/", "/api/health", "/api/models"} or path.startswith("/static/"):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if auth == f"Bearer {token}":
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


app.add_middleware(ApiTokenMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/health")
def health() -> dict:
    llm_ok = is_llm_available()
    model_info = list_available_models()
    return {
        "status": "ok" if llm_ok else "degraded",
        "ok": True,
        "default_model": default_chat_model(),
        "default_model_available": model_info.get("default_available", False),
        "checks": {
            "llm": {"ok": llm_ok},
            "ollama": {
                "ok": model_info.get("reachable", False),
                "model_count": len(model_info.get("models", [])),
            },
        },
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
