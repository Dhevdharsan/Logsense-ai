# LogSense AI

**AI-powered log intelligence for SRE teams.**
Detect anomalies, cluster related errors, and get plain-English root cause summaries — all running locally.

## What It Does

- Ingests structured JSON logs via REST API
- Detects anomalous log patterns using Isolation Forest
- Groups similar errors using DBSCAN clustering
- Generates plain-English root cause summaries using a local LLM (Ollama)
- Displays everything in a professional SRE dashboard

## Quick Start

git clone https://github.com/Dhevdharsan/Logsense-ai.git
cd Logsense-ai
docker compose up --build

Then load sample data:
python3 scripts/generate_sample_logs.py --count 500

Open http://localhost:3000

## Tech Stack

- Backend: FastAPI + Python 3.11 + SQLAlchemy (async)
- Database: PostgreSQL 16 + pgvector extension
- Cache: Redis 7
- ML: scikit-learn (Isolation Forest + DBSCAN + TF-IDF)
- LLM: Ollama (runs locally, no API key needed)
- Frontend: Next.js 14 + TypeScript + Tailwind + Recharts

## Architecture

Browser (localhost:3000)
    |
FastAPI Backend (localhost:8000)
    |
    |-- PostgreSQL + pgvector  (stores logs + ML vectors)
    |-- Redis                  (caches LLM summaries)
    |-- Ollama                 (runs LLM locally)

## API Reference

Interactive docs at http://localhost:8000/docs

Key endpoints:
- POST /api/v1/logs/ingest        Submit logs
- GET  /api/v1/logs               Browse logs
- POST /api/v1/analyze/run        Trigger ML pipeline
- GET  /api/v1/dashboard/summary  Dashboard stats
- GET  /api/v1/clusters           View clusters with AI summaries

## ML Pipeline

Raw Logs -> TF-IDF Vectorize -> Isolation Forest -> DBSCAN -> LLM Summary
                                  (anomaly score)  (clusters)  (cached 6hr)

## Week-by-Week Build

| Week | Goal                                          | Status |
|------|-----------------------------------------------|--------|
| 1    | Docker, DB schema, ingest API, dashboard      | Done   |
| 2    | ML pipeline: anomaly detection + clustering   | Next   |
| 3    | Ollama LLM integration + cluster summaries    | Soon   |
| 4    | Frontend polish + anomaly views               | Soon   |

## Running Locally Without Docker

Terminal 1 - infrastructure:
docker compose up postgres redis

Terminal 2 - backend:
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

Terminal 3 - frontend:
cd frontend
npm install
npm run dev
