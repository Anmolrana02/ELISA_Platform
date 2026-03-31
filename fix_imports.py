"""
ELISA Platform — Import & Path Fixer
=====================================
Run this AFTER moving elisa2/ into ELISA_Platform/.

What it fixes automatically:
  1. Scans every .py file in elisa2/ for hardcoded Windows paths
  2. Fixes the ROOT path in settings.py for new folder depth
  3. Checks all internal imports still resolve correctly
  4. Updates GEE_KEY_FILE path style
  5. Adds utils/ __init__.py if missing
  6. Reports any problems it cannot fix automatically

Usage:
    cd ELISA_Platform
    python fix_imports.py

    # Or specify paths explicitly:
    python fix_imports.py --elisa2 "C:/Projects/ELISA_Platform/elisa2"
"""

import argparse
import ast
import os
import re
import sys
from pathlib import Path


# ── Colour helpers ────────────────────────────────────────────────────────────
def _color(code): return code if sys.platform != "win32" or "WT_SESSION" in os.environ else ""
GREEN  = _color("\033[92m"); YELLOW = _color("\033[93m")
RED    = _color("\033[91m"); CYAN   = _color("\033[96m")
BOLD   = _color("\033[1m");  RESET  = _color("\033[0m")

def ok(m):   print(f"  {GREEN}✓{RESET}  {m}")
def warn(m): print(f"  {YELLOW}!{RESET}  {m}")
def err(m):  print(f"  {RED}✗{RESET}  {m}")
def info(m): print(f"  {CYAN}→{RESET}  {m}")
def head(m): print(f"\n{BOLD}{m}{RESET}")


# ── Known elisa2 internal packages ────────────────────────────────────────────
# These are all the top-level packages inside elisa2/.
# Any import of these is an internal import and should work
# as long as elisa2/ is on sys.path (which ml_bridge.py ensures).
INTERNAL_PACKAGES = {
    "config", "ingestion", "features", "models",
    "decision", "simulation", "farm", "dashboard",
    "pipelines", "utils",
}

# External packages that elisa2 uses (must be installed via requirements.txt)
EXTERNAL_PACKAGES = {
    "numpy", "pandas", "torch", "sklearn", "scipy", "matplotlib",
    "requests", "yaml", "pydantic", "joblib", "xarray", "netCDF4",
    "ee", "earthengine", "streamlit", "folium", "plotly", "altair",
    "dask", "fsspec", "pyarrow", "cloudpickle",
}


def find_python_files(root: Path) -> list[Path]:
    """Find all .py files in elisa2/, excluding __pycache__ and venv."""
    files = []
    for p in root.rglob("*.py"):
        parts = p.parts
        if any(x in parts for x in ("__pycache__", "venv", ".venv", "node_modules")):
            continue
        files.append(p)
    return sorted(files)


def check_syntax(path: Path) -> tuple[bool, str]:
    """Parse a Python file and return (ok, error_message)."""
    try:
        ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError line {e.lineno}: {e.msg}"


def fix_settings_root(elisa2_root: Path) -> bool:
    """
    Fix the ROOT path in settings.py.

    settings.py can live at two depths:
      - elisa2/settings.py          → ROOT = Path(__file__).parent
      - elisa2/config/settings.py   → ROOT = Path(__file__).parent.parent

    We detect which depth it's at and patch accordingly.
    """
    # Try both locations
    candidates = [
        elisa2_root / "settings.py",
        elisa2_root / "config" / "settings.py",
    ]
    settings_path = next((p for p in candidates if p.exists()), None)
    if not settings_path:
        warn("settings.py not found — skipping ROOT fix.")
        return False

    text = settings_path.read_text(encoding="utf-8")

    # Determine correct ROOT expression based on depth
    depth = len(settings_path.relative_to(elisa2_root).parts) - 1  # 0 = flat, 1 = in subfolder
    if depth == 0:
        correct_root = "ROOT = Path(__file__).parent"
    else:
        correct_root = "ROOT = Path(__file__).parent.parent"

    # Check current state
    if correct_root in text:
        ok(f"settings.py ROOT already correct ({correct_root.split('=')[1].strip()})")
        return True

    # Try to replace any ROOT = Path(...) line
    new_text = re.sub(
        r"ROOT\s*=\s*Path\(__file__\)[.\w()]*",
        correct_root,
        text,
    )
    if new_text == text:
        warn(f"Could not auto-fix ROOT in settings.py — check manually.")
        warn(f"  It should be: {correct_root}")
        return False

    settings_path.write_text(new_text, encoding="utf-8")
    ok(f"Fixed ROOT in settings.py → {correct_root}")
    return True


def fix_hardcoded_windows_paths(elisa2_root: Path) -> int:
    """
    Replace hardcoded Windows-style absolute paths in .py and .env files.
    Returns count of files modified.
    """
    # Patterns that suggest hardcoded paths from the old location
    old_path_patterns = [
        r"F:\\ELISA\\ELISA_2\.1",
        r"F:/ELISA/ELISA_2\.1",
        r"C:\\Users\\[^\\\"'\s]+\\ELISA_2\.1",
        r"C:/Users/[^/\"'\s]+/ELISA_2\.1",
    ]
    combined = re.compile("|".join(old_path_patterns), re.IGNORECASE)

    modified = 0
    new_path = str(elisa2_root).replace("\\", "/")

    all_files = list(elisa2_root.rglob("*.py")) + list(elisa2_root.rglob("*.env")) + \
                list(elisa2_root.rglob("*.yaml")) + list(elisa2_root.rglob("*.json"))

    for fpath in all_files:
        if "__pycache__" in str(fpath):
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if combined.search(text):
            new_text = combined.sub(new_path, text)
            fpath.write_text(new_text, encoding="utf-8")
            ok(f"Fixed hardcoded path in: {fpath.relative_to(elisa2_root)}")
            modified += 1

    return modified


def ensure_init_files(elisa2_root: Path) -> int:
    """
    Ensure every Python package folder has an __init__.py.
    Returns count of files created.
    """
    created = 0
    # All folders that contain .py files should be packages
    for folder in elisa2_root.rglob("*"):
        if not folder.is_dir():
            continue
        if "__pycache__" in str(folder):
            continue
        py_files = list(folder.glob("*.py"))
        if py_files:
            init = folder / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
                ok(f"Created missing __init__.py in: {folder.relative_to(elisa2_root)}/")
                created += 1
    return created


def ensure_utils_dates(elisa2_root: Path) -> bool:
    """
    utils/dates.py is imported by many files.
    Make sure utils/ package exists with dates.py.
    """
    utils_dir   = elisa2_root / "utils"
    dates_file  = utils_dir / "dates.py"
    init_file   = utils_dir / "__init__.py"

    if dates_file.exists():
        ok("utils/dates.py exists ✓")
        return True

    # Try flat structure (dates.py at root)
    flat_dates = elisa2_root / "dates.py"
    if flat_dates.exists():
        utils_dir.mkdir(exist_ok=True)
        init_file.write_text("", encoding="utf-8")
        dates_file.write_text(flat_dates.read_text(encoding="utf-8"), encoding="utf-8")
        ok(f"Moved dates.py → utils/dates.py")
        warn(f"Original dates.py left at root — you can delete it after testing.")
        return True

    warn("utils/dates.py not found. Creating it with standard content.")
    utils_dir.mkdir(exist_ok=True)
    init_file.write_text("", encoding="utf-8")
    dates_file.write_text('''\
"""
utils/dates.py
Central date-parsing helper.
"""
from __future__ import annotations
from pathlib import Path
from typing import Union
import pandas as pd


def parse_dates(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    if col not in df.columns:
        return df
    if pd.api.types.is_datetime64_any_dtype(df[col]):
        return df
    df = df.copy()
    df[col] = pd.to_datetime(df[col], format="mixed", dayfirst=True)
    return df


def read_csv(path: Union[str, Path], **kwargs) -> pd.DataFrame:
    kwargs.pop("parse_dates", None)
    df = pd.read_csv(path, **kwargs)
    return parse_dates(df, col="date")
''', encoding="utf-8")
    ok("Created utils/dates.py with standard content.")
    return True


def scan_imports(elisa2_root: Path, py_files: list[Path]) -> dict:
    """
    Scan all .py files for import statements.
    Returns a report dict.
    """
    broken        = []   # imports that look wrong
    internal_ok   = []   # confirmed internal imports
    external_ok   = []   # confirmed external imports

    for fpath in py_files:
        try:
            tree = ast.parse(fpath.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        rel = str(fpath.relative_to(elisa2_root))

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                else:
                    names = [node.module.split(".")[0]] if node.module else []

                for name in names:
                    if name in INTERNAL_PACKAGES:
                        # Check that the package actually exists
                        pkg_path = elisa2_root / name
                        if not pkg_path.exists() and not (elisa2_root / f"{name}.py").exists():
                            broken.append((rel, name, "package folder not found"))
                        else:
                            internal_ok.append((rel, name))
                    elif name in EXTERNAL_PACKAGES or name.startswith("_"):
                        external_ok.append((rel, name))
                    # else: stdlib or unknown, skip

    return {
        "broken":      broken,
        "internal_ok": len(set(internal_ok)),
        "external_ok": len(set(external_ok)),
    }


def check_gee_key(elisa2_root: Path) -> None:
    """Verify gee_key.json exists."""
    key = elisa2_root / "gee_key.json"
    if key.exists():
        ok("gee_key.json found ✓")
    else:
        warn("gee_key.json not found in elisa2/")
        warn("  Copy it from your old ELISA_2.1 folder.")


def check_data_dirs(elisa2_root: Path) -> None:
    """Check expected data subdirectories."""
    expected = [
        "data/gee_extracts",
        "data/downscaled",
        "data/farm_states",
        "data/farms",
        "saved_models",
        "logs",
    ]
    for sub in expected:
        p = elisa2_root / sub
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            ok(f"Created missing data dir: {sub}/")


def fix_run_py_import(elisa2_root: Path) -> None:
    """
    run.py has: from narwhals import read_csv
    This is wrong — should be: from utils.dates import read_csv
    Fix it if found.
    """
    candidates = [
        elisa2_root / "run.py",
        elisa2_root / "pipelines" / "run.py",
    ]
    for fpath in candidates:
        if not fpath.exists():
            continue
        text = fpath.read_text(encoding="utf-8")
        if "from narwhals import read_csv" in text:
            new_text = text.replace(
                "from narwhals import read_csv",
                "from utils.dates import read_csv",
            )
            fpath.write_text(new_text, encoding="utf-8")
            ok(f"Fixed wrong import in {fpath.relative_to(elisa2_root)}: narwhals → utils.dates")


def generate_report(elisa2_root: Path, results: dict) -> None:
    head("Import Scan Results")
    print(f"  Internal imports verified: {results['internal_ok']}")
    print(f"  External imports found:    {results['external_ok']}")

    if results["broken"]:
        print(f"\n  {RED}Broken imports found ({len(results['broken'])}):{RESET}")
        for rel, name, reason in results["broken"]:
            print(f"    {RED}✗{RESET}  {rel}: import {name!r} — {reason}")
        print(f"\n  {YELLOW}To fix broken imports:{RESET}")
        print(f"  Check that the package folder exists in: {elisa2_root}")
        print(f"  If it's a flat file (e.g. dates.py), move it into the right package folder.")
    else:
        ok("No broken imports detected.")


def main():
    parser = argparse.ArgumentParser(description="Fix elisa2 imports for monorepo.")
    parser.add_argument("--elisa2", type=str, default=None,
                        help="Path to elisa2/ folder. Defaults to ./elisa2")
    args = parser.parse_args()

    if args.elisa2:
        elisa2_root = Path(args.elisa2).resolve()
    else:
        # Auto-detect: look for elisa2/ relative to this script
        script_dir  = Path(__file__).parent.resolve()
        elisa2_root = script_dir / "elisa2"
        if not elisa2_root.exists():
            # Try parent (if script is inside ELISA_Platform/)
            elisa2_root = script_dir.parent / "elisa2"

    if not elisa2_root.exists():
        err(f"elisa2/ not found at {elisa2_root}")
        err("Run from ELISA_Platform/ or pass --elisa2 /path/to/elisa2")
        sys.exit(1)

    info(f"elisa2 root: {elisa2_root}")

    py_files = find_python_files(elisa2_root)
    info(f"Found {len(py_files)} Python files")

    # ── Syntax check ─────────────────────────────────────────────────────────
    head("Step 1/6 — Syntax check")
    syntax_errors = []
    for f in py_files:
        ok_syntax, msg = check_syntax(f)
        if not ok_syntax:
            err(f"{f.relative_to(elisa2_root)}: {msg}")
            syntax_errors.append(f)
    if not syntax_errors:
        ok("All files parse without syntax errors.")

    # ── Fix ROOT in settings.py ───────────────────────────────────────────────
    head("Step 2/6 — Fix settings.py ROOT path")
    fix_settings_root(elisa2_root)

    # ── Fix hardcoded paths ───────────────────────────────────────────────────
    head("Step 3/6 — Fix hardcoded old paths")
    n = fix_hardcoded_windows_paths(elisa2_root)
    if n == 0:
        ok("No hardcoded old paths found.")

    # ── Fix known wrong imports ───────────────────────────────────────────────
    head("Step 4/6 — Fix known incorrect imports")
    fix_run_py_import(elisa2_root)

    # ── Ensure package structure ──────────────────────────────────────────────
    head("Step 5/6 — Ensure package structure")
    ensure_utils_dates(elisa2_root)
    n = ensure_init_files(elisa2_root)
    if n == 0:
        ok("All __init__.py files already present.")
    check_gee_key(elisa2_root)
    check_data_dirs(elisa2_root)

    # ── Scan imports ──────────────────────────────────────────────────────────
    head("Step 6/6 — Scan all imports")
    results = scan_imports(elisa2_root, py_files)
    generate_report(elisa2_root, results)

    head("Fix script complete")
    print(f"""
  {GREEN}What to do next:{RESET}

  1. Open backend/.env and set:
       ELISA2_PATH=C:\\Projects\\ELISA_Platform\\elisa2

  2. Test the ML core works:
       cd backend
       python -c "from services.ml_bridge import check_ml_health; print(check_ml_health())"

  3. If you see any remaining errors above, fix them manually
     and re-run this script to verify.
""")


if __name__ == "__main__":
    main()