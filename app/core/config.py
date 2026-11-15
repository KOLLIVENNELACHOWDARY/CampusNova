"""Application settings. Values come from environment variables or a local `.env` file (see `.env.example`)."""
import os
from typing import List

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()  # so the feature switches read with os.getenv (auto-assign, notify mode, scheduler) also honour `.env`


class Settings(BaseSettings):
    app_name: str = "CampusNova"
    app_version: str = "1.0.0"
    environment: str = "development"  # development | production
    database_url: str = "mysql+pymysql://campusnova_user:change_me@localhost:3306/campusnova"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # security (Chethana)
    secret_key: str = "dev-only-secret-change-me-before-deploying-1234567890"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    firebase_project_id: str = ""
    auth_enabled: bool = True

    # web
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # complaint media (Jahnavi)
    max_upload_mb: int = 4  # Vercel rejects request bodies over 4.5 MB; the web app shrinks photos before upload
    db_ssl: bool = False  # hosted MySQL (Aiven, TiDB Cloud, PlanetScale...) requires TLS: set DB_SSL=true
    db_ssl_ca: str = ""  # optional CA file; default is the certifi bundle
    cron_secret: str = ""  # Bearer token for /cron/* (Vercel sends it automatically when CRON_SECRET is set)
    max_images_per_complaint: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("secret_key")
    @classmethod
    def _secret_not_empty(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("SECRET_KEY must be at least 16 characters")
        return v

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
if settings.is_production and settings.secret_key.startswith("dev-only"):
    raise RuntimeError("Set a real SECRET_KEY before running with ENVIRONMENT=production")
