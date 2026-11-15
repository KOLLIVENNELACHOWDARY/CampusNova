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
