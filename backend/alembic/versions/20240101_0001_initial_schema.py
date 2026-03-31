# Paste contents from the generated migration file here
# backend/alembic/versions/20240101_0001_initial_schema.py
"""
Initial schema — 4 tables + PostGIS extension.

Revision: 0001
Creates:  users, farms (with PostGIS boundary column),
          predictions (with ARRAY[float] sm_forecast),
          savings_log
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# Alembic revision identifiers
revision: str = "0001"
down_revision = None         # first migration — no parent
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 0. PostGIS extension (idempotent) ─────────────────────────────────────
    # Must run before any GEOMETRY column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")   # gen_random_uuid()

    # ── 1. users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name",            sa.String(100), nullable=False),
        sa.Column(
            "phone",
            sa.String(15),
            unique=True,
            nullable=False,
            comment="+91XXXXXXXXXX format",
        ),
        sa.Column(
            "language",
            sa.String(5),
            nullable=False,
            server_default="hi",
            comment="'hi' or 'en'",
        ),
        sa.Column(
            "whatsapp_opt_in",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("users_phone_idx", "users", ["phone"])

    # ── 2. farms ──────────────────────────────────────────────────────────────
    op.create_table(
        "farms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name",  sa.String(100), nullable=False),
        sa.Column("crop",  sa.String(20),  nullable=False, comment="'Wheat' or 'Rice'"),
        # PostGIS polygon
        sa.Column(
            "boundary",
            Geometry("POLYGON", srid=4326),
            nullable=True,
        ),
        sa.Column("centroid_lat",  sa.Float, nullable=True),
        sa.Column("centroid_lon",  sa.Float, nullable=True),
        sa.Column("area_ha",       sa.Float, nullable=True),
        sa.Column("district",      sa.String(50), nullable=True),
        sa.Column(
            "gee_extracted",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("farms_user_id_idx", "farms", ["user_id"])

    # ── 3. predictions ────────────────────────────────────────────────────────
    op.create_table(
        "predictions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date, nullable=False),
        # 7-element float array — PatchTST 7-day SM forecast
        sa.Column(
            "sm_forecast",
            postgresql.ARRAY(sa.Float),
            nullable=True,
            comment="[day1_mm, day2_mm, ..., day7_mm]",
        ),
        sa.Column("irrigate",         sa.Boolean,  nullable=False),
        sa.Column("pump_start_hour",  sa.SmallInteger, nullable=True),
        sa.Column("pump_end_hour",    sa.SmallInteger, nullable=True),
        sa.Column("energy_kwh",       sa.Float,    nullable=True),
        sa.Column("cost_inr",         sa.Float,    nullable=True),
        sa.Column("rain_24h_mm",      sa.Float,    nullable=True),
        sa.Column("reason",           sa.Text,     nullable=True),
        sa.Column(
            "whatsapp_sent",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("farm_id", "date", name="uq_prediction_farm_date"),
    )
    op.create_index("predictions_farm_id_idx", "predictions", ["farm_id"])
    op.create_index("predictions_date_idx",    "predictions", ["date"])

    # ── 4. savings_log ────────────────────────────────────────────────────────
    op.create_table(
        "savings_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season", sa.String(20), nullable=False, comment="e.g. 'Rabi-2025'"),
        sa.Column(
            "water_saved_mm",
            sa.Float,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_saved_inr",
            sa.Float,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "actual_events",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "blind_baseline_events",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "stress_days",
            sa.SmallInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("farm_id", "season", name="uq_savings_farm_season"),
    )
    op.create_index("savings_log_farm_id_idx", "savings_log", ["farm_id"])


def downgrade() -> None:
    # Drop in reverse FK order
    op.drop_table("savings_log")
    op.drop_table("predictions")
    op.drop_table("farms")
    op.drop_table("users")
    # Leave PostGIS — don't drop extensions on downgrade