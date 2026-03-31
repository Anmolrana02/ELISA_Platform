# Paste contents from the generated db_models/user.py here
# backend/db_models/user.py
"""
ORM model for the `users` table.
Authentication is phone-based (OTP), no passwords stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(
        String(15), unique=True, nullable=False, index=True,
        comment="+91XXXXXXXXXX format",
    )
    language: Mapped[str] = mapped_column(
        String(5), nullable=False, default="hi",
        comment="'hi' or 'en' — controls WhatsApp template language",
    )
    whatsapp_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    farms: Mapped[list["Farm"]] = relationship(  # type: ignore[name-defined]
        "Farm",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} phone={self.phone}>"