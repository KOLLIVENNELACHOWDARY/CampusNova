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
    """On Vercel every request is rewritten to /api/index. Restore the original path so FastAPI can route it,
    whichever entry file Vercel decides to run (api/index.py or app/main.py). Harmless everywhere else."""

    PREFIX = "/api/index"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "/")
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            original = headers.get("x-vercel-original-path") or headers.get("x-matched-path")
            new = path
            if original and original.startswith("/") and not original.startswith(self.PREFIX) and "[" not in original:
                new = original.split("?")[0]
            elif path == self.PREFIX or path.startswith(self.PREFIX + "/"):
                new = path[len(self.PREFIX):] or "/"
            if new != path:
                scope = dict(scope, path=new, raw_path=new.encode())
        await self.app(scope, receive, send)