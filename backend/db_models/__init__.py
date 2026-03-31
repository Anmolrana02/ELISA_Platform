# Paste contents from the generated db_models/__init__.py here
# backend/db_models/__init__.py
"""
Import all ORM models here so that:
  1. Alembic autogenerate sees every table when it calls `target_metadata`
  2. Any module that does `from db_models import *` gets all models

Order matters: User first (no FK deps), then Farm (FK → User),
then Prediction and SavingsLog (FK → Farm).
"""

from db_models.user import User           # noqa: F401
from db_models.farm import Farm           # noqa: F401
from db_models.prediction import Prediction  # noqa: F401
from db_models.savings import SavingsLog  # noqa: F401

__all__ = ["User", "Farm", "Prediction", "SavingsLog"]