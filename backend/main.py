# backend/main.py
"""
ELISA Platform — FastAPI application entry point.

Mounts:
    /api/v1/auth        — authentication (OTP + JWT)
    /api/v1/farms       — farm CRUD + polygon registration
    /api/v1             — predictions, weather, savings, irrigation
                          (prefixed inside each router via farm_id path param)

Lifespan:
    startup  → verify DB connection + PostGIS + ML core path
    shutdown → dispose connection pool

Run locally:
    cd backend
    uvicorn main:app --reload --port 8000

Render:
    web: cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations


import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.database import close_db, init_db

settings = get_settings()
_log     = logging.getLogger("elisa.main")

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    _log.info("=" * 56)
    _log.info("ELISA Platform starting up")
    _log.info("  env       : %s", settings.app_env)
    _log.info("  elisa2    : %s", settings.elisa2_root)
    _log.info("=" * 56)

    # Verify DB + PostGIS
    # Verify DB + PostGIS
    try:
        await init_db()
        _log.info("Database connection verified.")
    except Exception as exc:
        _log.warning("DB connection check failed (non-fatal): %s", exc)

    # Verify ML core health (non-blocking — logs warnings, doesn't abort startup)
    try:
        from services.ml_bridge import check_ml_health
        health = check_ml_health()
        _log.info("ML core health: %s", health)
        if not health["overall"]:
            _log.warning(
                "ML core not fully ready. Predictions will use ETo-decay fallback "
                "until datasets and checkpoints are present."
            )
    except Exception as exc:
        _log.warning("ML health check failed (non-fatal): %s", exc)

    # Start APScheduler daily cron
    try:
        from core.scheduler import start_scheduler
        start_scheduler()
        _log.info("Scheduler started.")
    except Exception as exc:
        _log.warning("Scheduler failed to start (non-fatal): %s", exc)

    yield  # ← app runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    _log.info("ELISA Platform shutting down.")
    try:
        from core.scheduler import scheduler
        if scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception:
        pass
    await close_db()
    _log.info("Database pool closed.")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "ELISA Platform API",
    description = (
        "Smart irrigation decision system for Western UP smallholder farmers. "
        "Jamia Millia Islamia — EE Dept B.Tech Major Project."
    ),
    version     = "2.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
    openapi_url = "/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.cors_origins,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────

from api.auth        import router as auth_router        # noqa: E402
from api.farms       import router as farms_router       # noqa: E402
from api.predictions import router as predictions_router # noqa: E402
from api.weather     import router as weather_router     # noqa: E402
from api.savings     import router as savings_router     # noqa: E402
from api.irrigation  import router as irrigation_router  # noqa: E402

PREFIX = "/api/v1"

app.include_router(auth_router,        prefix=f"{PREFIX}")
app.include_router(farms_router,       prefix=f"{PREFIX}")
app.include_router(predictions_router, prefix=f"{PREFIX}")
app.include_router(weather_router,     prefix=f"{PREFIX}")
app.include_router(savings_router,     prefix=f"{PREFIX}")
app.include_router(irrigation_router,  prefix=f"{PREFIX}")


# ── Health endpoint (used by UptimeRobot ping) ────────────────────────────────

@app.get("/health", tags=["health"], summary="Liveness check for UptimeRobot")
async def health() -> dict:
    """
    Returns 200 OK with system status.
    UptimeRobot pings this every 5 minutes to keep Render from spinning down.
    """
    try:
        from services.ml_bridge import check_ml_health
        ml = check_ml_health()
    except Exception:
        ml = {"overall": False}

    return {
        "status":         "ok",
        "env":            settings.app_env,
        "ml_core_ready":  ml.get("overall", False),
        "gee_ready":      ml.get("gee_ready", False),
        "patchtst_ready": ml.get("patchtst_checkpoint", False),
    }


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"message": "ELISA Platform API v2.0. See /docs for endpoints."}# Paste contents from the generated main.py here
