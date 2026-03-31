"""
ELISA Platform — Project Structure Creator
==========================================
Run this script ONCE from anywhere on your computer.
It creates the complete folder + file skeleton for ELISA_Platform.

Usage:
    python create_elisa_platform.py

    # Or specify a custom location:
    python create_elisa_platform.py --path "D:/Projects/ELISA_Platform"

What it creates:
    - All folders
    - All Python, JS, JSX, JSON, YAML, CSS files as empty stubs
    - .env.example files with correct keys (no real values)
    - A README.md in every major folder explaining what goes there
    - A VS Code workspace file (.code-workspace) so you can open
      everything in one window
"""

import argparse
import os
import sys
from pathlib import Path


# ── Colour helpers (Windows-safe) ────────────────────────────────────────────
def _supports_color():
    return sys.platform != "win32" or "ANSICON" in os.environ or "WT_SESSION" in os.environ

GREEN  = "\033[92m" if _supports_color() else ""
YELLOW = "\033[93m" if _supports_color() else ""
CYAN   = "\033[96m" if _supports_color() else ""
RED    = "\033[91m" if _supports_color() else ""
BOLD   = "\033[1m"  if _supports_color() else ""
RESET  = "\033[0m"  if _supports_color() else ""

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def info(msg): print(f"  {CYAN}→{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}!{RESET}  {msg}")
def head(msg): print(f"\n{BOLD}{msg}{RESET}")


# ═════════════════════════════════════════════════════════════════════════════
# FILE CONTENTS
# Each entry is (relative_path, file_content).
# Paths are relative to the project root (ELISA_Platform/).
# Files that already exist are NEVER overwritten — safe to re-run.
# ═════════════════════════════════════════════════════════════════════════════

FILES = {

    # ── Root ──────────────────────────────────────────────────────────────────

    "Procfile": """\
web: cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
""",

    ".gitignore": """\
# Python
__pycache__/
*.py[cod]
*.pyo
.venv/
venv/
*.egg-info/
dist/
build/
.pytest_cache/

# Environment files — NEVER commit these
.env
.env.local
.env.*.local
backend/.env
frontend/.env.local

# Secrets
gee_key.json
*.key
*.pem

# VS Code
.vscode/settings.json

# Node
node_modules/
frontend/dist/
frontend/.vite/

# Data and models (large files)
elisa2/data/
elisa2/saved_models/
elisa2/logs/

# OS
.DS_Store
Thumbs.db
""",

    "README.md": """\
# ELISA Platform 2.0

Smart irrigation decision system for Western UP smallholder farmers.
Built at Jamia Millia Islamia — EE Dept B.Tech Major Project.

## Folders

| Folder      | What it is                                      |
|-------------|------------------------------------------------|
| `elisa2/`   | Existing ML core — PatchTST + MPC + simulation |
| `backend/`  | FastAPI web backend                            |
| `frontend/` | React web app                                  |

## Quick start

```bash
# 1. Backend
cd backend
python -m venv venv && venv\\Scripts\\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

See docs/SETUP.md for the full setup guide.
""",

    # ── VS Code workspace ─────────────────────────────────────────────────────

    "ELISA_Platform.code-workspace": """\
{
  "folders": [
    { "name": "🌾 Root",     "path": "." },
    { "name": "🤖 elisa2",   "path": "elisa2" },
    { "name": "⚡ backend",  "path": "backend" },
    { "name": "🌐 frontend", "path": "frontend" }
  ],
  "settings": {
    "editor.formatOnSave": true,
    "editor.tabSize": 4,
    "[javascript]": { "editor.tabSize": 2 },
    "[javascriptreact]": { "editor.tabSize": 2 },
    "[json]": { "editor.tabSize": 2 },
    "python.defaultInterpreterPath": "./backend/venv/Scripts/python.exe",
    "files.exclude": {
      "**/node_modules": true,
      "**/__pycache__": true,
      "**/*.pyc": true,
      "**/venv": true
    },
    "search.exclude": {
      "**/node_modules": true,
      "**/venv": true,
      "elisa2/data": true
    },
    "editor.rulers": [100],
    "files.associations": {
      "*.jsx": "javascriptreact",
      ".env*": "properties"
    }
  },
  "extensions": {
    "recommendations": [
      "ms-python.python",
      "ms-python.pylance",
      "dbaeumer.vscode-eslint",
      "esbenp.prettier-vscode",
      "bradlc.vscode-tailwindcss",
      "mtxr.sqltools",
      "formulahendry.auto-rename-tag",
      "christian-kohler.path-intellisense"
    ]
  }
}
""",

    # ── elisa2/ placeholder ───────────────────────────────────────────────────

    "elisa2/README.md": """\
# elisa2 — ML Core

**DO NOT edit files in this folder from the web platform.**
This is the existing ELISA 2.0 ML codebase.

## How to populate this folder

Copy your entire existing `ELISA_2.1` folder contents here.
The file list should include:

    config/settings.py
    config/agronomy.yaml
    ingestion/gee_client.py
    ingestion/gee_extractor.py
    ingestion/era5_loader.py
    ingestion/nasa_power.py
    ingestion/pipeline.py
    features/crop_calendar.py
    features/eto.py
    features/soil_balance.py
    features/builder.py
    models/patchtst/model.py
    models/patchtst/dataset.py
    models/patchtst/trainer.py
    models/downscaler/rf_model.py
    models/downscaler/trainer.py
    decision/tariff.py
    decision/state_manager.py
    decision/mpc.py
    simulation/farmer_blind.py
    simulation/farmer_minor.py
    simulation/farmer_major.py
    simulation/metrics.py
    simulation/compare.py
    farm/geocoder.py
    farm/manager.py
    utils/dates.py
    dashboard/app.py
    pipelines/run.py
    gee_key.json
    .env

After copying, set ELISA2_PATH in backend/.env to the
absolute path of this folder.
""",

    # ── backend/ ──────────────────────────────────────────────────────────────

    "backend/README.md": """\
# backend — FastAPI Web Backend

## Setup

```bash
cd backend
python -m venv venv
venv\\Scripts\\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt
pip install -r ../elisa2/requirements.txt

# Copy and fill in environment variables
copy .env.example .env

# Run database migrations
alembic upgrade head

# Start development server
uvicorn main:app --reload --port 8000
```

## API docs
Visit http://localhost:8000/docs once the server is running.

## Folder structure

    main.py           ← FastAPI app entry point
    core/             ← config, database, security, scheduler
    db_models/        ← SQLAlchemy ORM models (4 tables)
    api/              ← route handlers (6 files)
    services/         ← business logic: ML bridge, savings, WhatsApp, OTP
    alembic/          ← database migrations
""",

    "backend/main.py":               "# Paste contents from the generated main.py here\n",
    "backend/requirements.txt":      "# Paste contents from the generated requirements.txt here\n",

    "backend/.env.example": """\
# Copy this file to .env and fill in real values.
# NEVER commit .env to git.

# ── Database (Supabase) ───────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@db.YOURREF.supabase.co:5432/postgres

# ── Auth ─────────────────────────────────────────────────────────────
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=paste_64_char_hex_here
JWT_EXPIRE_DAYS=30

# ── OTP (Fast2SMS) ───────────────────────────────────────────────────
# Leave blank for dev mode (OTP prints to terminal)
FAST2SMS_API_KEY=

# ── WhatsApp (Meta Cloud API) ────────────────────────────────────────
# Leave blank to disable alerts
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=

# ── ELISA ML core ────────────────────────────────────────────────────
# Absolute path to the elisa2/ folder on your machine
# Windows example:
ELISA2_PATH=C:\\Projects\\ELISA_Platform\\elisa2

# ── GEE ─────────────────────────────────────────────────────────────
GEE_ENABLED=true
GEE_SERVICE_ACCOUNT=elisa-gee-runner@elisa-irrigation-research.iam.gserviceaccount.com
GEE_KEY_FILE=C:\\Projects\\ELISA_Platform\\elisa2\\gee_key.json

# ── App ──────────────────────────────────────────────────────────────
APP_ENV=development
CORS_ORIGINS=["http://localhost:5173"]
LOG_LEVEL=INFO
""",

    # backend/core/
    "backend/core/__init__.py":   "",
    "backend/core/config.py":     "# Paste contents from the generated core/config.py here\n",
    "backend/core/database.py":   "# Paste contents from the generated core/database.py here\n",
    "backend/core/security.py":   "# Paste contents from the generated core/security.py here\n",
    "backend/core/scheduler.py":  "# Paste contents from the generated core/scheduler.py here\n",

    # backend/db_models/
    "backend/db_models/__init__.py":  "# Paste contents from the generated db_models/__init__.py here\n",
    "backend/db_models/user.py":      "# Paste contents from the generated db_models/user.py here\n",
    "backend/db_models/farm.py":      "# Paste contents from the generated db_models/farm.py here\n",
    "backend/db_models/prediction.py":"# Paste contents from the generated db_models/prediction.py here\n",
    "backend/db_models/savings.py":   "# Paste contents from the generated db_models/savings.py here\n",

    # backend/api/
    "backend/api/__init__.py":     "",
    "backend/api/auth.py":         "# Paste contents from the generated api/auth.py here\n",
    "backend/api/farms.py":        "# Paste contents from the generated api/farms.py here\n",
    "backend/api/predictions.py":  "# Paste contents from the generated api/predictions.py here\n",
    "backend/api/weather.py":      "# Paste contents from the generated api/weather.py here\n",
    "backend/api/savings.py":      "# Paste contents from the generated api/savings.py here\n",
    "backend/api/irrigation.py":   "# Paste contents from the generated api/irrigation.py here\n",

    # backend/services/
    "backend/services/__init__.py":      "",
    "backend/services/ml_bridge.py":     "# Paste contents from the generated services/ml_bridge.py here\n",
    "backend/services/savings_engine.py":"# Paste contents from the generated services/savings_engine.py here\n",
    "backend/services/whatsapp.py":      "# Paste contents from the generated services/whatsapp.py here\n",
    "backend/services/otp.py":           "# Paste contents from the generated services/otp.py here\n",

    # backend/alembic/
    "backend/alembic/alembic.ini": "# Paste contents from the generated alembic/alembic.ini here\n",
    "backend/alembic/env.py":      "# Paste contents from the generated alembic/env.py here\n",
    "backend/alembic/versions/20240101_0001_initial_schema.py":
        "# Paste contents from the generated migration file here\n",

    # ── frontend/ ─────────────────────────────────────────────────────────────

    "frontend/README.md": """\
# frontend — React Web App

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in VITE_API_URL for production

# Start dev server (backend must be running on port 8000)
npm run dev
```

Open http://localhost:5173

## Build for production
```bash
npm run build    # outputs to dist/
```

## Folder structure

    src/
      App.jsx          ← Router, auth guard, sidebar, farm context
      main.jsx         ← React entry point
      index.css        ← Design tokens, global styles
      api/
        client.js      ← Axios instance + all API functions
      pages/
        Login.jsx      ← OTP authentication
        FarmSetup.jsx  ← Leaflet polygon draw (most complex page)
        Dashboard.jsx  ← Current status overview
        Forecast.jsx   ← 7-day SM + rain chart
        Decision.jsx   ← MPC decision + irrigation log
        Savings.jsx    ← Season savings vs blind baseline
      components/
        MetricCard.jsx ← Numeric metric display card
        DecisionCard.jsx ← MPC decision banner
        SMChart.jsx    ← Recharts SM + rain chart
        FarmMap.jsx    ← Leaflet farm polygon display
""",

    "frontend/index.html":        "<!-- Paste contents from the generated index.html here -->\n",
    "frontend/package.json":      "{}  // Paste contents from the generated package.json here\n",
    "frontend/vite.config.js":    "// Paste contents from the generated vite.config.js here\n",
    "frontend/tailwind.config.js":"// Paste contents from the generated tailwind.config.js here\n",
    "frontend/postcss.config.js": "// Paste contents from the generated postcss.config.js here\n",

    "frontend/.env.example": """\
# Copy to .env.local — NEVER commit .env.local

# Backend API base URL.
# Leave blank in dev — Vite proxies /api → localhost:8000 automatically.
# Set to your Render URL for production.
VITE_API_URL=https://your-elisa-backend.onrender.com
""",

    "frontend/public/favicon.svg": """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="8" fill="#2D1F14"/>
  <text x="16" y="23" font-size="20" text-anchor="middle">🌾</text>
</svg>
""",

    # frontend/src/
    "frontend/src/main.jsx":   "// Paste contents from the generated main.jsx here\n",
    "frontend/src/App.jsx":    "// Paste contents from the generated App.jsx here\n",
    "frontend/src/index.css":  "/* Paste contents from the generated index.css here */\n",

    # frontend/src/api/
    "frontend/src/api/client.js": "// Paste contents from the generated api/client.js here\n",

    # frontend/src/pages/
    "frontend/src/pages/Login.jsx":     "// Paste contents from the generated Login.jsx here\n",
    "frontend/src/pages/FarmSetup.jsx": "// Paste contents from the generated FarmSetup.jsx here\n",
    "frontend/src/pages/Dashboard.jsx": "// Paste contents from the generated Dashboard.jsx here\n",
    "frontend/src/pages/Forecast.jsx":  "// Paste contents from the generated Forecast.jsx here\n",
    "frontend/src/pages/Decision.jsx":  "// Paste contents from the generated Decision.jsx here\n",
    "frontend/src/pages/Savings.jsx":   "// Paste contents from the generated Savings.jsx here\n",

    # frontend/src/components/
    "frontend/src/components/MetricCard.jsx":   "// Paste contents from the generated MetricCard.jsx here\n",
    "frontend/src/components/DecisionCard.jsx": "// Paste contents from the generated DecisionCard.jsx here\n",
    "frontend/src/components/SMChart.jsx":      "// Paste contents from the generated SMChart.jsx here\n",
    "frontend/src/components/FarmMap.jsx":      "// Paste contents from the generated FarmMap.jsx here\n",
}


# ═════════════════════════════════════════════════════════════════════════════
# BUILDER
# ═════════════════════════════════════════════════════════════════════════════

def create_structure(root: Path) -> None:
    head(f"Creating ELISA Platform at: {root}")

    created_dirs  = 0
    created_files = 0
    skipped_files = 0

    for rel_path_str, content in FILES.items():
        file_path = root / rel_path_str
        dir_path  = file_path.parent

        # Create parent directories
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            ok(f"Created folder:  {dir_path.relative_to(root)}")
            created_dirs += 1

        # Write file only if it doesn't exist (never overwrite)
        if file_path.exists():
            warn(f"Already exists, skipped: {file_path.relative_to(root)}")
            skipped_files += 1
        else:
            file_path.write_text(content, encoding="utf-8")
            ok(f"Created file:    {file_path.relative_to(root)}")
            created_files += 1

    # Create a few extra empty __init__.py files that Python needs
    extra_inits = [
        "elisa2/__init__.py",
        "backend/alembic/versions/__init__.py",
    ]
    for rel in extra_inits:
        p = root / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
            ok(f"Created file:    {rel}")
            created_files += 1

    # Summary
    head("Done!")
    print(f"""
  {GREEN}Created:{RESET}  {created_files} files, {created_dirs} folders
  {YELLOW}Skipped:{RESET}  {skipped_files} files (already existed)

  {BOLD}Next steps:{RESET}

  1. Open VS Code:
     {CYAN}code "{root / 'ELISA_Platform.code-workspace'}"{RESET}

  2. Copy your existing ELISA_2.1 files into:
     {CYAN}{root / 'elisa2'}{RESET}

  3. Paste the generated code into each stub file
     (each file says "Paste contents from generated X here")

  4. Fill in backend{os.sep}.env:
     {CYAN}{root / 'backend' / '.env'}{RESET}
     (copy from .env.example first)

  5. Install backend dependencies:
     {CYAN}cd backend && python -m venv venv && venv\\Scripts\\activate{RESET}
     {CYAN}pip install -r requirements.txt{RESET}

  6. Run database migration:
     {CYAN}alembic upgrade head{RESET}

  7. Start backend:
     {CYAN}uvicorn main:app --reload{RESET}

  8. Install frontend dependencies (new terminal):
     {CYAN}cd frontend && npm install && npm run dev{RESET}
""")


def main():
    parser = argparse.ArgumentParser(
        description="Create the ELISA Platform project structure."
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help='Where to create the project. Default: ELISA_Platform in current directory.',
    )
    args = parser.parse_args()

    if args.path:
        root = Path(args.path).resolve()
    else:
        # Default: create ELISA_Platform/ next to this script
        root = Path(__file__).parent.resolve() / "ELISA_Platform"

    # Safety check — don't create inside system folders
    forbidden = [Path.home() / "AppData", Path("C:/Windows"), Path("/usr"), Path("/bin")]
    for f in forbidden:
        try:
            root.relative_to(f)
            print(f"{RED}Error: refusing to create project inside {f}{RESET}")
            sys.exit(1)
        except ValueError:
            pass

    if root.exists() and any(root.iterdir()):
        print(f"\n{YELLOW}Warning: {root} already exists and is not empty.{RESET}")
        answer = input("  Continue anyway (existing files will NOT be overwritten)? [y/N] ")
        if answer.strip().lower() != "y":
            print("Aborted.")
            sys.exit(0)

    root.mkdir(parents=True, exist_ok=True)
    create_structure(root)


if __name__ == "__main__":
    main()