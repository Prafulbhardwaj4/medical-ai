# MedScribe — AI Medical Scribe Assistant

AI-powered assistant for doctors: record a consultation → AI structures the prescription → generates PDF → sends to patient via WhatsApp.

## Tech Stack
- **Backend**: FastAPI + SQLite (dev) / PostgreSQL (prod)
- **Auth**: JWT
- **Speech-to-Text**: OpenAI Whisper API
- **AI Structuring**: Groq API
- **PDF**: ReportLab
- **WhatsApp**: Twilio WhatsApp API
- **Frontend**: HTML + CSS + Vanilla JS

## Setup

### 1. Clone & configure
```bash
git clone <repo>
cd medscribe
cp .env.example .env
# Fill in your API keys in .env
```

### 2. Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 3. Frontend
Open `frontend/pages/login.html` directly in a browser, or serve with:
```bash
python -m http.server 5500 --directory frontend
```

## Twilio WhatsApp Sandbox Setup
1. Go to [Twilio Console](https://console.twilio.com/) → Messaging → Try it out → Send a WhatsApp message
2. Note the sandbox number (default: `+1 415 523 8886`)
3. Have the patient's phone send `join <sandbox-keyword>` to that number to opt in
4. Set `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886` in your `.env`

## Project Structure
```
medscribe/
├── backend/
│   ├── app/
│   │   ├── routers/       # auth, patients, consultations, prescriptions
│   │   ├── models/        # SQLAlchemy DB models
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   ├── services/      # whisper, groq, pdf, twilio logic
│   │   ├── utils/         # token gen, helpers
│   │   ├── main.py        # FastAPI app entry
│   │   ├── database.py    # DB connection
│   │   └── config.py      # env config
│   └── requirements.txt
└── frontend/
    ├── pages/             # login, dashboard, patient, consultation
    ├── css/style.css
    └── js/               # api.js (fetch helpers), auth.js
```