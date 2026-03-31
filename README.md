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
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

See docs/SETUP.md for the full setup guide.
