import os

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base  # noqa: F401  (re-exported: `from app.db.session import Base` keeps working)


def make_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        if os.getenv("VERCEL"):  # serverless: every invocation is short-lived, so no long-lived pool (it would leak connections)
            kwargs["poolclass"] = NullPool
        else:  # a small pool is plenty for one API process
            kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow, pool_recycle=1800)
        if settings.db_ssl:
            import certifi

            kwargs["connect_args"] = {"ssl": {"ca": settings.db_ssl_ca or certifi.where()}}
    return create_engine(url, **kwargs)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
