"""CampusNova API entry point. Wires routers, CORS, security headers, error format and (optionally) the scheduler."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (admin_jobs, ai_review, auth, complaints, cron, dashboard, departments, notifications, priority,
                     users, workflow)
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.middleware import SecurityHeadersMiddleware, VercelPathMiddleware

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if os.getenv("CAMPUSNOVA_SCHEDULER", "0") == "1":
        from app.jobs.scheduler import build_scheduler

        scheduler = build_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
              description="Campus complaint & maintenance management with AI priority, auto-assignment and SLA escalation.")
app.add_middleware(VercelPathMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
install_error_handlers(app)

for module in (auth, users, departments, complaints, workflow, ai_review, priority, notifications, dashboard, admin_jobs, cron):
    app.include_router(module.router)


@app.get("/", tags=["meta"])
def root():
    return {"message": "CampusNova API is running", "version": settings.app_version}


@app.get("/health", tags=["meta"])
def health_check():
    return {"status": "healthy"}


@app.get("/health/db", tags=["meta"])
def health_db():
    from sqlalchemy import text

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "reachable"}