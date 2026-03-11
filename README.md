# Husky AI — Be an AI-Ready Husky!

A real-time prompt coaching tool built for Northeastern University. Chat on the left, get scored on the right — across five dimensions of AI prompting sophistication.

## What it does

Each message you send is scored across five dimensions (PSQ, CCM, TSI, CLM, RAS) and combined into a single **Prompting Effectiveness Index (PEI)**. The eval panel shows your score, classification (Novice / Intermediate / Advanced), suggestions for improvement, and red flags in real time.

## Stack

- **Frontend**: React + Vite + Tailwind CSS
- **Backend**: FastAPI + WebSockets + Google Gemini

## Running locally

**Backend**
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # add your GOOGLE_API_KEY
python main.py
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`

## Deploying

- **Backend** → Railway (set `GOOGLE_API_KEY` env var, root directory: `backend`)
- **Frontend** → Vercel (set `VITE_WS_URL=wss://your-backend.railway.app/ws`, root directory: `frontend`)
