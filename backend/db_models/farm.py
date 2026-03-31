# Paste contents from the generated db_models/farm.py here
# backend/db_models/farm.py
"""
ORM model for the `farms` table.
The `boundary` column is a PostGIS POLYGON (SRID 4326 = WGS84).
Centroid, area_ha, and district are auto-populated at insert time
by the farms API using PostGIS functions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    crop: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="'Wheat' or 'Rice'",
    )

    # PostGIS polygon — stored as WKB, received as GeoJSON from frontend
    boundary: Mapped[Geometry] = mapped_column(
        Geometry("POLYGON", srid=4326),
        nullable=True,
        comment="Farm boundary drawn on Leaflet map",
    )

    # Auto-computed from boundary at insert / update
    centroid_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    area_ha: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="ST_Area(boundary::geography) / 10000",
    )
    district: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Nearest district from ELISA 5-district study area",
    )

    gee_extracted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True after GEE hyperlocal extraction is available for this farm",
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="Soft-delete flag",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User",
        back_populates="farms",
        lazy="select",
    )
    predictions: Mapped[list["Prediction"]] = relationship(  # type: ignore[name-defined]
        "Prediction",
        back_populates="farm",
        cascade="all, delete-orphan",
        lazy="select",
    )
    savings_logs: Mapped[list["SavingsLog"]] = relationship(  # type: ignore[name-defined]
        "SavingsLog",
        back_populates="farm",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Farm id={self.id} name={self.name!r} district={self.district}>"


# Explicit index on user_id (also declared inline above, but explicit here for Alembic)
_farms_user_id_idx = Index("farms_user_id_idx", Farm.user_id)