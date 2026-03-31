# settings.py
"""
config/settings.py
──────────────────
Single source of truth for all configuration.

Usage in any module:
    from config.settings import settings, agro

settings → environment/infra config (from .env)
agro     → agronomy constants      (from agronomy.yaml)
"""

import logging
import os
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Project root ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent


# ── Environment settings (from .env) ─────────────────────────────────────────

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Project
    project_name: str = "ELISA_2.0"
    env:          str = "development"
    log_level:    str = "INFO"

    # Paths
    data_dir:   Path = ROOT / "data"
    models_dir: Path = ROOT / "saved_models"
    logs_dir:   Path = ROOT / "logs"

    # NASA POWER
    nasa_power_url:   str = "https://power.larc.nasa.gov/api/temporal/daily/point"
    nasa_start_date:  str = "2015-01-01"
    nasa_end_date:    str = "2024-12-31"

    # GEE
    gee_enabled:         bool          = False
    gee_service_account: Optional[str] = None
    gee_key_file:        Optional[str] = None
    gee_grid_spacing_deg: float        = 0.03

    # OpenMeteo
    openmeteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    openmeteo_archive_url:  str = "https://archive-api.open-meteo.com/v1/archive"

    # PatchTST hyperparameters
    seq_len:          int   = 30
    patch_size:       int   = 5
    d_model:          int   = 64
    n_heads:          int   = 4
    n_layers:         int   = 2
    d_ff:             int   = 128
    dropout:          float = 0.1
    forecast_horizon: int   = 7
    epochs:           int   = 60
    batch_size:       int   = 64
    learning_rate:    float = 1e-3

    # Simulation
    forecast_noise_std: float = 1.5

    @field_validator("data_dir", "models_dir", "logs_dir", mode="before")
    @classmethod
    def resolve_paths(cls, v):
        p = ROOT / v if not Path(str(v)).is_absolute() else Path(str(v))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @model_validator(mode="after")
    def ensure_subdirs(self):
        for sub in [
            "soil_moisture_data", "gee_extracts",
            "downscaled", "farm_states", "farms",
        ]:
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)
        return self

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def n_patches(self) -> int:
        return self.seq_len // self.patch_size

    @property
    def gee_is_ready(self) -> bool:
        return (
            self.gee_enabled
            and bool(self.gee_service_account)
            and bool(self.gee_key_file)
            and Path(self.gee_key_file).exists()
        )

    # ── Derived paths ─────────────────────────────────────────────────────────

    @property
    def raw_weather_csv(self) -> Path:
        return self.data_dir / "raw_nasa_weather.csv"

    @property
    def simulated_dataset(self) -> Path:
        return self.data_dir / "dataset_simulated.csv"

    @property
    def real_soil_dataset(self) -> Path:
        return self.data_dir / "dataset_real_soil.csv"

    @property
    def patchtst_checkpoint(self) -> Path:
        return self.models_dir / "patchtst.pt"

    @property
    def downscaler_checkpoint(self) -> Path:
        return self.models_dir / "downscaler_rf.joblib"

    def get_logger(self, name: str) -> logging.Logger:
        return _setup_logger(name, self.logs_dir, self.log_level)


# ── Agronomy config (from YAML) ───────────────────────────────────────────────

class DistrictCoords:
    def __init__(self, data: dict):
        self._data = {k: (v["lat"], v["lon"]) for k, v in data.items()}

    def __getitem__(self, district: str) -> Tuple[float, float]:
        return self._data[district]

    def keys(self) -> List[str]:
        return list(self._data.keys())

    def items(self):
        return self._data.items()

    def grid_3x3(self, district: str, spacing: float = 0.03) -> List[Tuple[float, float]]:
        """9-point 3×3 grid around district centroid for RF downscaling training."""
        lat, lon = self._data[district]
        offsets = [-spacing, 0.0, spacing]
        return [
            (round(lat + dlat, 5), round(lon + dlon, 5))
            for dlat in offsets
            for dlon in offsets
        ]


class CropProfile:
    def __init__(self, name: str, data: dict, soil: dict):
        self.name             = name
        self._d               = data
        self._soil            = soil
        self.root_depth_mm    = data["root_depth_mm"]
        self.growing_months   = data.get("growing_months", [])
        self.kc_table         = data.get("kc", {})

        fc  = soil["field_capacity_frac"]
        pwp = soil["wilting_point_frac"]
        self.fc_mm  = fc  * self.root_depth_mm
        self.pwp_mm = pwp * self.root_depth_mm

        if name == "Wheat":
            mad             = data["mad"]
            self.trigger_mm = self.fc_mm - (self.fc_mm - self.pwp_mm) * mad
            self.irr_amount_mm = data["irr_amount_mm"]
        elif name == "Rice":
            self.trigger_mm        = data["ponding_trigger_mm"]
            self.ponding_target_mm = data["ponding_target_mm"]
            self.percolation_mm_day = data["percolation_mm_day"]
            self.irr_amount_mm     = data["ponding_target_mm"]

    def kc(self, doy: int) -> float:
        """FAO-56 crop coefficient for day-of-year."""
        tbl = self.kc_table
        if self.name == "Wheat":
            if doy >= 335 or doy < 60:  return tbl["mid"]["value"]
            if 305 <= doy < 335:        return tbl["initial"]["value"]
            if 60  <= doy < 105:        return tbl["late"]["value"]
            return tbl.get("default", 0.80)
        if self.name == "Rice":
            if 171 <= doy < 200: return tbl["initial"]["value"]
            if 200 <= doy < 280: return tbl["mid"]["value"]
            if 280 <= doy <= 304:return tbl["late"]["value"]
            return tbl.get("default", 0.60)
        return 1.0


class PumpSpec:
    def __init__(self, data: dict):
        self.power_hp       = data["power_hp"]
        self.efficiency     = data["efficiency"]
        self.run_duration_h = data["run_duration_h"]

    @property
    def power_kw(self) -> float:
        return self.power_hp * 0.7457

    @property
    def energy_per_run_kwh(self) -> float:
        return (self.power_kw / self.efficiency) * self.run_duration_h


class TariffSchedule:
    def __init__(self, data: dict):
        self.low    = data["low"]
        self.medium = data["medium"]
        self.peak   = data["peak"]

    def rate_for_hour(self, hour: int) -> float:
        if 0  <= hour < 6:  return self.low
        if 6  <= hour < 18: return self.medium
        if 18 <= hour < 22: return self.peak
        return self.medium

    def slot_name(self, hour: int) -> str:
        if 0  <= hour < 6:  return "low"
        if 6  <= hour < 18: return "medium"
        if 18 <= hour < 22: return "peak"
        return "medium"

    def cheapest_window(self, duration_h: int = 2) -> Tuple[int, float]:
        pump_draw = settings.agro.pump.power_kw / settings.agro.pump.efficiency
        best_h, best_cost = 0, float("inf")
        for start in range(24 - duration_h + 1):
            cost = sum(pump_draw * self.rate_for_hour((start + h) % 24)
                       for h in range(duration_h))
            if cost < best_cost:
                best_cost, best_h = cost, start
        return best_h, round(best_cost, 2)


class AgronomyConfig:
    def __init__(self, path: Path):
        with open(path) as f:
            raw = yaml.safe_load(f)

        self.districts = DistrictCoords(raw["study_area"]["districts"])
        soil           = raw["soil"]
        self.crops: Dict[str, CropProfile] = {
            name: CropProfile(name, data, soil)
            for name, data in raw["crops"].items()
        }
        self.pump    = PumpSpec(raw["pump"])
        self.tariff  = TariffSchedule(raw["tariff"])
        self.mpc     = raw["mpc"]
        self.sim     = raw["simulation"]

    def get_crop(self, name: str) -> CropProfile:
        return self.crops.get(name, self.crops["Wheat"])


# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logger(name: str, logs_dir: Path, level: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level.upper())
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logs_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(logs_dir / "elisa.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


# ── Singleton instances (import these everywhere) ─────────────────────────────

class _AppConfig:
    """Lazy-loaded singleton wrapper so YAML is only read once."""
    _settings: Optional[Settings]    = None
    _agro:     Optional[AgronomyConfig] = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = Settings()
        return self._settings

    @property
    def agro(self) -> AgronomyConfig:
        if self._agro is None:
            self._agro = AgronomyConfig(ROOT / "config" / "agronomy.yaml")
        return self._agro


_app = _AppConfig()

# Public API — import these two in every module
settings: Settings       = _app.settings   # type: ignore[assignment]
agro:     AgronomyConfig = _app.agro       # type: ignore[assignment]


if __name__ == "__main__":
    print(f"Project  : {settings.project_name}")
    print(f"GEE ready: {settings.gee_is_ready}")
    print(f"Districts: {agro.districts.keys()}")
    print(f"Wheat FC : {agro.crops['Wheat'].fc_mm:.1f} mm")
    print(f"Pump kW  : {agro.pump.power_kw:.2f} kW")
    best_h, cost = agro.tariff.cheapest_window()
    print(f"Cheapest pump window: {best_h:02d}:00 | ₹{cost:.2f}")
