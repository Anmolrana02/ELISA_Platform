# backend — FastAPI Web Backend

## Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
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
