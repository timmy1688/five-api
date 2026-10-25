import logging

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.services.redaction import redact

logger = logging.getLogger(__name__)


def protocol_body(path: str, status: int, detail) -> dict:
    anthropic = path.startswith("/v1/messages")
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        body = dict(detail)
        if anthropic:
            body["type"] = "error"
            body["error"] = {"type": detail["error"].get("type", "api_error"),
                             "message": detail["error"].get("message", "Request rejected")}
        return body
    kind = ("authentication_error" if status == 401 else "permission_error" if status == 403
            else "rate_limit_error" if status == 429 else "invalid_request_error" if status < 500 else "api_error")
    error = {"type": kind, "message": str(detail) if isinstance(detail, str) else "Request rejected"}
    return {"type": "error", "error": error} if anthropic else {"error": {**error, "code": kind}}


def install_error_handlers(app):
    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if exc.status_code >= 400:
            logger.info("Request rejected request_id=%s status=%s path=%s",
                        getattr(request.state, "request_id", ""), exc.status_code, request.url.path)
        detail = redact(exc.detail)
        content = protocol_body(request.url.path, exc.status_code, detail) if request.url.path.startswith("/v1/") else {"detail": detail}
        headers = dict(exc.headers or {})
        if exc.status_code == 429:
            headers.setdefault("Retry-After", "60")
        if exc.status_code == 401:
            headers.setdefault("WWW-Authenticate", "Bearer")
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [{"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()]
        if request.url.path.startswith("/v1/"):
            return JSONResponse(status_code=400, content=protocol_body(
                request.url.path, 400, "Invalid request parameters",
            ))
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def service_error(request, exc):
        logger.exception("Request failed (%s)", type(exc).__name__)
        status = 503 if request.url.path.startswith("/v1/") else 500
        body = protocol_body(request.url.path, status, "Service unavailable") if status == 503 else {"detail": "Internal service error"}
        return JSONResponse(status_code=status, content=body)
