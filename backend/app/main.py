from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
from app.config import settings
from app.database import create_tables
from app.routers import ingest, dashboard

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name}...")
    await create_tables()
    logger.info("Ready! Docs at http://localhost:8000/docs")
    yield
    logger.info("Shutting down...")

app = FastAPI(title="LogSense AI API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(dashboard.router)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "app": settings.app_name}

@app.get("/", tags=["System"])
async def root():
    return {"message": f"Welcome to {settings.app_name}", "docs": "/docs"}
