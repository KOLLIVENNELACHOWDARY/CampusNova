"""Vercel entry point: the whole FastAPI app runs as one serverless function.

All paths are rewritten to /api/index (see vercel.json). Depending on the Vercel runtime the app can see
either the original path or the rewritten one, so restore the original path before FastAPI routes it.
"""
import logging

from app.main import app as _app

log = logging.getLogger("campusnova.vercel")
PREFIX = "/api/index"


class RestorePath:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "/")
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            original = headers.get("x-vercel-original-path") or headers.get("x-now-route-matches")
            if original and original.startswith("/") and not original.startswith(PREFIX):
                path = original.split("?")[0]
            elif path.startswith(PREFIX):
                path = path[len(PREFIX):] or "/"
            if path != scope.get("path"):
                scope = dict(scope, path=path, raw_path=path.encode())
            log.warning("request path=%s", scope["path"])
        await self.inner(scope, receive, send)


app = RestorePath(_app)