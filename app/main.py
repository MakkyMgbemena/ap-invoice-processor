"""
app.main
--------
FastAPI application entry point for the OCR Invoice Processor.

Mounts all routers, configures middleware, and exposes
a /health endpoint for Cloud Run health checks.

Sources:
- FastAPI documentation:
  https://fastapi.tiangolo.com/
- Uvicorn ASGI server:
  https://www.uvicorn.org/
- FastAPI CORS middleware:
  https://fastapi.tiangolo.com/tutorial/cors/
"""

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, __description__
from app.config import init_dirs, validate_config
from app.config import API_HOST, API_PORT, DEBUG
from app.routes import all_routers

logger = logging.getLogger(__name__)

# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="OCR Invoice Processor",
    description=__description__,
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten to specific origins in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──────────────────────────────────────────────────────────
for router in all_routers:
    app.include_router(router)

logger.info(f"[App] Registered routers: {[r.prefix for r in all_routers]}")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Lightweight health check used by Cloud Run and load balancers.
    Returns 200 OK with version info when the app is running.
    """
    return {
        "status":  "healthy",
        "version": __version__,
        "service": "ocr-invoice-processor",
    }

@app.on_event("startup")
async def startup_event():
    validate_config()
    init_dirs()

# ── Dev entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    validate_config()
    init_dirs()
    uvicorn.run(
        "app.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=DEBUG,
        log_level="info",
    )
