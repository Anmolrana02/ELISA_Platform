# run.py
"""
pipelines/run.py
─────────────────
Master pipeline orchestrator for ELISA 2.0.

Usage:
    python -m pipelines.run                  # run all steps
    python -m pipelines.run --step 1 2       # specific steps only
    python -m pipelines.run --from-step 4    # from step 4 onwards
    python -m pipelines.run --force          # re-run completed steps
    python -m pipelines.run --list           # show status of all steps
    python -m pipelines.run --nightly        # run nightly farm update
    python -m pipelines.run --dashboard      # launch Streamlit dashboard

Steps:
    1  Fetch NASA POWER weather
    2  Build simulated dataset    (fast, no ERA5 needed)
    3  Build real-soil dataset    (requires ERA5 .nc files)
    4  GEE satellite extraction   (stub or real)
    5  Train RF downscaler
    6  Apply RF to all districts
    7  Train PatchTST transformer
    8  Evaluate PatchTST
    9  Run 3-farmer simulation + figures
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from narwhals import read_csv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import settings

_log = settings.get_logger("pipeline")


# ── Step registry ──────────────────────────────────────────────────────────────

def _steps():
    """Returns step definitions. Deferred so settings are fully loaded."""
    return {
        1: {
            "name":   "Fetch NASA POWER weather",
            "fn":     _step_weather,
            "output": settings.raw_weather_csv,
        },
        2: {
            "name":   "Build simulated dataset",
            "fn":     _step_simulated,
            "output": settings.simulated_dataset,
            "needs":  1,
        },
        3: {
            "name":   "Build real-soil dataset (ERA5)",
            "fn":     _step_real_soil,
            "output": settings.real_soil_dataset,
            "needs":  1,
            "note":   "Requires ERA5 .nc files in data/soil_moisture_data/",
        },
        4: {
            "name":   "GEE satellite extraction (3×3 grid)",
            "fn":     _step_gee,
            "output": settings.data_dir / "gee_extracts",
            "note":   "Stub mode until GEE_ENABLED=true in .env",
        },
        5: {
            "name":   "Train RF spatial downscaler",
            "fn":     _step_rf_train,
            "output": settings.downscaler_checkpoint,
            "needs":  4,
        },
        6: {
            "name":   "Apply RF downscaling to all districts",
            "fn":     _step_rf_apply,
            "output": settings.data_dir / "downscaled",
            "needs":  5,
        },
        7: {
            "name":   "Train PatchTST transformer",
            "fn":     _step_patchtst_train,
            "output": settings.patchtst_checkpoint,
            "needs":  3,
            "note":   "~30 min on CPU",
        },
        8: {
            "name":   "Evaluate PatchTST (per-day R²)",
            "fn":     _step_evaluate,
            "output": None,      # always run
            "needs":  7,
        },
        9: {
            "name":   "3-farmer simulation + figures",
            "fn":     _step_simulate,
            "output": settings.logs_dir / "simulation_results.csv",
            "needs":  3,
        },
    }


# ── Step implementations ───────────────────────────────────────────────────────

def _step_weather(force: bool):
    from ingestion.pipeline import build_raw_weather
    return build_raw_weather(force=force) is not None


def _step_simulated(force: bool):
    from features.builder import build_simulated
    return build_simulated(force=force) is not None


def _step_real_soil(force: bool):
    from ingestion.pipeline import build_real_soil_dataset
    from features.builder import build_real_soil
    raw = build_real_soil_dataset(force=force)
    if raw is None:
        return False
    return build_real_soil(raw, force=force) is not None


def _step_gee(force: bool):
    from ingestion.pipeline import build_gee_extracts
    results = build_gee_extracts(force=force)
    return len(results) > 0


def _step_rf_train(force: bool):
    from models.downscaler.trainer import train
    return train(force=force) is not None


def _step_rf_apply(force: bool):
    from models.downscaler.trainer import apply_to_all_districts
    results = apply_to_all_districts()
    return len(results) > 0


def _step_patchtst_train(force: bool):
    import pandas as pd
    from models.patchtst.trainer import train
    from utils.dates import read_csv
    df = read_csv(settings.real_soil_dataset)
    train(df=df, force=force)
    return settings.patchtst_checkpoint.exists()


def _step_evaluate(force: bool):
    import pandas as pd
    from models.patchtst.trainer import evaluate
    from utils.dates import read_csv
    df = read_csv(settings.real_soil_dataset)
    result = evaluate(df)
    return result is not None


def _step_simulate(force: bool):
    import pandas as pd
    from simulation.compare import run
    from utils.dates import read_csv
    path = settings.real_soil_dataset
    if not path.exists():
        _log.error("Real soil dataset not found. Run step 3 first.")
        return False
    df = read_csv(path)
    return run(df) is not None


# ── Runner logic ───────────────────────────────────────────────────────────────

def _is_done(step: dict) -> bool:
    out = step.get("output")
    if out is None:
        return False
    p = Path(out)
    if p.is_dir():
        # For GEE extracts — all 5 district files must exist
        if "gee_extracts" in str(p):
            from config.settings import agro
            expected = [
                p / f"{district}_hyperlocal.csv"
                for district in agro.districts.keys()
            ]
            return all(f.exists() for f in expected)
        return any(p.iterdir())
    return p.exists()


def _dep_done(step_num: int, registry: dict) -> bool:
    dep = registry[step_num].get("needs")
    return dep is None or _is_done(registry[dep])


def print_status(registry: dict):
    print(f"\n{'─'*65}")
    print("  ELISA 2.0 — Pipeline Status")
    print(f"{'─'*65}")
    print(f"  {'#':<4}  {'Status':<10}  Name")
    print(f"  {'─'*4}  {'─'*10}  {'─'*44}")
    for n, s in registry.items():
        status = "✓ done" if _is_done(s) else "pending"
        note   = f"   [{s['note']}]" if s.get("note") else ""
        print(f"  {n:<4}  {status:<10}  {s['name']}{note}")
    print(f"{'─'*65}\n")


def run_pipeline(
    steps:    list,
    force:    bool = False,
) -> bool:
    registry = _steps()
    passed = skipped = failed = 0

    for n in steps:
        if n not in registry:
            _log.error("Step %d not found.", n)
            continue

        step = registry[n]

        if not force and _is_done(step):
            _log.info("[SKIP] Step %d: %s", n, step["name"])
            skipped += 1
            continue

        if not _dep_done(n, registry):
            _log.warning("[WAIT] Step %d needs step %d first. Skipping.", n, step.get("needs"))
            skipped += 1
            continue

        _log.info("")
        _log.info("=" * 62)
        _log.info("STEP %d: %s", n, step["name"])
        if step.get("note"):
            _log.info("NOTE : %s", step["note"])
        _log.info("=" * 62)

        t0 = time.time()
        try:
            ok = step["fn"](force)
        except Exception as exc:
            _log.error("Step %d raised: %s", n, exc, exc_info=True)
            ok = False

        elapsed = time.time() - t0
        if ok:
            _log.info("Step %d done in %.1fs.", n, elapsed)
            passed += 1
        else:
            _log.error("Step %d FAILED.", n)
            failed += 1
            break

    _log.info("")
    _log.info("=" * 62)
    _log.info("Pipeline finished. Ran=%d  Skipped=%d  Failed=%d", passed, skipped, failed)
    _log.info("=" * 62)
    return failed == 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ELISA 2.0 pipeline orchestrator.")
    parser.add_argument("--step",       "-s", type=int, nargs="+", metavar="N")
    parser.add_argument("--from-step",        type=int, metavar="N")
    parser.add_argument("--force",      "-f", action="store_true")
    parser.add_argument("--list",       "-l", action="store_true")
    parser.add_argument("--dashboard",        action="store_true")
    parser.add_argument("--nightly",          action="store_true")
    args = parser.parse_args()

    registry = _steps()

    if args.list:
        print_status(registry); return

    if args.dashboard:
        subprocess.run(["streamlit", "run", str(ROOT / "dashboard" / "app.py")], cwd=ROOT)
        return

    if args.nightly:
        from decision.state_manager import run_nightly_update
        run_nightly_update(); return

    if args.step:
        steps = sorted(set(args.step))
    elif args.from_step:
        steps = [n for n in registry if n >= args.from_step]
    else:
        steps = list(registry.keys())

    print_status(registry)
    ok = run_pipeline(steps, force=args.force)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
