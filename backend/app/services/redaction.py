import logging
import re

from app.services.request_context import credentials

_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[REDACTED]"),
    (re.compile(r"""(?i)([?&](?:api[_-]?key|access_token|token|password|secret)=)[^&\s'"]+"""), r"\1[REDACTED]"),
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
]
_SENSITIVE = {"authorization", "x-api-key", "api_key", "access_token", "password", "old_password", "new_password", "secret"}


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if str(key).lower() in _SENSITIVE else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    for secret in sorted(credentials.get(), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


class RedactingFormatter(logging.Formatter):
    def __init__(self, original: logging.Formatter):
        super().__init__()
        self.original = original

    def format(self, record):
        return redact(self.original.format(record))


def configure_safe_logging():
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        for handler in logging.getLogger(name).handlers:
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter or logging.Formatter("%(levelname)s %(message)s")))
