# Paste contents from the generated core/scheduler.py here
# backend/core/scheduler.py
"""
APScheduler daily cron — runs at 05:00 IST every day.

For every active farm:
    1. Run PatchTST + MPC via ml_bridge.get_prediction()
    2. Upsert result into predictions table
    3. If irrigate=True and user.whatsapp_opt_in=True → send WhatsApp alert
    4. Recompute savings_log for the current season

Why 05:00 IST:
    - Farmers check phones between 06:00–07:00 before heading to fields.
    - OpenMeteo forecast is freshest after the 00:00 UTC (05:30 IST) model run.
    - Avoids Render free-tier cold-start at 06:00 when farmers actually check.

Error isolation:
    Each farm's job is wrapped in try/except so one failing farm
    (missing data, network error) doesn't abort the remaining farms.
    Errors are logged individually.
"""

from __future__ import annotations

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

_log      = logging.getLogger("elisa.scheduler")
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def daily_prediction_job() -> None:
    """
    Main daily job. Called at 05:00 IST.
    Order of operations:
      1. Extend dataset with fresh NASA POWER weather   ← NEW
      2. Run predictions for every active farm
      3. Send WhatsApp alerts
      4. Recompute savings
      5. Upload farm states back to Drive               ← NEW
    Imports are deferred inside the function to avoid circular import
    at module load time (scheduler is imported by main.py during startup).
    """
    from sqlalchemy import select

    from core.database import get_db_context
    from db_models.farm import Farm
    from db_models.prediction import Prediction
    from db_models.user import User
    from services.ml_bridge import get_prediction, get_rain_forecast
    from services.savings_engine import compute_savings, current_season
    from services.whatsapp import (
        WhatsAppDeliveryError,
        build_alert_payload_from_prediction,
        send_irrigation_alert,
    )
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from datetime import datetime, timezone

    today = date.today()
    _log.info("=" * 56)
    _log.info("Daily prediction job started for %s", today)
    _log.info("=" * 56)

    # ── STEP 1: Extend dataset with recent NASA POWER weather ─────────────────
    # This ensures PatchTST always has a real 30-day window, not stale 2024 data
    try:
        import sys
        from core.config import get_settings as _get_cfg
        _cfg = _get_cfg()
        sys.path.insert(0, str(_cfg.elisa2_root))
        from ingestion.live_weather import extend_dataset
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: extend_dataset(days_back=45))
        _log.info("Dataset extended with fresh NASA POWER data.")
    except Exception as exc:
        _log.warning("Dataset extension failed (non-fatal): %s", exc)
    # ─────────────────────────────────────────────────────────────────────────

    # Load all active farms + their users
    async with get_db_context() as db:
        result = await db.execute(
            select(Farm, User)
            .join(User, Farm.user_id == User.id)
            .where(Farm.active == True)
        )
        pairs = result.all()

    _log.info("Processing %d active farms.", len(pairs))
    success = error = 0

    for farm, user in pairs:
        try:
            await _process_farm(farm, user, today)
            success += 1
        except Exception as exc:
            _log.error("Farm %s (%s) failed: %s", farm.name, farm.id, exc)
            error += 1

    _log.info("Predictions done. success=%d error=%d", success, error)

    # ── STEP 5: Upload updated farm states back to Drive ──────────────────────
    try:
        from utils.drive_sync import upload_models_and_data
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(None, upload_models_and_data)
        _log.info("Farm states synced to Drive.")
    except Exception as exc:
        _log.warning("Nightly Drive upload failed (non-fatal): %s", exc)
    # ─────────────────────────────────────────────────────────────────────────


async def _process_farm(farm, user, today: date) -> None:
    """Processes one farm: predict → store → alert → savings."""
    from datetime import datetime, timezone

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from core.database import get_db_context
    from db_models.prediction import Prediction
    from services.ml_bridge import get_prediction, get_rain_forecast
    from services.savings_engine import compute_savings, current_season
    from services.whatsapp import (
        WhatsAppDeliveryError,
        build_alert_payload_from_prediction,
        send_irrigation_alert,
    )

    # ── 1. Run ML inference ───────────────────────────────────────────────────
    ml_result = await get_prediction(
        farm_id  = str(farm.id),
        district = farm.district or "Meerut",
        crop     = farm.crop,
        on_date  = today,
    )

    if "error" in ml_result:
        _log.warning(
            "Prediction error for farm %s: %s", farm.id, ml_result["error"]
        )
        return

    # ── 2. Fetch rain ─────────────────────────────────────────────────────────
    if farm.centroid_lat and farm.centroid_lon:
        rain_hourly = await get_rain_forecast(farm.centroid_lat, farm.centroid_lon, days=2)
        rain_24h    = round(sum(rain_hourly[:24]), 2)
    else:
        rain_24h = 0.0

    # ── 3. Upsert prediction row ──────────────────────────────────────────────
    async with get_db_context() as db:
        stmt = (
            pg_insert(Prediction)
            .values(
                farm_id         = farm.id,
                date            = today,
                sm_forecast     = ml_result.get("sm_forecast"),
                irrigate        = bool(ml_result.get("irrigate", False)),
                pump_start_hour = ml_result.get("pump_start_hour"),
                pump_end_hour   = ml_result.get("pump_end_hour"),
                energy_kwh      = ml_result.get("energy_kwh"),
                cost_inr        = ml_result.get("cost_inr"),
                rain_24h_mm     = rain_24h,
                reason          = ml_result.get("reason", ""),
                whatsapp_sent   = False,
                created_at      = datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                constraint="uq_prediction_farm_date",
                set_={
                    "sm_forecast":     ml_result.get("sm_forecast"),
                    "irrigate":        bool(ml_result.get("irrigate", False)),
                    "pump_start_hour": ml_result.get("pump_start_hour"),
                    "pump_end_hour":   ml_result.get("pump_end_hour"),
                    "energy_kwh":      ml_result.get("energy_kwh"),
                    "cost_inr":        ml_result.get("cost_inr"),
                    "rain_24h_mm":     rain_24h,
                    "reason":          ml_result.get("reason", ""),
                    "created_at":      datetime.now(timezone.utc),
                },
            )
            .returning(Prediction.id)
        )
        result = await db.execute(stmt)
        prediction_id = result.scalar_one()

    _log.info(
        "Farm %s: irrigate=%s rain_24h=%.1fmm prediction_id=%s",
        farm.name, ml_result.get("irrigate"), rain_24h, prediction_id,
    )

    # ── 4. WhatsApp alert if irrigation needed ────────────────────────────────
    if ml_result.get("irrigate") and user.whatsapp_opt_in:
        payload = build_alert_payload_from_prediction(
            prediction = ml_result,
            user_name  = user.name,
            farm_name  = farm.name,
            phone      = user.phone,
            language   = user.language,
        )
        if payload:
            try:
                await send_irrigation_alert(payload)
                # Mark as sent
                async with get_db_context() as db:
                    from sqlalchemy import update
                    from db_models.prediction import Prediction as P
                    await db.execute(
                        update(P)
                        .where(P.id == prediction_id)
                        .values(whatsapp_sent=True)
                    )
                _log.info("WhatsApp alert sent: farm=%s phone=%s", farm.name, user.phone)
            except WhatsAppDeliveryError as exc:
                _log.warning(
                    "WhatsApp delivery failed for farm %s: %s", farm.name, exc
                )

    # ── 5. Recompute savings (quick update) ───────────────────────────────────
    try:
        season = current_season(today)
        compute_savings(
            farm_id  = str(farm.id),
            district = farm.district or "Meerut",
            crop     = farm.crop,
            season   = season,
        )
    except Exception as exc:
        _log.debug("Savings recompute skipped for farm %s: %s", farm.name, exc)


def start_scheduler() -> None:
    scheduler.add_job(
        daily_prediction_job,
        CronTrigger(hour=5, minute=0),
        id              = "daily_predictions",
        replace_existing= True,
        misfire_grace_time = 3600,   # run up to 1h late if Render was sleeping
    )
    scheduler.start()
    _log.info("APScheduler started — daily predictions at 05:00 IST.")