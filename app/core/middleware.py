import logging
import os
from urllib.parse import parse_qsl, urlencode

log = logging.getLogger("campusnova.vercel")
"""Security headers and request-size guard (Chethana)."""
from starlette.middleware.base import BaseHTTPMiddleware

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        for k, v in HEADERS.items():
            if path.startswith(("/docs", "/redoc", "/openapi")) and k in ("Content-Security-Policy", "Cache-Control"):
                continue  # Swagger UI needs scripts; the API itself stays locked down
            if k == "Cache-Control" and path.endswith("/file"):
                continue  # photos may be cached by the browser
            response.headers.setdefault(k, v)
        return response


class VercelPathMiddleware:
    """On Vercel every request is rewritten to /api/index?__p=<original path> (see vercel.json). Restore the original
    path so FastAPI can route it, whichever entry file Vercel runs. Harmless everywhere else."""

    PREFIX = "/api/index"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "/")
            query = scope.get("query_string", b"").decode()
            pairs = parse_qsl(query, keep_blank_values=True)
            carried = [v for k, v in pairs if k == "__p"]
            new = path
            if carried:
                new = "/" + carried[0].lstrip("/")
                scope = dict(scope, query_string=urlencode([(k, v) for k, v in pairs if k != "__p"]).encode())
            elif path == self.PREFIX or path.startswith(self.PREFIX + "/"):
                new = path[len(self.PREFIX):] or "/"
            else:
                headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
                original = headers.get("x-vercel-original-path")
                if original and original.startswith("/") and not original.startswith(self.PREFIX):
                    new = original.split("?")[0]
            if new != path:
                scope = dict(scope, path=new, raw_path=new.encode())
            if os.getenv("VERCEL"):
                log.warning("vercel request: in=%s out=%s", path, scope["path"])
        await self.app(scope, receive, send)