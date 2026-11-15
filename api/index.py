"""Vercel entry point: the whole FastAPI app runs as one serverless function (all paths are rewritten here)."""
from app.main import app  # noqa: F401  (Vercel looks for an ASGI object called `app`)
