# VidyaVerse - Ivy League Opportunity Intelligence

VidyaVerse is a production-grade, full-stack web application designed as a Real-Time Ivy League Opportunity Intelligence & Student Competency Network for students focusing on elite academic and professional opportunities.

## 🚀 Key Features
- **AI-Powered Opportunity Feed**: Real-time opportunity scraping, categorized by NLP zero-shot classification (HuggingFace).
- **Resilient Live Scraping**: Continuous ingestion with retries, dedupe, deadline-based expiry cleanup, and runtime status for Ivy RSS, Unstop, Naukri, Internshala, Hack2Skill, Freshersworld, and best-effort Indeed India sources.
- **InCoScore Ranking Engine**: Ranks students based on achievements and parsed resumes (spaCy NER).
- **Smart Automated Applications**: Playwright-based form autofill with optional real submit.
- **Academic Social Network**: Connect with researchers and innovators in specialized domain groups.
- **Premium SaaS UI**: Responsive, glassmorphic dark theme built with Next.js and Vanilla CSS.

---

## 🏗️ Architecture Stack
- **Backend:** FastAPI, Python 3.12, Beanie ODM, MongoDB Atlas
- **AI Engine:** spaCy (NER parsing), HuggingFace Transformers (distilbart-mnli-12-3 zero-shot tracking)
- **Frontend:** Next.js (App Router), React, Vanilla CSS

---

## ⚙️ Running Locally

### 1. Database Setup
The backend uses MongoDB. Configure your database URL in `backend/.env`:
```bash
MONGODB_URL=mongodb+srv://<username>:<password>@<cluster>/?appName=vidyaverse
MONGODB_DB_NAME=vidyaverse
```

### 2. Backend Setup
Navigate to the `backend` directory, activate the virtual environment, and run the FastAPI server:
```bash
cd backend
source venv/bin/activate
# Install requirements if not done: pip install -r requirements.txt

# Install browser engine for Playwright auto-application
playwright install chromium

# Start Uvicorn Dev Server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Backend will be live at `http://localhost:8000`. API docs available at `http://localhost:8000/docs`.

Optional scraper tuning in `backend/.env`:
```bash
SCRAPER_INTERVAL_MINUTES=30
SCRAPER_TIMEOUT_SECONDS=20
SCRAPER_HTTP_RETRIES=4
SCRAPER_RETRY_BACKOFF=0.8
SCRAPER_UNSTOP_MAX_ITEMS=60
SCRAPER_NAUKRI_MAX_ITEMS=25
SCRAPER_INTERNSHALA_MAX_ITEMS=30
SCRAPER_HACK2SKILL_MAX_ITEMS=24
SCRAPER_FRESHERSWORLD_MAX_ITEMS=30
SCRAPER_INDEED_MAX_ITEMS=20
```

Scraper runtime endpoints:
- `GET /api/v1/opportunities/scraper-status`
- `POST /api/v1/opportunities/trigger-scraper`

### 3. Frontend Setup
Navigate to the `frontend` directory and run the Next.js development server:
```bash
cd frontend
# Install dependencies
npm install

# Optional: override backend base URL (default is http://127.0.0.1:8000)
echo "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000" > .env.local

# Optional: choose Puter Claude model for Vidya Chat
echo "NEXT_PUBLIC_PUTER_MODEL=claude-sonnet-4-6" >> .env.local

# Run the dev server
npm run dev
```
Frontend will be live at `http://localhost:3000`.

### 3.1 AI Chat via Puter.js
- The frontend loads Puter.js automatically from `https://js.puter.com/v2/`.
- Vidya Chat uses `puter.ai.chat(...)` directly (no OpenRouter key needed in frontend).
- Default model: `claude-sonnet-4-6` (override with `NEXT_PUBLIC_PUTER_MODEL`).

### 4. Optional Auto-Submit Mode
By default, application automation opens pages and fills forms without clicking submit.
To enable real submit attempts:
```bash
AUTO_SUBMIT_ENABLED=true
```

### 5. OTP Auth (Signup / Signin)
- OTPs are now stored in MongoDB (`otp_codes` collection) with expiration (TTL).
- `/api/v1/auth/send-otp` supports `purpose: "signup" | "signin"`.
- `/api/v1/auth/verify-otp` validates OTP and issues JWT.
- OTP delivery is strict email-only (no debug/demo OTP fallback).
- For real email delivery, configure SMTP in `backend/.env`:
```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASSWORD=your_app_password
SMTP_FROM_EMAIL=your_email@example.com
```

---

## 🛠️ Project Structure
- `backend/app` - Contains the FastAPI application, database connections, and AI Engine.
  - `services/ai_engine.py` - Core NLP classification and Resume parsing logic.
  - `services/scraper.py` - Web scraper logic simulation.
  - `models/` - Beanie document models (User, Profile, Opportunity, Application, Post, Comment).
- `backend/alembic` - Legacy migration setup (not used in current MongoDB flow).
- `frontend/src/app` - Next.js App router containing UI (Landing, Dashboard, Social, Opportunities).
- `frontend/src/app/globals.css` - Custom premium CSS aesthetics including glassmorphism tokens.
