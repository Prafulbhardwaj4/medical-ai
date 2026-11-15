# MedScribe — AI Medical Scribe Assistant

Hospital management software for Indian hospitals and nursing homes: OPD tokens and queue, consultations with an AI scribe (record a consultation → AI structures the prescription → PDF), pharmacy, lab, GST billing, online appointment booking, a patient portal, admissions and chat. Patient messages are prepared in a WhatsApp messages list that staff send by hand.

Running it live? Read [docs/RUNBOOK.md](docs/RUNBOOK.md) (deploy, rollback, backups, key rotation, incidents, every setting).

## Tech Stack
- **Backend**: FastAPI + SQLAlchemy + Alembic migrations, SQLite (dev) / PostgreSQL (prod)
- **Auth**: JWT login tokens, captcha, 2FA for super admins, separate patient portal login
- **Speech-to-Text**: Sarvam (live streaming)
- **AI Structuring**: Groq API
- **PDF**: ReportLab
- **Files**: local disk, or an S3-compatible bucket (AWS S3, Cloudflare R2, Backblaze B2)
- **WhatsApp**: a messages list that staff send by hand (no WhatsApp provider is connected)
- **Monitoring**: optional Sentry; `/health/live` and `/health` endpoints
- **Frontend**: HTML + CSS + Vanilla JS on Vercel (API address in `frontend/config.js`)
- **Tests and CI**: pytest, GitHub Actions (tests, migration safety, dependency audit, secret scan, nightly encrypted database backup)

## Setup

### 1. Clone & configure
```bash
git clone <repo>
cd medscribe
cp .env.example backend/.env
# Fill in your API keys in backend/.env (the app reads .env from the backend folder)
```

### 2. Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload     # local development only; never use --reload in production
```

Run the tests:
```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

### 3. Frontend
Open `frontend/pages/login.html` directly in a browser, or serve with:
```bash
python -m http.server 5500 --directory frontend
```


## Project Structure
```
medscribe/
├── .github/               # CI, Dependabot and the nightly database backup workflow
├── docs/
│   └── RUNBOOK.md         # deploy, rollback, backups, key rotation, incidents, every setting
├── backend/
│   ├── app/
│   │   ├── routers/       # auth, patients, consultations, admissions, billing, lab, pharmacy, portal, chat, ...
│   │   ├── models/        # SQLAlchemy DB models
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   ├── services/      # sarvam (speech), groq (AI), pdf, storage logic
│   │   ├── utils/         # auth, audit, rate limits, encryption, helpers
│   │   ├── main.py        # FastAPI app entry
│   │   ├── database.py    # DB connection
│   │   └── config.py      # env config
│   ├── migrations/        # Alembic migrations (additive only)
│   ├── scripts/           # release, backup, key-rotation and check scripts (see docs/RUNBOOK.md)
│   ├── tests/             # pytest tests
│   └── requirements.txt
└── frontend/
    ├── pages/             # login, dashboard, patient, consultation, admissions, pharmacy, lab, portal, ...
    ├── config.js          # API address, loaded before js/api.js
    ├── css/style.css
    └── js/               # api.js (fetch helpers), auth.js
```