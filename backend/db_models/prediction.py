# Paste contents from the generated db_models/prediction.py here
# backend/db_models/prediction.py
"""
ORM model for the `predictions` table.
One row per farm per day — created by the daily APScheduler job
and also on-demand via the /predict endpoint.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    farm_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="Date this prediction was made for (today's decision date)",
    )

    # PatchTST 7-day forecast — array of 7 SM values in mm
    sm_forecast: Mapped[list[float] | None] = mapped_column(
        ARRAY(Float),
        nullable=True,
        comment="7-day soil moisture forecast [day1_mm, ..., day7_mm]",
    )

    # MPC decision
    irrigate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pump_start_hour: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True,
        comment="Cheapest tariff window start hour (0–23)",
    )
    pump_end_hour: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True,
        comment="Cheapest tariff window end hour (0–23)",
    )
    energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    rain_24h_mm: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Forecasted rain in next 24h (used for C2 suppression check)",
    )
    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Human-readable MPC decision reason shown in WhatsApp + UI",
    )

    # Delivery tracking
    whatsapp_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    # Unique constraint: one prediction per farm per day
    __table_args__ = (
        UniqueConstraint("farm_id", "date", name="uq_prediction_farm_date"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    farm: Mapped["Farm"] = relationship(  # type: ignore[name-defined]
        "Farm",
        back_populates="predictions",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<Prediction farm={self.farm_id} date={self.date} "
            f"irrigate={self.irrigate}>"
        )