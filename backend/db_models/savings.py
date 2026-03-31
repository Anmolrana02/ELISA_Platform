# Paste contents from the generated db_models/savings.py here
# backend/db_models/savings.py
"""
ORM model for the `savings_log` table.
One row per farm per season — updated by savings_engine.py after
each confirmed irrigation event and at end-of-season summary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class SavingsLog(Base):
    __tablename__ = "savings_log"

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
    season: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="e.g. 'Rabi-2025', 'Kharif-2025'",
    )

    # Savings vs blind baseline
    water_saved_mm: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="How much water (mm) this farmer saved vs traditional blind irrigation",
    )
    cost_saved_inr: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="₹ saved vs blind farmer energy cost",
    )

    # Event counts
    actual_events: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="Farmer-confirmed irrigation events this season",
    )
    blind_baseline_events: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="Simulated blind farmer events for same period",
    )

    # Stress tracking
    stress_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="Days where SM fell below PWP — proxy for yield stress",
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # One row per farm per season
    __table_args__ = (
        UniqueConstraint("farm_id", "season", name="uq_savings_farm_season"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    farm: Mapped["Farm"] = relationship(  # type: ignore[name-defined]
        "Farm",
        back_populates="savings_logs",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<SavingsLog farm={self.farm_id} season={self.season} "
            f"saved=₹{self.cost_saved_inr:.0f}>"
        )