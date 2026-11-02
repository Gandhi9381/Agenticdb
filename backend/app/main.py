"""
AgenticDB FastAPI Application Entry Point
"""
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env before config initialises
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app.core.config import get_settings
from app.database.engine import init_db
from app.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AgenticDB starting up…")
    init_db()
    logger.info("Database ready.")
    if not settings.llm_configured:
        logger.warning(
            "LLM_API_KEY not set — AI features (SQL generation, diagnosis) are disabled. "
            "Set LLM_API_KEY in your .env file to enable them."
        )
    yield
    logger.info("AgenticDB shutting down.")


app = FastAPI(
    title="AgenticDB",
    description="Autonomous AI Database Administrator for Query Optimization and Proactive Insights",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {
        "name": "AgenticDB",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "api": "/api",
    }
