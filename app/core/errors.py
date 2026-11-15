"""One error format for the whole API (Nakshatra):

    {"error": {"code": "not_found", "message": "...", "details": [...]}}

Every handler below maps a family of exceptions to a stable `code` the frontend can switch on.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.common import BusinessRuleError, ComplaintValidationError, NotFoundError

logger = logging.getLogger("campusnova.api")

_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
          409: "conflict", 413: "payload_too_large", 415: "unsupported_media_type", 422: "validation_error",
          423: "account_locked", 429: "too_many_requests", 503: "unavailable"}


def error_body(code: str, message: str, details=None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(error_body(_CODES.get(exc.status_code, "error"), str(exc.detail)), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")), "message": e["msg"]}
                   for e in exc.errors()]
        return JSONResponse(error_body("validation_error", "The request is not valid.", details), status_code=422)

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError):
        return JSONResponse(error_body("not_found", str(exc)), status_code=404)

    @app.exception_handler(ComplaintValidationError)
    async def complaint_invalid(request: Request, exc: ComplaintValidationError):
        return JSONResponse(error_body("validation_error", str(exc)), status_code=422)

    @app.exception_handler(BusinessRuleError)
    async def business_rule(request: Request, exc: BusinessRuleError):
        return JSONResponse(error_body("conflict", str(exc)), status_code=409)

    @app.exception_handler(PermissionError)
    async def permission(request: Request, exc: PermissionError):
        return JSONResponse(error_body("forbidden", str(exc) or "Not allowed."), status_code=403)

    @app.exception_handler(IntegrityError)
    async def integrity(request: Request, exc: IntegrityError):
        logger.warning("integrity error: %s", exc.orig)
        return JSONResponse(error_body("conflict", "That conflicts with existing data."), status_code=409)

    @app.exception_handler(OperationalError)
    async def database_down(request: Request, exc: OperationalError):
        logger.error("database error: %s", exc)
        return JSONResponse(error_body("unavailable", "The database is not reachable right now. Please try again."), status_code=503)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(error_body("internal_error", "Something went wrong on our side."), status_code=500)
